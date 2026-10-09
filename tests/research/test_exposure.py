"""Exposure Engine: effective bets, beta, risk shares, group weights, tilts, missing data."""

import numpy as np
import pandas as pd
import pytest

from quant_research.exposure import betas, compute, effective_bets, normalize, risk_shares

DATES = pd.bdate_range("2026-01-05", periods=120)


def _panel(seed: int = 0) -> tuple[pd.DataFrame, pd.Series]:
    rng = np.random.default_rng(seed)
    market = pd.Series(rng.normal(0, 0.01, len(DATES)), index=DATES)
    returns = pd.DataFrame({
        "AAA": 1.5 * market + rng.normal(0, 0.005, len(DATES)),
        "BBB": 0.5 * market + rng.normal(0, 0.005, len(DATES)),
        "CCC": rng.normal(0, 0.02, len(DATES)),
    }, index=DATES)
    return returns, market


def test_effective_bets_is_n_for_independent_and_one_for_identical():
    assert effective_bets(np.eye(5)) == pytest.approx(5.0)
    assert effective_bets(np.ones((5, 5))) == pytest.approx(1.0)
    two_blocks = np.kron(np.eye(2), np.ones((3, 3)))            # two groups of three identical stocks
    assert effective_bets(two_blocks) == pytest.approx(2.0)


def test_beta_matches_polyfit_on_pairwise_complete_rows():
    returns, market = _panel()
    returns.iloc[:7, 0] = np.nan                                 # gaps are dropped, not filled
    b = betas(returns, market, min_obs=90)
    for s in returns:
        ok = returns[s].notna()
        slope = np.polyfit(market[ok], returns[s][ok], 1)[0]
        assert b[s] == pytest.approx(slope, rel=1e-9)
    assert betas(returns, market, min_obs=200).empty               # not enough observations: no beta


def test_risk_shares_sum_to_one_and_portfolio_figures_are_consistent():
    returns, market = _panel()
    ex = compute(returns, market, {"AAA": 2, "BBB": 1, "CCC": 1})
    assert ex.per_stock["risk_share"].sum() == pytest.approx(1.0)
    assert ex.per_stock["weight"].sum() == pytest.approx(1.0)
    w = ex.per_stock.set_index("symbol")["weight"]
    assert w["AAA"] == pytest.approx(0.5)
    port = (returns[w.index] * w).sum(axis=1)
    assert ex.portfolio["vol_ann"] == pytest.approx(port.std(ddof=1) * np.sqrt(250), rel=1e-9)
    assert ex.portfolio["beta"] == pytest.approx(np.polyfit(market, port, 1)[0], rel=1e-9)
    assert ex.portfolio["effective_n_weights"] == pytest.approx(1 / (0.5 ** 2 + 2 * 0.25 ** 2))
    assert 1.0 < ex.portfolio["effective_bets"] < 3.0
    assert ex.portfolio["n"] == 3 and ex.missing == []


def test_group_weights_sum_to_one_with_unknown_labels():
    returns, market = _panel()
    labels = {"industry": {"AAA": "Banks", "BBB": "Banks"}}       # CCC has no label
    ex = compute(returns, market, {"AAA": 1, "BBB": 1, "CCC": 2}, labels)
    g = ex.groups["industry"].set_index("industry")["weight"]
    assert g.sum() == pytest.approx(1.0)
    assert g["Banks"] == pytest.approx(0.5) and g["unknown"] == pytest.approx(0.5)


def test_missing_symbols_are_reported_and_left_out():
    returns, market = _panel()
    returns.iloc[:60, 2] = np.nan                                # CCC: half the window only
    ex = compute(returns, market, {"AAA": 1, "BBB": 1, "CCC": 1, "ZZZ": 1})
    assert ex.missing == ["CCC", "ZZZ"]
    assert set(ex.per_stock["symbol"]) == {"AAA", "BBB"}
    assert ex.per_stock["weight"].sum() == pytest.approx(1.0)    # re-normalized over what is left
    empty = compute(returns, market, {"ZZZ": 1})
    assert empty.portfolio["n"] == 0 and empty.portfolio["beta"] is None and empty.missing == ["ZZZ"]


def test_factor_tilts_are_weighted_over_covered_symbols():
    returns, market = _panel()
    z = pd.DataFrame({"size": [1.0, -1.0, np.nan], "momentum": [np.nan, np.nan, np.nan]},
                     index=["AAA", "BBB", "CCC"])
    ex = compute(returns, market, {"AAA": 3, "BBB": 1, "CCC": 4}, factor_z=z)
    t = ex.tilts.set_index("factor")
    assert t.loc["size", "weighted_z"] == pytest.approx((3 * 1 - 1 * 1) / 4)
    assert t.loc["size", "coverage"] == pytest.approx(0.5)
    assert t.loc["momentum", "weighted_z"] is None or np.isnan(t.loc["momentum", "weighted_z"])
    assert t.loc["momentum", "coverage"] == 0.0


def test_normalize_drops_zero_and_negative_weights():
    w = normalize({"A": 2, "B": 0, "C": -1, "D": 2})
    assert list(w.index) == ["A", "D"] and w.sum() == pytest.approx(1.0)
