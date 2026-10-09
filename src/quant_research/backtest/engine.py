"""Daily long-only portfolio simulation with Vietnamese market constraints.

Timeline of session i:
  open  : enter new positions from the candidate list built at the close of i-1 (signal of i-1);
          skip a stock whose open is at the ceiling or that has no trade.
  close : (1) data-error jump on a held stock -> close it at its last valid close;
          (2) positions at/after their planned exit (and at least 2 sessions after entry, T+2): renew if
              the stock was a candidate at the close of i-1 (renewal on), otherwise sell at the close,
              unless the close is at the floor or the stock did not trade (retry next session);
          (3) mark to market; record equity.
Sizing: each new position gets equity(prev close) / K, capped by cash and by capacity
(cap_adv_share x adv_value at the signal date). Costs: fee on both sides, tax on sells; with a cost model
(cost model v1), also half-spread + square-root impact per side, from the inputs of the previous close.
Entries need a valid ADV at the signal close (finite and > 0); otherwise they are blocked and counted
(entries_blocked_no_adv), never uncapped.
Marking: mark="traded" (default) marks a position at its last TRADED close; a session without trades keeps the
previous mark (its close is only the reference price). mark="legacy" also takes the close of no-trade sessions:
the pre-registered paper portfolio keeps it so its forward record stays comparable.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np

from quant_research.backtest.costs import CostModel
from quant_research.backtest.data import Market

STALE_SESSIONS = 5


@dataclass(frozen=True)
class Strategy:
    hold_sessions: int = 10
    max_positions: int = 20
    renew: bool = True
    fee: float = 0.0015
    sell_tax: float = 0.001
    cap_adv_share: float = 0.05
    initial_equity: float = 10e9

    def __post_init__(self) -> None:
        if self.hold_sessions < 2:
            raise ValueError("hold_sessions must be >= 2 (T+2 settlement)")


@dataclass
class Position:
    col: int
    shares: float
    entry_index: int
    entry_price: float
    entry_cost: float
    planned_exit: int
    last_price: float
    renewals: int = 0
    last_trade: int = -1                 # session of the last traded close used as the mark


@dataclass
class Trade:
    symbol: str
    entry_index: int
    exit_index: int
    entry_price: float
    exit_price: float
    shares: float
    gross_pnl: float
    costs: float
    renewals: int
    exit_reason: str


@dataclass
class Result:
    equity: np.ndarray
    cash: np.ndarray
    invested: np.ndarray
    n_positions: np.ndarray
    trades: list[Trade] = field(default_factory=list)
    costs_paid: float = 0.0
    traded_notional: float = 0.0
    capacity_capped: int = 0
    entries_blocked: int = 0
    exits_delayed: int = 0
    data_error_exits: int = 0
    cost_fallbacks: int = 0
    entries_blocked_no_adv: int = 0
    stale_value_share_max: float = 0.0   # share of invested value marked with a price older than STALE_SESSIONS
    stale_value_share_mean: float = 0.0  # over sessions with positions


# A candidate selector returns, for the close of session i, the ordered column indices to buy at i+1.
Selector = Callable[[Market, int], list[int]]


def signal_selector(market: Market, i: int) -> list[int]:
    """Stocks in the signal decile at the close of i, strongest signal first (ties by symbol)."""
    cols = np.flatnonzero(~np.isnan(market.signal[i]))
    return sorted(cols.tolist(), key=lambda j: (-market.signal[i, j], market.symbols[j]))


def random_selector(seed: int, fraction: float = 0.1) -> Selector:
    """Control: a random `fraction` of the universe each day (same size as one decile), random order.
    Using the whole universe would make every held stock a 'candidate' and disable exits."""
    rng = np.random.default_rng(seed)

    def select(market: Market, i: int) -> list[int]:
        cols = np.flatnonzero(market.universe[i])
        k = int(round(len(cols) * fraction))
        return rng.choice(cols, size=k, replace=False).tolist() if k else []
    return select


def run(market: Market, strategy: Strategy, selector: Selector = signal_selector,
        costs: CostModel | None = None, mark: str = "traded") -> Result:
    if mark not in ("traded", "legacy"):
        raise ValueError(f"unknown mark {mark!r}")
    n = len(market.dates)
    stale_sum, held_sessions = 0.0, 0
    res = Result(np.zeros(n), np.zeros(n), np.zeros(n), np.zeros(n, dtype=int))
    cash = strategy.initial_equity
    positions: dict[int, Position] = {}
    candidates: list[int] = []
    candidate_set: set[int] = set()
    prev_equity = cash

    for i in range(n):
        # ---- open: entries from the previous close's candidates
        for j in candidates:
            if len(positions) >= strategy.max_positions:
                break
            if j in positions:
                continue
            price = market.open[i, j]
            if np.isnan(price) or not market.traded[i, j] or market.open_limit_up[i, j]:
                res.entries_blocked += 1
                continue
            budget = prev_equity / strategy.max_positions
            adv = market.adv_value[i - 1, j] if i > 0 else np.nan
            if not (np.isfinite(adv) and adv > 0):
                res.entries_blocked_no_adv += 1
                continue
            cap = strategy.cap_adv_share * adv
            if cap < budget:
                res.capacity_capped += 1
            extra = _extra(res, market, costs, i, j, min(budget, cap))
            notional = min(budget, cap, cash / (1 + strategy.fee + extra))
            if notional <= 0:
                continue
            if costs is not None:
                extra = _extra(res, market, costs, i, j, notional)
            cost = notional * (strategy.fee + extra)
            cash -= notional + cost
            res.costs_paid += cost
            res.traded_notional += notional
            positions[j] = Position(j, notional / price, i, price, cost, i + strategy.hold_sessions, price, last_trade=i)

        # ---- close: data errors, exits/renewals, mark to market
        for j in list(positions):
            pos = positions[j]
            close = market.close[i, j]
            if market.price_jump[i, j]:
                extra = _extra(res, market, costs, i, j, pos.shares * pos.last_price)
                _sell(res, positions, j, i, pos.last_price, strategy, market, "data_error", extra)
                cash += _proceeds(pos, pos.last_price, strategy, extra)
                res.data_error_exits += 1
                continue
            if not np.isnan(close) and (mark == "legacy" or market.traded[i, j]):
                pos.last_price = close
                pos.last_trade = i
            if i < pos.planned_exit or i < pos.entry_index + 2:
                continue
            if strategy.renew and j in candidate_set:
                pos.planned_exit = i + strategy.hold_sessions
                pos.renewals += 1
                continue
            if np.isnan(close) or not market.traded[i, j] or market.limit_down[i, j]:
                res.exits_delayed += 1
                continue
            extra = _extra(res, market, costs, i, j, pos.shares * close)
            cash += _proceeds(pos, close, strategy, extra)
            _sell(res, positions, j, i, close, strategy, market, "planned", extra)

        invested = sum(p.shares * p.last_price for p in positions.values())
        if invested > 0:
            stale = sum(p.shares * p.last_price for p in positions.values()
                        if i - p.last_trade > STALE_SESSIONS) / invested
            res.stale_value_share_max = max(res.stale_value_share_max, stale)
            stale_sum, held_sessions = stale_sum + stale, held_sessions + 1
        res.cash[i], res.invested[i], res.n_positions[i] = cash, invested, len(positions)
        res.equity[i] = prev_equity = cash + invested
        candidates = selector(market, i)
        candidate_set = set(candidates)

    for j in list(positions):                      # mark open positions at the end
        pos = positions[j]
        res.trades.append(Trade(str(market.symbols[j]), pos.entry_index, n - 1, pos.entry_price, pos.last_price,
                                pos.shares, pos.shares * (pos.last_price - pos.entry_price), pos.entry_cost,
                                pos.renewals, "open_at_end"))
    res.stale_value_share_mean = stale_sum / held_sessions if held_sessions else 0.0
    return res


def _extra(res: Result, market: Market, costs: CostModel | None, i: int, j: int, notional: float) -> float:
    """Cost model v1 cost per side (0 without a model), from the inputs of the previous close."""
    if costs is None:
        return 0.0
    row = max(i - 1, 0)
    if costs.spread == "none":
        hs = 0.0
    else:
        spreads = market.tick_half_spread if costs.spread == "tick" else market.half_spread
        hs = spreads[row, j] if spreads is not None else np.nan
    sigma = market.sigma[row, j] if market.sigma is not None else np.nan
    value, fallback = costs.side(hs, sigma, market.adv_value[row, j], notional)
    res.cost_fallbacks += fallback
    return value


def _proceeds(pos: Position, price: float, strategy: Strategy, extra: float = 0.0) -> float:
    gross = pos.shares * price
    return gross - gross * (strategy.fee + strategy.sell_tax + extra)


def _sell(res: Result, positions: dict[int, Position], j: int, i: int, price: float, strategy: Strategy,
          market: Market, reason: str, extra: float = 0.0) -> None:
    pos = positions.pop(j)
    gross = pos.shares * price
    sell_cost = gross * (strategy.fee + strategy.sell_tax + extra)
    res.costs_paid += sell_cost
    res.traded_notional += gross
    res.trades.append(Trade(str(market.symbols[j]), pos.entry_index, i, pos.entry_price, price, pos.shares,
                            pos.shares * (price - pos.entry_price), pos.entry_cost + sell_cost, pos.renewals, reason))
