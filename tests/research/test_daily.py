"""Daily scanner, completeness gate, catch-up, paper portfolio and report."""

from datetime import UTC, date, datetime

import duckdb
import numpy as np
import pytest

from fireant_crawler.store.warehouse import Warehouse
from quant_research.backtest.data import UniverseRule, load_market
from quant_research.backtest.engine import run, signal_selector
from quant_research.build import build
from quant_research.daily import FORWARD_START, FROZEN_STRATEGY, run_daily, run_paper
from quant_research.daily_report import render_daily, write_reports
from quant_research.patterns import Pattern
from quant_research.results import ResultsStore
from tests.research.synthetic import build_synthetic_warehouse, calendar

NOW = datetime(2027, 3, 1, 19, 0, tzinfo=UTC)   # after the synthetic calendar: every session is final
RULE = UniverseRule(min_adv_value=0, min_session_index=0, min_stocks_per_date=2, signal_decile=3)
START = date(2026, 1, 5)
FORWARD_DAYS = [d for d in calendar(START) if d >= FORWARD_START]


def make(tmp_path, start=START, drop_last_for=None):
    wh, rs = tmp_path / "w.duckdb", tmp_path / "r.duckdb"
    for p in (wh, rs):
        p.unlink(missing_ok=True)
    build_synthetic_warehouse(wh, start=start)
    if drop_last_for:
        with Warehouse(wh) as w:
            last = w.connection.execute("SELECT max(date) FROM quotes_daily").fetchone()[0]
            w.connection.execute("DELETE FROM quotes_daily WHERE date = ? AND symbol = ?", [last, drop_last_for])
    build(wh, rs, NOW)
    return rs


def test_catch_up_scans_every_forward_session_once(tmp_path):
    rs = make(tmp_path)
    with ResultsStore(tmp_path / "results.duckdb", rs) as store:
        first = run_daily(store, NOW, rule=RULE, n_random=2)
        second = run_daily(store, NOW, rule=RULE, n_random=2)
        n_scans = store.con.execute("SELECT count(*) FROM daily_scans WHERE is_forward").fetchone()[0]
    assert first.scanned == FORWARD_DAYS and first.incomplete == []
    assert second.scanned == [] and n_scans == len(FORWARD_DAYS)


def test_events_equal_a_direct_query_on_features_only(tmp_path):
    rs = make(tmp_path)
    lib = {"down": Pattern("down", "return_1d < 0", "test: fires on most sessions")}
    with ResultsStore(tmp_path / "results.duckdb", rs) as store:
        run_daily(store, NOW, rule=RULE, n_random=2, library=lib)
        got = store.con.execute("SELECT scan_date, symbol FROM daily_events WHERE pattern = 'down' ORDER BY 1, 2").fetchall()
        want = store.con.execute(f"""SELECT date, symbol FROM rs.stock_features
            WHERE date >= ? AND {RULE.sql()} AND return_1d < 0 ORDER BY 1, 2""", [FORWARD_START]).fetchall()
    assert got == want and len(got) > 20


def test_completeness_gate_skips_a_partial_session_until_complete(tmp_path):
    rs = make(tmp_path, drop_last_for="STK")                         # 4 of 5 raw rows on the last day
    with ResultsStore(tmp_path / "results.duckdb", rs) as store:
        r = run_daily(store, NOW, rule=RULE, n_random=2)
    assert r.incomplete and r.incomplete[0][0] == FORWARD_DAYS[-1] and r.incomplete[0][1] < 0.95
    assert FORWARD_DAYS[-1] not in r.scanned

    rs = make(tmp_path)                                               # the next update completes the day
    with ResultsStore(tmp_path / "results.duckdb", rs) as store:
        r = run_daily(store, NOW, rule=RULE, n_random=2)
        status = store.con.execute("SELECT status FROM daily_scans WHERE scan_date = ?", [FORWARD_DAYS[-1]]).fetchone()[0]
    assert r.scanned == [FORWARD_DAYS[-1]] and status == "scanned"


def test_delisting_and_no_trade_days_do_not_trip_the_gate(tmp_path):
    rs = make(tmp_path)                                               # DEL stops trading mid-sample
    with ResultsStore(tmp_path / "results.duckdb", rs) as store:
        r = run_daily(store, NOW, rule=RULE, n_random=2)
    assert r.incomplete == []


