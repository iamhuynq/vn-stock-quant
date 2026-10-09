"""Invariants of both engines on many random markets with edge cases (no trades, price limits, missing ADV,
data-error jumps): no negative cash or shares, no sale beyond the eligible lots, orders within their caps,
costs that add up, and marks taken from traded sessions only."""

import numpy as np
import pytest

from quant_research.backtest.costs import CostModel
from quant_research.backtest.engine import Strategy, random_selector, run
from quant_research.portfolio.construction import Construction
from quant_research.portfolio.engine import rebalance_days, run_targets
from tests.backtest.test_engine import market

SEEDS = range(12)


def edge_market(seed: int, n: int = 160, k: int = 25):
    rng = np.random.default_rng(seed)
    close = 10 * np.cumprod(1 + rng.normal(0, 0.03, (n, k)), axis=0)
    open_ = close * (1 + rng.normal(0, 0.01, (n, k)))
    m = market(open_, close, signal=np.where(rng.random((n, k)) < 0.15, rng.random((n, k)), np.nan),
               traded=rng.random((n, k)) > 0.15, limit_down=rng.random((n, k)) < 0.05,
               open_limit_up=rng.random((n, k)) < 0.05, price_jump=rng.random((n, k)) < 0.003)
    m.adv_value[...] = rng.uniform(2e4, 5e5, (n, k))
    m.adv_value[rng.random((n, k)) < 0.05] = np.nan                       # missing ADV
    m.half_spread, m.sigma = rng.uniform(0, 0.01, (n, k)), rng.uniform(0.01, 0.05, (n, k))
    m.tick_half_spread = np.full((n, k), 0.001)
    m.universe[...] = rng.random((n, k)) > 0.1
    return m


@pytest.mark.parametrize("seed", SEEDS)
def test_event_engine_invariants(seed):
    m = edge_market(seed)
    s = Strategy(hold_sessions=5, max_positions=6, renew=True, initial_equity=1e6, cap_adv_share=0.05)
    for selector in (None, random_selector(seed)):
        res = run(m, s, costs=CostModel()) if selector is None else run(m, s, selector, CostModel())
        assert (res.cash >= -1e-6).all() and (res.invested >= -1e-9).all()
        assert (res.n_positions <= s.max_positions).all()
        np.testing.assert_allclose(res.equity, res.cash + res.invested, rtol=1e-12)
        assert res.costs_paid == pytest.approx(sum(t.costs for t in res.trades), rel=1e-9)
        col = {sym: j for j, sym in enumerate(m.symbols)}
        for t in res.trades:
            adv = m.adv_value[t.entry_index - 1, col[t.symbol]]
            assert np.isfinite(adv) and t.shares * t.entry_price <= s.cap_adv_share * adv + 1e-6
            assert t.exit_index - t.entry_index >= 2 or t.exit_reason in ("data_error", "open_at_end")
            if t.exit_reason == "planned":
                assert m.traded[t.exit_index, col[t.symbol]]                 # exits only at traded closes


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("schedule", ["weekly", "monthly"])
def test_portfolio_engine_invariants(seed, schedule):
    m = edge_market(seed)
    m.price_jump[...] = False                    # data-error exits sell at the close; checked in test_portfolio
    sell_lag = 3
    c = Construction(n_names=5, entry_rank=5, exit_rank=10, min_adv_value=0, max_participation=0.05)
    scores = np.random.default_rng(seed + 100).random(m.open.shape)
    res = run_targets(m, c, lambda i: scores[i], schedule, 1e6, np.full(m.open.shape, None, dtype=object),
                      costs=CostModel(), sell_lag=sell_lag)
    assert (res.cash >= -1e-6).all() and (res.equity >= res.cash - 1e-6).all()
    assert res.costs_paid == pytest.approx(sum(t[4] for t in res.trades), rel=1e-9)
    decisions = set(rebalance_days(m.dates, schedule).tolist())
    lots: dict[int, list[list[float]]] = {}
    held = np.zeros(m.open.shape[1])
    for i, j, qty, price, _ in res.trades:
        assert i - 1 in decisions and m.traded[i, j]                         # trades at the open after a decision
        adv = m.adv_value[i - 1, j]
        assert np.isfinite(adv) and abs(qty) * price <= c.max_participation * adv + 1e-6
        if qty > 0:
            assert not m.open_limit_up[i, j]
            lots.setdefault(j, []).append([i, qty])
        else:
            assert not m.limit_down[i, j]
            eligible = sum(sh for b, sh in lots.get(j, []) if i - b >= sell_lag)
            assert -qty <= eligible + 1e-9                                   # never beyond the eligible lots
            remaining = -qty
            for lot in lots[j]:
                take = min(lot[1], remaining)
                lot[1] -= take
                remaining -= take
        held[j] += qty
        assert held[j] >= -1e-9
    assert 0.0 <= res.stale_value_share_mean <= res.stale_value_share_max <= 1.0


def test_marks_skip_sessions_without_trades():
    # one stock bought at the open of 1, its close jumps on a no-trade session (reference price), then trades again
    close = np.array([10.0, 10.0, 10.0, 13.0, 10.5, 10.5, 10.5, 10.5])
    m = market(close.copy(), close.copy(), signal=[1] + [np.nan] * 7, traded=[1, 1, 1, 0, 1, 1, 1, 1])
    s = Strategy(hold_sessions=6, max_positions=1, renew=False, initial_equity=1000.0)
    traded, legacy = run(m, s, mark="traded"), run(m, s, mark="legacy")
    assert traded.invested[3] == pytest.approx(traded.invested[2])          # the no-trade close is not a mark
    assert legacy.invested[3] == pytest.approx(legacy.invested[2] * 1.3)    # legacy marks the reference price
    assert traded.invested[4] == pytest.approx(legacy.invested[4])          # same again after a traded close


def test_writedown_values_stocks_that_stop_trading_at_zero():
    close = np.full(30, 10.0)
    traded = np.r_[np.ones(4), np.zeros(26)]                                # stops trading after session 3
    m = market(close.copy(), close.copy(), signal=[1] + [np.nan] * 29, traded=traded)
    s = Strategy(hold_sessions=3, max_positions=1, renew=False, initial_equity=1000.0)
    keep, cut = run(m, s), run(m, s, writedown_after=10)
    assert keep.invested[-1] > 0 and cut.invested[-1] == 0.0                 # stuck: cannot be sold, written down
    assert cut.invested[13] == pytest.approx(keep.invested[13]) and cut.invested[14] == 0.0
    from tests.backtest.test_portfolio import no_industry
    c = Construction(n_names=1, entry_rank=1, exit_rank=1, min_adv_value=-1)
    m.adv_value[...] = 1e12
    p_keep = run_targets(m, c, lambda i: np.array([1.0]), "monthly", 1000.0, no_industry(m))
    p_cut = run_targets(m, c, lambda i: np.array([1.0]), "monthly", 1000.0, no_industry(m), writedown_after=10)
    assert p_keep.equity[-1] > p_cut.equity[-1] == pytest.approx(p_cut.cash[-1])
