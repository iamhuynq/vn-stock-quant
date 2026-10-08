"""Phase 5 event catalog: conditions, point in time, event study (descriptive), daily scan copy."""

from datetime import UTC, date, datetime

import duckdb
import numpy as np
import pandas as pd
import pytest

from fireant_crawler.store.warehouse import Warehouse
from quant_research.build import build
from quant_research.event_study import run_event_study
from quant_research.events import EVENT_TYPES, catalog_version
from quant_research.results import ResearchParams, ResultsStore
from tests.research.synthetic import build_synthetic_warehouse

NOW = datetime(2026, 10, 8, 20, 0, tzinfo=UTC)
PARAMS = ResearchParams(min_adv_value=0, min_session_index=0, min_stocks_per_date=1)
BASE = "is_traded AND NOT price_jump AND NOT bad_source_date"
DIRECT = {   # event type -> condition on stock_features (BREAKOUT/BREAKDOWN checked with pandas)
    "PRICE_SURGE": "return_1d >= 0.05",
    "PRICE_DROP": "return_1d <= -0.05",
    "VOLUME_SPIKE": "volume_ratio_20 >= 3",
    "FOREIGN_BUY_SPIKE": "foreign_net_value / nullif(adv_value_20, 0) >= 0.5 AND NOT foreign_inconsistent",
    "FOREIGN_SELL_SPIKE": "foreign_net_value / nullif(adv_value_20, 0) <= -0.5 AND NOT foreign_inconsistent",
    "ORDER_IMBALANCE_SPIKE_BUY": "order_imbalance >= 0.5",
    "ORDER_IMBALANCE_SPIKE_SELL": "order_imbalance <= -0.5",
    "VOLATILITY_SPIKE": "high_low_range / nullif(atr_14_pct, 0) >= 2.5",
    "DIVERGENCE_UP_FOREIGN_SELL": "return_5d >= 0.05 AND foreign_net_5d < 0",
    "DIVERGENCE_DOWN_FOREIGN_BUY": "return_5d <= -0.05 AND foreign_net_5d > 0",
}


@pytest.fixture(scope="module")
def research(tmp_path_factory):
    d = tmp_path_factory.mktemp("events")
    build_synthetic_warehouse(d / "w.duckdb")
    build(d / "w.duckdb", d / "r.duckdb", NOW)
    return d


def rows(path, sql, params=()):
    con = duckdb.connect(str(path), read_only=True)
    try:
        return con.execute(sql, list(params)).fetchall()
    finally:
        con.close()


def test_every_event_equals_its_condition(research):
    r = research / "r.duckdb"
    assert {t for (t,) in rows(r, "SELECT DISTINCT event_type FROM stock_events")} <= set(EVENT_TYPES)
    for event, cond in DIRECT.items():
        got = rows(r, "SELECT symbol, date FROM stock_events WHERE event_type = ? ORDER BY 1, 2", [event])
        want = rows(r, f"SELECT symbol, date FROM stock_features WHERE {BASE} AND ({cond}) ORDER BY 1, 2")
        assert got == want, event
    assert rows(r, "SELECT count(*) FROM stock_events WHERE event_type = 'PRICE_SURGE'")[0][0] > 0


def test_breakout_compares_with_the_previous_60_sessions_only(research):
    r = research / "r.duckdb"
    con = duckdb.connect(str(r), read_only=True)
    panel = con.execute("SELECT symbol, date, adj_close, is_traded FROM daily_panel ORDER BY symbol, date").df()
    feats = con.execute(f"SELECT symbol, date FROM stock_features WHERE {BASE}").df()
    got = set(map(tuple, con.execute("SELECT symbol, date FROM stock_events WHERE event_type = 'BREAKOUT'")
                  .df().to_numpy()))
    con.close()
    want = set()
    for sym, g in panel.groupby("symbol"):
        traded = g["adj_close"].where(g["is_traded"])
        prev_max = traded.shift(1).rolling(60, min_periods=1).max()
        prev_n = g["is_traded"].astype(int).shift(1).rolling(60, min_periods=1).sum()
        hit = g[(prev_n >= 50) & (g["adj_close"] > prev_max)]
        want |= {(sym, d) for d in hit["date"]}
    allowed = set(map(tuple, feats.to_numpy()))
    assert got == {x for x in want if x in allowed} and got


