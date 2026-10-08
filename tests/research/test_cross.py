"""Phase 4 cross-stock: matrix maths vs pandas, planted relations, look-ahead perturbation, tests."""

from datetime import UTC, date, datetime

import duckdb
import numpy as np
import pandas as pd
import pytest

from quant_research.build import build, file_hash
from quant_research.cross.build import build_cross
from quant_research.cross.describe import granger_p
from quant_research.cross.hypotheses import attach, hac_ols, run_all
from quant_research.cross.matrix import adjusted_rand_index, clusters, lag_corr, pairwise_corr
from quant_research.cross.params import CrossParams
from quant_research.results import ResearchParams, ResultsStore
from tests.research.synthetic_cross import PLANTED, build_cross_warehouse

NOW = datetime(2026, 10, 5, 20, 0, tzinfo=UTC)
PARAMS = CrossParams(universe_size=30, min_adv_value=0, windows=(60, 120), cluster_window=120, coint_window=120,
                     n_large=6, start_year=2020)
RESEARCH = ResearchParams(min_stocks_per_date=5)


# ---------- matrix maths ----------

def test_pairwise_corr_matches_pandas_with_missing_values():
    rng = np.random.default_rng(1)
    x = rng.normal(size=(80, 6))
    x[rng.random(x.shape) < 0.2] = np.nan
    got, n = pairwise_corr(x, min_obs=10)
    want = pd.DataFrame(x).corr(min_periods=10).to_numpy()
    np.testing.assert_allclose(got, want, atol=1e-10)
    assert n[0, 1] == int((np.isfinite(x[:, 0]) & np.isfinite(x[:, 1])).sum())


def test_lag_corr_matches_shifted_pandas():
    rng = np.random.default_rng(2)
    x = rng.normal(size=(100, 4))
    x[rng.random(x.shape) < 0.1] = np.nan
    got, _ = lag_corr(x, x, 2, min_obs=10)
    df = pd.DataFrame(x)
    assert got[0, 3] == pytest.approx(df[0].iloc[:-2].reset_index(drop=True)
                                      .corr(df[3].iloc[2:].reset_index(drop=True)), abs=1e-10)


def test_adjusted_rand_index_and_clusters():
    a = np.array([1, 1, 2, 2, 3, 3])
    assert adjusted_rand_index(a, np.array([5, 5, 7, 7, 9, 9])) == pytest.approx(1.0)
    assert adjusted_rand_index(a, np.array([1, 2, 3, 1, 2, 3])) < 0.1
    corr = np.full((6, 6), 0.0)
    for g in ((0, 1, 2), (3, 4, 5)):
        for i in g:
            for j in g:
                corr[i, j] = 0.9
    labels = clusters(corr, 2)
    assert len(set(labels[:3])) == 1 and len(set(labels[3:])) == 1 and labels[0] != labels[3]


# ---------- build on planted data ----------

@pytest.fixture(scope="module")
def planted(tmp_path_factory):
    d = tmp_path_factory.mktemp("cross")
    build_cross_warehouse(d / "w.duckdb")
    build(d / "w.duckdb", d / "r.duckdb", NOW)
    before = file_hash(d / "r.duckdb")
    build_cross(d / "r.duckdb", d / "c.duckdb", NOW, PARAMS)
    assert file_hash(d / "r.duckdb") == before                      # research.duckdb never written
    return d


def q(path, sql, params=()):
    con = duckdb.connect(str(path), read_only=True)
    try:
        return con.execute(sql, list(params)).fetchall()
    finally:
        con.close()