def test_paper_portfolio_is_a_deterministic_engine_run_on_the_forward_window(tmp_path):
    rs = make(tmp_path)
    with ResultsStore(tmp_path / "results.duckdb", rs) as store:
        run_daily(store, NOW, rule=RULE, n_random=2)
        eq = [r[0] for r in store.con.execute("SELECT equity FROM paper_daily ORDER BY date").fetchall()]
        run_paper(store, FORWARD_DAYS[-1], rule=RULE, n_random=2)
        eq2 = [r[0] for r in store.con.execute("SELECT equity FROM paper_daily ORDER BY date").fetchall()]
        direct = run(load_market(store.con, FORWARD_START, date(2099, 12, 31), RULE), FROZEN_STRATEGY, signal_selector)
    assert len(eq) == len(FORWARD_DAYS) and eq == eq2
    np.testing.assert_allclose(eq, direct.equity)


def test_report_renders_before_and_after_the_forward_start(tmp_path):
    rs = make(tmp_path)
    with ResultsStore(tmp_path / "results.duckdb", rs) as store:
        report = render_daily(store, run_daily(store, NOW, rule=RULE, n_random=2), NOW)
    assert "## Avoid list" in report and "## Forward scoreboard" in report and "Strategy:" in report

    old = tmp_path / "old"
    old.mkdir()
    rs_old = make(old, start=date(2023, 1, 2))                       # data ends before FORWARD_START
    with ResultsStore(old / "results.duckdb", rs_old) as store:
        result = run_daily(store, NOW, rule=RULE, n_random=2)
        report = render_daily(store, result, NOW)
        flags = store.con.execute("SELECT DISTINCT is_forward FROM daily_scans").fetchall()
    assert "not started yet" in report and "Not started" in report and flags == [(False,)]


def test_report_shows_recorded_validation_decisions_not_recomputed_ones(tmp_path):
    rs = make(tmp_path)
    with ResultsStore(tmp_path / "results.duckdb", rs) as store:
        report = render_daily(store, run_daily(store, NOW, rule=RULE, n_random=2), NOW)
    row = next(line for line in report.splitlines() if line.startswith("| order_imbalance_d10 |"))
    assert "**FAIL**" in row and "after costs" in row
    assert "**PASS**" in next(line for line in report.splitlines() if line.startswith("| drop3_volume2_sellers |"))
    assert "not validated" in next(line for line in report.splitlines() if line.startswith("| drop3 |"))


def test_a_session_in_progress_is_neither_scanned_nor_traded(tmp_path):
    """Even if the warehouse holds a row for today's session, quant daily waits until it is final."""
    from zoneinfo import ZoneInfo
    vn = ZoneInfo("Asia/Ho_Chi_Minh")
    rs = make(tmp_path)
    monday = next(d for d in FORWARD_DAYS[3:] if d.weekday() == 0)
    before = [d for d in FORWARD_DAYS if d < monday]
    with ResultsStore(tmp_path / "results.duckdb", rs) as store:
        morning = run_daily(store, datetime(monday.year, monday.month, monday.day, 10, 0, tzinfo=vn),
                            rule=RULE, n_random=2)
        last_paper = store.con.execute("SELECT max(date) FROM paper_daily").fetchone()[0]
        with pytest.raises(ValueError, match="not final"):
            run_daily(store, datetime(monday.year, monday.month, monday.day, 10, 0, tzinfo=vn),
                      rescan=monday, rule=RULE, n_random=2)
        evening = run_daily(store, datetime(monday.year, monday.month, monday.day, 18, 30, tzinfo=vn),
                            rule=RULE, n_random=2)
    assert morning.scanned == before and morning.latest_date == before[-1] and last_paper == before[-1]
    assert evening.scanned == [monday] and evening.latest_date == monday


def test_catch_up_run_writes_one_report_per_scanned_session(tmp_path):
    from zoneinfo import ZoneInfo
    vn = ZoneInfo("Asia/Ho_Chi_Minh")
    rs = make(tmp_path)
    missed = FORWARD_DAYS[:6]                                        # a week nobody ran the pipeline
    late = datetime(missed[-1].year, missed[-1].month, missed[-1].day, 20, 0, tzinfo=vn)
    with ResultsStore(tmp_path / "results.duckdb", rs) as store:
        result = run_daily(store, late, rule=RULE, n_random=2)
        paths = write_reports(store, result, late, tmp_path / "reports")
        first = paths[0].read_text()
        on_time = render_daily(store, result, late, day=missed[0])
    assert result.scanned == missed and [p.stem for p in paths] == [str(d) for d in missed]
    assert "Catch-up report" in first and "## Avoid list" in first and "## Today's events" in first
    assert "## Forward scoreboard" not in first and "| symbol | entry |" not in first
    latest = paths[-1].read_text()
    assert "Catch-up report" not in latest and "## Forward scoreboard" in latest
    assert first == on_time
