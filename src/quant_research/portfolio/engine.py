"""Target-weight engine (docs/portfolio-construction-plan.md).

At each rebalance close t the targets are computed from data known at t; trades happen at the open of t + 1:
sells first, then buys with the cash available. Rules:
- an order is capped at max_participation x ADV20(t); the rest of the move is skipped;
- no buy at an open at the ceiling, no trade in a stock without a trade or an open price;
- no sell when the session closes at the floor (the open has no floor flag; approximation);
- T+2: shares bought at the open of b can be sold from the open of b + 3 (they arrive in the afternoon of b + 2);
- a held stock with a data-error jump is sold at its last valid close (as in the event engine).
Costs: commission on both sides, sell tax, plus cost model v1 (inputs of the decision close) when given.
Between rebalances, positions drift with prices.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np

from quant_research.backtest.costs import CostModel
from quant_research.backtest.data import Market
from quant_research.portfolio.construction import Construction, ranks, select, target_weights

FEE, SELL_TAX = 0.0015, 0.001
Scores = Callable[[int], np.ndarray]     # rebalance close index -> score per column (NaN = no score)


@dataclass
class PortfolioResult:
    equity: np.ndarray
    cash: np.ndarray
    n_names: np.ndarray
    traded_notional: float = 0.0
    costs_paid: float = 0.0
    cost_fallbacks: int = 0
    orders_capped: int = 0
    orders_blocked: int = 0
    data_error_exits: int = 0
    max_industry_weight: float = 0.0
    trades: list[tuple] = field(default_factory=list)     # (session, column, shares (+ buy / - sell), price, cost)


def rebalance_days(dates: np.ndarray, schedule: str) -> np.ndarray:
    """Indices of the first session of each week or month (the decision closes)."""
    if schedule == "weekly":
        period = (dates.astype("datetime64[D]").astype(int) + 3) // 7           # Monday-based weeks
    elif schedule == "monthly":
        period = dates.astype("datetime64[M]").astype(int)
    else:
        raise ValueError(f"unknown schedule {schedule!r}")
    return np.flatnonzero(np.r_[True, period[1:] != period[:-1]])


def run_targets(market: Market, c: Construction, scores: Scores, schedule: str, initial: float,
                industry: np.ndarray, cash_on: np.ndarray | None = None, costs: CostModel | None = None
                ) -> PortfolioResult:
    """industry: (dates x symbols) object keys; cash_on: bool per date, True = hold cash after that close."""
    n, k = market.open.shape
    res = PortfolioResult(np.zeros(n), np.zeros(n), np.zeros(n, dtype=int))
    shares = np.zeros(k)
    last_buy = np.full(k, -10)
    last_price = np.full(k, np.nan)
    cash = initial
    is_rebalance = np.zeros(n, bool)
    is_rebalance[rebalance_days(market.dates, schedule)] = True
    targets: dict[int, float] | None = None
    decision = -1
    for i in range(n):
        if targets is not None:                                   # open of the session after a rebalance close
            cash = _trade(market, c, res, i, decision, targets, shares, last_buy, last_price, cash, costs)
            targets = None
        for j in np.flatnonzero(shares > 0):                      # close: data errors, then mark to market
            if market.price_jump[i, j]:
                value = shares[j] * last_price[j]
                cost = value * (FEE + SELL_TAX)
                cash += value - cost
                res.costs_paid += cost
                res.traded_notional += value
                res.trades.append((i, int(j), -shares[j], last_price[j], cost))
                res.data_error_exits += 1
                shares[j] = 0.0
            elif np.isfinite(market.close[i, j]):
                last_price[j] = market.close[i, j]
        held_value = float(np.nansum(shares * last_price))
        res.equity[i], res.cash[i], res.n_names[i] = cash + held_value, cash, int((shares > 0).sum())
        if is_rebalance[i] and i < n - 1:
            decision = i
            if cash_on is not None and cash_on[i]:
                targets = {}
            else:
                eligible = market.universe[i] & (np.nan_to_num(market.adv_value[i]) > c.min_adv_value)
                chosen = select(ranks(scores(i), eligible), set(np.flatnonzero(shares > 0).tolist()), c)
                sigma = market.sigma[i] if market.sigma is not None else np.full(k, np.nan)
                targets = target_weights(chosen, c, sigma, industry[i])
                ind: dict = {}
                for j, w in targets.items():
                    ind[industry[i, j]] = ind.get(industry[i, j], 0.0) + w
                res.max_industry_weight = max([res.max_industry_weight, *[w for key, w in ind.items() if key]])
    return res


def _extra(res: PortfolioResult, market: Market, costs: CostModel | None, t: int, j: int, value: float) -> float:
    if costs is None:
        return 0.0
    if costs.spread == "none":
        hs = 0.0
    else:
        arr = market.tick_half_spread if costs.spread == "tick" else market.half_spread
        hs = arr[t, j] if arr is not None else np.nan
    sigma = market.sigma[t, j] if market.sigma is not None else np.nan
    v, fallback = costs.side(hs, sigma, market.adv_value[t, j], value)
    res.cost_fallbacks += fallback
    return v


def _trade(market: Market, c: Construction, res: PortfolioResult, i: int, t: int, targets: dict[int, float],
           shares: np.ndarray, last_buy: np.ndarray, last_price: np.ndarray, cash: float,
           costs: CostModel | None) -> float:
    price = market.open[i]
    equity = cash + float(np.nansum(shares * last_price))           # value at the decision close
    wanted = {j: targets.get(j, 0.0) * equity for j in set(targets) | set(np.flatnonzero(shares > 0).tolist())}
    cap = c.max_participation * np.where(np.isfinite(market.adv_value[t]), market.adv_value[t], np.inf)
    tradable = market.traded[i] & np.isfinite(price) & (price > 0)
    buys = []
    for j, target in sorted(wanted.items()):
        current = shares[j] * price[j] if tradable[j] else np.nan
        if not np.isfinite(current):
            if target != shares[j] * last_price[j]:
                res.orders_blocked += 1
            continue
        delta = target - current
        if delta < 0:                                               # sells first
            if market.limit_down[i, j] or i - last_buy[j] < 3:
                res.orders_blocked += 1
                continue
            value = min(-delta, cap[j], current)
            res.orders_capped += value < -delta - 1e-9
            cost = value * (FEE + SELL_TAX + _extra(res, market, costs, t, j, value))
            cash += value - cost
            shares[j] -= value / price[j]
            if shares[j] * price[j] < 1e-6:
                shares[j] = 0.0
            res.costs_paid += cost
            res.traded_notional += value
            res.trades.append((i, int(j), -value / price[j], price[j], cost))
        elif delta > 0:
            if market.open_limit_up[i, j]:
                res.orders_blocked += 1
                continue
            buys.append((j, min(delta, cap[j])))
            res.orders_capped += cap[j] < delta - 1e-9
    for j, value in buys:
        rate = FEE + _extra(res, market, costs, t, j, value)
        value = min(value, cash / (1 + rate))
        if value <= 0:
            continue
        cost = value * rate
        cash -= value + cost
        shares[j] += value / price[j]
        last_buy[j] = i
        last_price[j] = price[j] if not np.isfinite(last_price[j]) else last_price[j]
        res.costs_paid += cost
        res.traded_notional += value
        res.trades.append((i, int(j), value / price[j], price[j], cost))
    return cash