def test_planted_lead_lag_is_found_and_persists(planted):
    rows = q(planted / "c.duckdb", """
        SELECT sl.symbol, sf.symbol, form_year, corr_form, corr_test_cc FROM leadlag_pairs p
        JOIN symbols sl ON sl.id = p.lead JOIN symbols sf ON sf.id = p.follow WHERE lag = 1""")
    by = {(a, b, y): (cf, ct) for a, b, y, cf, ct in rows}
    for lead, follow in PLANTED:
        cf, ct = by[(lead, follow, 2020)]
        assert cf > 0.4 and ct > 0.4                               # strong in formation and in the next year
        assert abs(by[(follow, lead, 2020)][0]) < 0.2              # the reverse direction is not
    noise = [cf for (a, b, _y), (cf, _ct) in by.items() if a.startswith("N") and b.startswith("N")]
    assert abs(np.mean(noise)) < 0.05


def test_stale_stock_has_no_returns_and_no_pairs(planted):
    assert q(planted / "c.duckdb", "SELECT count(ex_cc) FROM returns_daily WHERE symbol = 'ILLIQ'")[0][0] == 0
    n = q(planted / "c.duckdb", """SELECT count(*) FROM leadlag_pairs p JOIN symbols s ON s.id IN (p.lead, p.follow)
                                   WHERE s.symbol = 'ILLIQ'""")[0][0]
    assert n == 0


def test_cointegrated_pair_is_found_and_trades(planted):
    rows = q(planted / "c.duckdb", """SELECT sa.symbol, sb.symbol, min(p), count(*) FROM coint_pairs c
                                      JOIN symbols sa ON sa.id = c.a JOIN symbols sb ON sb.id = c.b GROUP BY 1, 2""")
    pairs = {(a, b): (p, n) for a, b, p, n in rows}
    assert pairs[("CA", "CB")][0] < 0.01
    events = q(planted / "c.duckdb", """SELECT count(*), count(DISTINCT e.symbol) FROM coint_events e
                                        JOIN symbols sa ON sa.id = e.a JOIN symbols sb ON sb.id = e.b
                                        WHERE sa.symbol = 'CA' AND sb.symbol = 'CB'""")[0]
    assert events[0] > 0 and events[1] == 2                         # both legs get to be the cheap one
    noise = [p for (a, b), (p, _n) in pairs.items() if a.startswith("N") and b.startswith("N")]
    rate = q(planted / "c.duckdb", """SELECT avg((p < 0.05)::INT) FROM coint_pairs c
                                      JOIN symbols sa ON sa.id = c.a JOIN symbols sb ON sb.id = c.b
                                      WHERE sa.symbol LIKE 'N%' AND sb.symbol LIKE 'N%'""")[0][0]
    assert noise and rate < 0.15                                    # false positives near the nominal 5%


def test_leaders_are_the_most_liquid_and_features_are_their_average(planted):
    leaders = q(planted / "c.duckdb", """SELECT DISTINCT symbol FROM leaders_monthly
                                         WHERE industry_l2_code = '5020' ORDER BY 1""")
    assert [r[0] for r in leaders] == ["LX1", "LX2", "LX3"]
    got, want = q(planted / "c.duckdb", """
        WITH d AS (SELECT min(date) AS day FROM cross_features WHERE leader_excess_1d IS NOT NULL
                   AND industry_l2_code = '5020')
        SELECT any_value(c.leader_excess_1d), avg(r.ex_cc) FROM cross_features c, d
        JOIN returns_daily r ON r.date = d.day AND r.symbol IN ('LX1', 'LX2', 'LX3')
        WHERE c.date = d.day AND c.symbol = 'FX1'""")[0]
    assert got == pytest.approx(want)


