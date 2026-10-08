"""Backtest engine on hand-built markets with exact expected outcomes."""

import numpy as np
import pytest

from quant_research.backtest.data import Market
from quant_research.backtest.engine import Strategy, random_selector, run
from quant_research.backtest.metrics import curve_metrics, drawdown, equal_weight_curve, strategy_metrics

FEE, TAX = 0.0015, 0.001


def market(open_, close, signal=None, **flags) -> Market:
    open_, close = np.asarray(open_, float), np.asarray(close, float)
    if open_.ndim == 1:
        open_, close = open_[:, None], close[:, None]
    n, k = close.shape
    sig = np.full((n, k), np.nan) if signal is None else np.asarray(signal, float).reshape(n, k)
    m = Market(np.arange(n).astype("datetime64[D]"), np.array([f"S{j}" for j in range(k)], dtype=object),
               open_, close, np.ones((n, k), bool), np.zeros((n, k), bool), np.zeros((n, k), bool),
               np.zeros((n, k), bool), np.full((n, k), np.inf), np.ones((n, k), bool), sig, np.ones(n))
    for name, value in flags.items():
        getattr(m, name)[...] = np.asarray(value).reshape(n, k)
    return m


def strat(**kw) -> Strategy:
    return Strategy(**({"hold_sessions": 3, "max_positions": 1, "renew": False, "initial_equity": 1000.0} | kw))


def test_single_round_trip_exact_pnl():
    m = market([10, 10, 11, 11, 12, 12], [10, 10, 11, 11, 12, 12], signal=[1, np.nan, np.nan, np.nan, np.nan, np.nan])
    res = run(m, strat())
    notional = 1000 / (1 + FEE)                       # cash-limited: budget 1000 must also pay the fee
    shares = notional / 10                            # bought at the open of session 1
    proceeds = shares * 12 * (1 - FEE - TAX)          # planned exit = 1 + 3 = session 4, at its close
    assert len(res.trades) == 1 and res.trades[0].exit_index == 4 and res.trades[0].exit_reason == "planned"
    assert res.equity[-1] == pytest.approx(proceeds)
    assert res.costs_paid == pytest.approx(notional * FEE + shares * 12 * (FEE + TAX))


def test_hold_below_t_plus_2_is_rejected():
    with pytest.raises(ValueError):
        Strategy(hold_sessions=1)


def test_t_plus_2_minimum_hold():
    m = market([10] * 6, [10] * 6, signal=[1] + [np.nan] * 5)
    trade = run(m, strat(hold_sessions=2)).trades[0]
    assert trade.entry_index == 1 and trade.exit_index == 3      # bought at open of 1, earliest sale close of 3


def test_renewal_uses_previous_close_signal():
    sig = [1, np.nan, np.nan, 1, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan]
    m = market([10] * 10, [10] * 10, signal=sig)
    trade = run(m, strat(renew=True)).trades[0]
    # planned exit at 4; signal at close of 3 -> renewed to 7; no signal at close of 6 -> sold at 7
    assert (trade.exit_index, trade.renewals) == (7, 1)
    no_renew = run(m, strat(renew=False)).trades
    assert no_renew[0].exit_index == 4


def test_entry_blocked_at_ceiling_open():
    m = market([10] * 5, [10] * 5, signal=[1] + [np.nan] * 4, open_limit_up=[False, True, False, False, False])
    res = run(m, strat())
    assert res.trades == [] and res.entries_blocked == 1 and res.equity[-1] == 1000


def test_exit_delayed_at_floor_and_no_trade():
    m = market([10] * 8, [10] * 8, signal=[1] + [np.nan] * 7,
               limit_down=[False, False, False, False, True, False, False, False],
               traded=[True, True, True, True, True, False, True, True])
    trade = run(m, strat()).trades[0]
    assert trade.exit_index == 6                                  # floor on 4, no trade on 5, sold on 6