def test_events_are_point_in_time(research, tmp_path):
    cut = date(2023, 9, 1)
    wh = tmp_path / "w.duckdb"
    wh.write_bytes((research / "w.duckdb").read_bytes())
    with Warehouse(wh) as w:
        w.connection.execute("""UPDATE quotes_daily SET price_close = price_close * 1.3, price_high = price_high * 1.3
                                WHERE date > ? AND symbol <> 'VNINDEX'""", [cut])
    build(wh, tmp_path / "r.duckdb", NOW)
    sql = "SELECT symbol, date, event_type, event_score FROM stock_events WHERE date <= ? ORDER BY ALL"
    assert rows(research / "r.duckdb", sql, [cut]) == rows(tmp_path / "r.duckdb", sql, [cut])
    later = "SELECT symbol, date, event_type, event_score FROM stock_events WHERE date > ? ORDER BY ALL"
    assert rows(research / "r.duckdb", later, [cut]) != rows(tmp_path / "r.duckdb", later, [cut])


def test_event_study_matches_pandas_and_is_not_logged(research, tmp_path):
    with ResultsStore(tmp_path / "results.duckdb", research / "r.duckdb") as store:
        run_id = run_event_study(store, NOW, PARAMS)
        stat = store.con.execute("""SELECT n_events, mean, median, win_rate FROM event_study_stats
                                    WHERE run_id = ? AND event_type = 'PRICE_SURGE' AND horizon = 'exec_excess_10d'
                                      AND segment = 'all'""", [run_id]).fetchone()
        direct = store.con.execute(f"""SELECT f.fwd_excess_exec_10d FROM rs.stock_events e
            JOIN rs.feature_target f USING (symbol, date)
            WHERE e.event_type = 'PRICE_SURGE' AND {PARAMS.universe_sql()} AND f.period = 'research'
              AND f.fwd_excess_exec_10d IS NOT NULL""").df()["fwd_excess_exec_10d"]
        logged = store.con.execute("SELECT count(*) FROM hypothesis_log").fetchone()[0]
        kind = store.con.execute("SELECT kind, pattern_version FROM research_runs WHERE run_id = ?", [run_id]).fetchone()
        with pytest.raises(ValueError):
            run_event_study(store, NOW, PARAMS, period="validation")
    assert stat[0] == len(direct) and stat[1] == pytest.approx(direct.mean())
    assert stat[2] == pytest.approx(np.median(direct)) and stat[3] == pytest.approx((direct > 0).mean())
    assert logged == 0 and kind == ("event_study", catalog_version())


def test_daily_scan_copies_only_the_scan_dates_events(tmp_path):
    from tests.research.test_daily import NOW as DAILY_NOW, RULE, make
    from quant_research.daily import run_daily
    from quant_research.daily_report import render_daily
    rs = make(tmp_path)
    with ResultsStore(tmp_path / "results.duckdb", rs) as store:
        result = run_daily(store, DAILY_NOW, rule=RULE, n_random=2)
        got = store.con.execute("""SELECT scan_date, substr(pattern, 7), symbol, version FROM daily_events
                                   WHERE pattern LIKE 'EVENT_%' ORDER BY 1, 2, 3""").fetchall()
        want = store.con.execute(f"""SELECT e.date, e.event_type, e.symbol FROM rs.stock_events e
            JOIN rs.stock_features f USING (symbol, date)
            WHERE e.date IN (SELECT scan_date FROM daily_scans WHERE status = 'scanned') AND {RULE.sql('f.')}
            ORDER BY 1, 2, 3""").fetchall()
        report = render_daily(store, result, DAILY_NOW)
    assert [g[:3] for g in got] == [tuple(w) for w in want] and got
    assert {g[3] for g in got} == {catalog_version()}
    assert "## Catalog events today" in report