def test_no_look_ahead_changing_later_data_leaves_earlier_outputs(planted, tmp_path):
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
        "corr_snapshots": "SELECT month_end, win, a, b, corr FROM corr_snapshots WHERE month_end <= ? ORDER BY 1, 2, 3, 4",
        "universe_monthly": "SELECT * FROM universe_monthly WHERE month_end <= ? ORDER BY 1, 2",
        "leaders_monthly": "SELECT * FROM leaders_monthly WHERE month_end <= ? ORDER BY 1, 2",
        "cross_features": "SELECT * FROM cross_features WHERE date <= ? ORDER BY 1, 2",
        "coint_pairs": "SELECT * FROM coint_pairs WHERE formation_date <= ? ORDER BY 1, 2, 3",
    }
    for name, sql in checks.items():
        assert q(planted / "c.duckdb", sql, [cut]) == q(tmp_path / "c.duckdb", sql, [cut]), name
    form = "SELECT form_year, lag, lead, follow, corr_form FROM leadlag_pairs WHERE form_year <= 2020 ORDER BY 1, 2, 3, 4"
    assert q(planted / "c.duckdb", form) == q(tmp_path / "c.duckdb", form)
    later = "SELECT month_end, win, a, b, corr FROM corr_snapshots WHERE month_end > ? ORDER BY 1, 2, 3, 4"
    assert q(planted / "c.duckdb", later, [cut]) != q(tmp_path / "c.duckdb", later, [cut])   # the change bites


# ---------- hypothesis tests ----------

def test_cross_tests_run_log_and_detect_the_planted_lead_lag(planted, tmp_path):
    with ResultsStore(tmp_path / "results.duckdb", planted / "r.duckdb") as store:
        attach(store, planted / "c.duckdb")
        runs = run_all(store, "research", RESEARCH, NOW, PARAMS, tests=("leadlag", "h1", "h2", "h3", "coint"))
        persist = dict(store.con.execute("""SELECT horizon, estimate FROM cross_stats
                                            WHERE test = 'leadlag_persist_cc'""").fetchall())
        logged = store.con.execute("SELECT count(*) FROM hypothesis_log").fetchone()[0]
        kinds = store.con.execute("SELECT DISTINCT kind FROM research_runs ORDER BY 1").fetchall()
        lifts = store.con.execute("SELECT count(*) FROM pattern_lifts").fetchone()[0]
    assert len(runs) == 5 and kinds == [("cross",), ("pattern",)]
    assert persist["lag1"] > 0.02 and abs(persist["lag5"]) < persist["lag1"]
    assert logged == 8 + 3 + 3 + 3 + 3 and lifts == 6


def test_cross_tests_refuse_holdout_without_final(planted, tmp_path):
    from quant_research.results import HoldoutLockedError
    with ResultsStore(tmp_path / "results.duckdb", planted / "r.duckdb") as store:
        attach(store, planted / "c.duckdb")
        with pytest.raises(HoldoutLockedError):
            run_all(store, "holdout", RESEARCH, NOW, PARAMS)


def test_hac_ols_matches_statsmodels():
    import statsmodels.api as sm
    rng = np.random.default_rng(3)
    x = rng.normal(size=(400, 2))
    y = 0.3 * x[:, 0] - 0.1 * x[:, 1] + rng.normal(size=400)
    beta, se = hac_ols(y, x, 4)
    ref = sm.OLS(y, sm.add_constant(x)).fit(cov_type="HAC", cov_kwds={"maxlags": 4, "use_correction": False})
    np.testing.assert_allclose(beta, ref.params, rtol=1e-10)
    np.testing.assert_allclose(se, ref.bse, rtol=1e-8)


def test_granger_p_matches_statsmodels_on_complete_data():
    from statsmodels.tsa.stattools import grangercausalitytests
    rng = np.random.default_rng(4)
    x = rng.normal(size=600)
    y = np.r_[0.0, 0.3 * x[:-1]] + rng.normal(size=600)
    ref = grangercausalitytests(np.column_stack([y, x]), maxlag=2)
    for k in (1, 2):
        assert granger_p(y, x, k) == pytest.approx(ref[k][0]["ssr_ftest"][1], rel=1e-8)


def test_pairs_have_a_canonical_orientation(planted):
    for table in ("corr_snapshots", "coint_pairs"):
        assert q(planted / "c.duckdb", f"SELECT count(*) FROM {table} WHERE a >= b")[0][0] == 0, table