def test_data_error_jump_closes_at_last_valid_price():
    m = market([10, 10, 10, 10, 10], [10, 10, 11, 500, 11], signal=[1] + [np.nan] * 4,
               price_jump=[False, False, False, True, False])
    res = run(m, strat(hold_sessions=4))
    t = res.trades[0]
    assert (t.exit_index, t.exit_price, t.exit_reason) == (3, 11.0, "data_error") and res.data_error_exits == 1
    assert res.equity.max() < 1200                                # the fake 500 never reaches equity


def test_capacity_cap_and_position_limit():
    sig = np.array([[3, 2, 1]] + [[np.nan] * 3] * 5)
    m = market(np.full((6, 3), 10.0), np.full((6, 3), 10.0), signal=sig, adv_value=np.full((6, 3), 2000.0))
    res = run(m, strat(max_positions=2))
    assert sorted(t.symbol for t in res.trades) == ["S0", "S1"]   # strongest signals first, K = 2
    assert res.capacity_capped == 2
    assert res.trades[0].entry_price * res.trades[0].shares == pytest.approx(100.0)   # 5% of 2000


def random_market(seed: int, n: int = 300, k: int = 40) -> Market:
    rng = np.random.default_rng(seed)
    close = 10 * np.cumprod(1 + rng.normal(0, 0.02, (n, k)), axis=0)
    open_ = close * (1 + rng.normal(0, 0.005, (n, k)))
    sig = np.where(rng.random((n, k)) < 0.1, rng.random((n, k)), np.nan)
    return market(open_, close, signal=sig, limit_down=rng.random((n, k)) < 0.02,
                  open_limit_up=rng.random((n, k)) < 0.02, traded=rng.random((n, k)) > 0.03)


def test_reconciliation_equity_equals_initial_plus_trade_pnl():
    m = random_market(1)
    s = Strategy(hold_sessions=5, max_positions=8, renew=True, initial_equity=1e6)
    res = run(m, s)
    net = sum(t.gross_pnl - t.costs for t in res.trades)
    assert res.equity[-1] == pytest.approx(1e6 + net, rel=1e-9)
    assert (res.cash >= -1e-6).all() and (res.n_positions <= 8).all()
    np.testing.assert_allclose(res.equity, res.cash + res.invested)


def test_no_look_ahead_perturbing_the_future():
    s = Strategy(hold_sessions=5, max_positions=8, renew=True, initial_equity=1e6)
    a = run(random_market(2), s)
    m = random_market(2)
    d = 150
    for arr in (m.open, m.close):
        arr[d + 1:] *= 1.7
    m.signal[d + 1:] = np.where(np.isnan(m.signal[d + 1:]), 0.5, np.nan)
    m.limit_down[d + 1:] = True
    b = run(m, s)
    np.testing.assert_array_equal(a.equity[:d + 1], b.equity[:d + 1])
    assert not np.array_equal(a.equity[d + 1:], b.equity[d + 1:])


def test_deterministic_and_random_control_uses_one_decile():
    m = random_market(3)
    s = Strategy(hold_sessions=5, max_positions=8, initial_equity=1e6)
    r1, r2 = run(m, s, random_selector(7)), run(m, s, random_selector(7))
    np.testing.assert_array_equal(r1.equity, r2.equity)
    assert len(random_selector(1)(m, 10)) == 4                        # 10% of 40 stocks
    assert r1.n_positions.mean() > 4                                  # control does exit and re-enter


def test_metrics_basics():
    eq = np.array([100, 110, 99, 120, 108.0])
    assert drawdown(eq) == (pytest.approx(-0.1), 1)
    m = curve_metrics(eq)
    assert m["total_return"] == pytest.approx(0.08) and m["max_drawdown"] == pytest.approx(-0.1)
    close = np.array([[10, 20], [11, 20], [11, 22.0]])
    ew = equal_weight_curve(close, np.ones((3, 2), bool))
    assert ew[-1] == pytest.approx(1.05 * 1.05)                       # (10% + 0%)/2 then (0% + 10%)/2
    res = run(random_market(4), Strategy(hold_sessions=5, max_positions=8, initial_equity=1e6))
    sm = strategy_metrics(res, 1e6)
    assert 0 <= sm["win_rate"] <= 1 and sm["turnover_per_year"] > 0 and sm["exposure"] <= 1.0001
