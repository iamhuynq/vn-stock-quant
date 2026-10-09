"""Interaction Engine: daily IC, contrast test, run rules, logging, halves, candidate rule."""

from datetime import UTC, date, datetime

import numpy as np
import pandas as pd
import pytest
import scipy.stats as sps

from quant_research import interactions as ix
from quant_research.build import build
from quant_research.cross.hypotheses import hac_ols
from quant_research.factors import FACTORS, FactorParams
from quant_research.interaction_report import is_candidate, render
from quant_research.interaction_report import tests_with_q as ix_tests
from quant_research.regimes import RegimeParams
from quant_research.results import ResearchParams, ResultsStore
from tests.research.synthetic import build_synthetic_warehouse

NOW = datetime(2026, 10, 9, 20, 0, tzinfo=UTC)
PARAMS = ResearchParams(min_adv_value=0, min_session_index=0, min_stocks_per_date=1)


@pytest.fixture(scope="module")
def research(tmp_path_factory):
    d = tmp_path_factory.mktemp("ix")
    build_synthetic_warehouse(d / "w.duckdb")
    build(d / "w.duckdb", d / "r.duckdb", NOW, FactorParams(min_adv_value=0, min_session_index=0, min_stocks=1),
          RegimeParams(window=100, min_obs=50, breadth_min_adv=0))
    return d / "r.duckdb"


@pytest.fixture
def small(monkeypatch):
    monkeypatch.setattr(ix, "MIN_STOCKS", 3)
    monkeypatch.setattr(ix, "MIN_DATES", 5)
    monkeypatch.setattr(ix, "HALF_SPLIT", date(2023, 7, 1))


def test_daily_ic_equals_scipy_spearman(research, tmp_path, small):
    with ResultsStore(tmp_path / "results.duckdb", research) as store:
        got = ix.daily_ic(store, "research", PARAMS)
        rows = store.con.execute(f"""
            SELECT f.date, f.factor, f.value, t.fwd_excess_exec_10d AS y FROM rs.stock_factors f
            JOIN rs.feature_target t USING (symbol, date)
            WHERE {PARAMS.universe_sql()} AND t.period = 'research' AND t.fwd_excess_exec_10d IS NOT NULL""").df()
    assert len(got) > 50
    for (d, factor), g in rows.groupby(["date", "factor"]):
        if len(g) < 3:
            continue
        want = sps.spearmanr(g["value"], g["y"]).statistic
        have = got[(got["date"] == d) & (got["factor"] == factor)]["ic"].iloc[0]
        assert have == pytest.approx(want, nan_ok=True), (d, factor)


def test_contrast_equals_the_mean_difference_and_hac_ols(monkeypatch):
    monkeypatch.setattr(ix, "MIN_DATES", 5)
    rng = np.random.default_rng(3)
    idx = pd.date_range("2020-01-01", periods=80)
    ic = pd.Series(rng.normal(0.02, 0.1, 80), index=idx)
    state = pd.Series(np.where(np.arange(80) % 3 == 0, "A", np.where(np.arange(80) % 3 == 1, "B", "C")), index=idx)
    res = ix.contrast(ic, state == "A", state == "B")
    keep = state.isin(["A", "B"])
    beta, ses = hac_ols(ic[keep].to_numpy(), (state[keep] == "A").to_numpy(float), 9)
    assert res["diff"] == pytest.approx(ic[state == "A"].mean() - ic[state == "B"].mean())
    assert res["se"] == pytest.approx(ses[1]) and res["t"] == pytest.approx(beta[1] / ses[1])
    assert (res["n_a"], res["n_b"]) == (27, 27)
    monkeypatch.setattr(ix, "MIN_DATES", 30)
    assert ix.contrast(ic, state == "A", state == "B")["p"] is None                  # too few dates: no test


def test_scan_logs_54_tests_with_halves_and_refuses_other_periods(research, tmp_path, small):
    with ResultsStore(tmp_path / "results.duckdb", research) as store:
        for period in ("validation", "holdout", "forward"):
            with pytest.raises(ix.InteractionRefused, match="research period only"):
                ix.run_scan(store, period, NOW, PARAMS)
        run_id = ix.run_scan(store, "research", NOW, PARAMS)
        logged = store.con.execute("SELECT label FROM hypothesis_log WHERE run_id = ?", [run_id]).fetchall()
        tests = ix_tests(store, run_id)
        with pytest.raises(ix.InteractionRefused, match="invalidate"):
            ix.run_scan(store, "research", NOW.replace(hour=21), PARAMS)
        store.invalidate(run_id, "test: re-run")
        again = ix.run_scan(store, "research", NOW.replace(hour=22), PARAMS)
        ic = ix.daily_ic(store, "research", PARAMS)
        regimes = store.con.execute("SELECT date, volatility FROM rs.market_regimes").df().set_index("date")
        text = render(store, again)
    assert len(logged) == len(FACTORS) * len(ix.CONTRASTS) == 54
    assert {label for (label,) in logged} == {f"ix_{f}_{d}" for f in FACTORS for d in ix.CONTRASTS}
    assert tests["p"].notna().any()
    s = ic[ic["factor"] == "volatility"].set_index("date")["ic"]
    s = s[np.isfinite(s)]
    lab = regimes.reindex(s.index)["volatility"]
    first = s.index < pd.Timestamp(date(2023, 7, 1))
    want = s[first & (lab == "high")].mean() - s[first & (lab == "low")].mean()
    row = tests[(tests["factor"] == "volatility") & (tests["dimension"] == "volatility")].iloc[0]
    assert row["diff_first_half"] == pytest.approx(want, nan_ok=True)
    assert "Candidates:" in text and "not economic value" in text


@pytest.mark.parametrize("row, want", [
    ({"q_value": 0.01, "diff": 0.03, "diff_first_half": 0.02, "diff_second_half": 0.04}, True),
    ({"q_value": 0.01, "diff": -0.03, "diff_first_half": -0.02, "diff_second_half": -0.01}, True),
    ({"q_value": 0.06, "diff": 0.03, "diff_first_half": 0.02, "diff_second_half": 0.04}, False),
    ({"q_value": 0.01, "diff": 0.015, "diff_first_half": 0.02, "diff_second_half": 0.01}, False),
    ({"q_value": 0.01, "diff": 0.03, "diff_first_half": -0.01, "diff_second_half": 0.06}, False),
    ({"q_value": None, "diff": 0.03, "diff_first_half": 0.02, "diff_second_half": 0.04}, False),
])
def test_candidate_rule(row, want):
    assert is_candidate(pd.Series(row, dtype=object)) is want
