"""Phase 4b group analysis: industry indexes, planted group lead-lag (true vs stale), momentum, guards."""

from datetime import UTC, date, datetime

import duckdb
import numpy as np
import pandas as pd
import pytest

from quant_research.build import build
from quant_research.cross.build import build_cross
from quant_research.cross.hypotheses import attach, run_all
from quant_research.cross.params import CrossParams
from quant_research.results import ResearchParams, ResultsStore
from tests.research.synthetic_groups import build_group_warehouse

NOW = datetime(2026, 10, 7, 20, 0, tzinfo=UTC)
PARAMS = CrossParams(universe_size=60, min_adv_value=0, windows=(60, 120), cluster_window=120, coint_window=120,
                     n_large=6, start_year=2020)
RESEARCH = ResearchParams(min_stocks_per_date=5)
GROUP_TESTS = ("g_leadlag", "g_momentum", "g_reversal", "g_laggard")


@pytest.fixture(scope="module")
def planted(tmp_path_factory):
    d = tmp_path_factory.mktemp("groups")
    build_group_warehouse(d / "w.duckdb")
    build(d / "w.duckdb", d / "r.duckdb", NOW)
    build_cross(d / "r.duckdb", d / "c.duckdb", NOW, PARAMS, warehouse_path=d / "w.duckdb")
    return d


def q(path, sql, params=()):
    con = duckdb.connect(str(path), read_only=True)
    try:
        return con.execute(sql, list(params)).fetchall()
    finally:
        con.close()


def test_index_is_the_mean_of_last_month_members_and_small_groups_have_none(planted):
    c = planted / "c.duckdb"
    day = q(c, "SELECT min(date) FROM group_returns_daily WHERE level = 'l2' AND group_code = '3020' "
               "AND ew_cc IS NOT NULL AND date > DATE '2020-06-30'")[0][0]
    got = q(c, "SELECT ew_cc FROM group_returns_daily WHERE level = 'l2' AND group_code = '3020' AND date = ?", [day])
    want = q(c, """SELECT avg(r.ex_cc) FROM returns_daily r JOIN group_members_monthly g
                   ON g.symbol = r.symbol AND g.level = 'l2' AND g.group_code = '3020'
                   AND g.month_end = (SELECT max(month_end) FROM month_ends WHERE month_end < ?)
                   WHERE r.date = ?""", [day, day])
    assert got[0][0] == pytest.approx(want[0][0])
    assert q(c, "SELECT count(ew_cc) FROM group_returns_daily WHERE group_code = '1510'")[0][0] == 0
    assert q(c, "SELECT name FROM group_names WHERE level = 'l2' AND group_code = '3020'")[0][0] == "ICB 3020"


def test_true_follower_shows_on_open_to_close_and_stale_one_does_not(planted):
    rows = q(planted / "c.duckdb", """SELECT follow, avg(corr_form), avg(corr_form_oc) FROM group_leadlag_pairs
                                      WHERE level = 'l2' AND lag = 1 AND lead = '5020' AND follow IN ('3020', '4010')
                                      GROUP BY 1""")
    by = {f: (cc, oc) for f, cc, oc in rows}
    assert by["3020"][0] > 0.3 and by["3020"][1] > 0.3                # B: real, tradable after the open
    assert by["4010"][0] > 0.3 and abs(by["4010"][1]) < 0.1          # S: only in the opening gap


def test_group_tests_detect_planted_effects_and_are_not_run_twice(planted, tmp_path):
    with ResultsStore(tmp_path / "results.duckdb", planted / "r.duckdb") as store:
        attach(store, planted / "c.duckdb")
        runs = run_all(store, "research", RESEARCH, NOW, PARAMS, tests=GROUP_TESTS)
        stats = {(t, h): e for t, h, e in store.con.execute(
            "SELECT test, horizon, estimate FROM cross_stats").fetchall()}
        logged = store.con.execute("SELECT count(*) FROM hypothesis_log").fetchone()[0]
        skipped = []
        again = run_all(store, "research", RESEARCH, NOW, PARAMS, tests=GROUP_TESTS, log=skipped.append)
    assert len(runs) == 4 and logged == 8 + 2 + 1 + 3
    assert stats[("group_leadlag_persist_oc", "lag1")] > 0.05      # A -> B survives on open-to-close
    assert stats[("group_momentum_21d", "exec_excess_20d")] > 0    # drifting industry D
    assert again == [] and len(skipped) == 4


def _rounded(rows):
    return [tuple(round(v, 12) if isinstance(v, float) else v for v in r) for r in rows]


def test_no_look_ahead_in_group_tables(planted, tmp_path):
    cut = date(2021, 6, 30)
    rs = tmp_path / "r.duckdb"
    rs.write_bytes((planted / "r.duckdb").read_bytes())
    con = duckdb.connect(str(rs))
    con.execute("UPDATE daily_panel SET adj_close = adj_close * (1 + 0.05 * sin(epoch(date))) WHERE date > ?", [cut])
    con.execute("UPDATE stock_features SET adv_value_20 = adv_value_20 * (1 + 0.5 * cos(epoch(date))) WHERE date > ?",
                [cut])
    con.close()
    build_cross(rs, tmp_path / "c.duckdb", NOW, PARAMS)
    checks = {
        "group_members_monthly": "SELECT * FROM group_members_monthly WHERE month_end <= ? ORDER BY ALL",
        "group_returns_daily": "SELECT * FROM group_returns_daily WHERE date <= ? ORDER BY ALL",
        "group_features": "SELECT * FROM group_features WHERE date <= ? ORDER BY ALL",
        "group_corr_snapshots": "SELECT * FROM group_corr_snapshots WHERE month_end <= ? ORDER BY ALL",
    }
    for name, sql in checks.items():                                  # parallel float sums: compare to 1e-12
        assert _rounded(q(planted / "c.duckdb", sql, [cut])) == _rounded(q(tmp_path / "c.duckdb", sql, [cut])), name
    later = "SELECT * FROM group_returns_daily WHERE date > ? ORDER BY ALL"
    assert q(planted / "c.duckdb", later, [cut]) != q(tmp_path / "c.duckdb", later, [cut])


def test_tercile_spread_matches_a_direct_computation():
    from quant_research.cross.group_tests import _tercile_spread
    dates = np.arange(np.datetime64("2021-01-01"), np.datetime64("2021-03-01")).astype("datetime64[D]")
    codes = [f"G{i}" for i in range(6)]
    ret = np.tile(np.arange(6, dtype=float) / 100, (len(dates), 1))   # G5 always strongest
    day = dates[-1]
    outcomes = {day: {c: float(i) for i, c in enumerate(codes)}}
    spread, _ = _tercile_spread(dates, codes, ret, outcomes, 21, "top")
    assert spread.tolist() == [pytest.approx(np.mean([4.0, 5.0]) - np.mean(range(6)))]
    spread, _ = _tercile_spread(dates, codes, ret, outcomes, 21, "bottom")
    assert spread.tolist() == [pytest.approx(np.mean([0.0, 1.0]) - np.mean(range(6)))]
