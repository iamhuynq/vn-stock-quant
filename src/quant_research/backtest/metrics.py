"""Performance metrics (doc section 17) from a daily equity curve and the trade list."""

import math

import numpy as np

from quant_research.backtest.engine import Result

SESSIONS_PER_YEAR = 250


def drawdown(equity: np.ndarray) -> tuple[float, int]:
    """(max drawdown as a negative fraction, longest drawdown duration in sessions)."""
    peak = np.maximum.accumulate(equity)
    dd = equity / peak - 1
    longest = current = 0
    for x in dd:
        current = current + 1 if x < 0 else 0
        longest = max(longest, current)
    return float(dd.min()), longest


def curve_metrics(equity: np.ndarray) -> dict[str, float]:
    rets = equity[1:] / equity[:-1] - 1
    years = len(rets) / SESSIONS_PER_YEAR
    total = equity[-1] / equity[0] - 1
    vol = float(rets.std(ddof=1) * math.sqrt(SESSIONS_PER_YEAR)) if len(rets) > 1 else float("nan")
    mean = float(rets.mean() * SESSIONS_PER_YEAR) if len(rets) else float("nan")
    mdd, mdd_len = drawdown(equity)
    return {
        "total_return": float(total),
        "cagr": float((1 + total) ** (1 / years) - 1) if years > 0 and total > -1 else float("nan"),
        "volatility": vol,
        "sharpe": mean / vol if vol and vol > 0 else float("nan"),
        "max_drawdown": mdd,
        "max_drawdown_sessions": float(mdd_len),
    }


def strategy_metrics(res: Result, initial: float) -> dict[str, float]:
    m = curve_metrics(res.equity)
    closed = [t for t in res.trades if t.exit_reason != "open_at_end"]
    net = np.array([t.gross_pnl - t.costs for t in closed]) if closed else np.array([])
    gains, losses = net[net > 0].sum(), -net[net < 0].sum()
    years = max(len(res.equity) / SESSIONS_PER_YEAR, 1e-9)
    avg_equity = float(res.equity.mean()) if len(res.equity) else initial
    m |= {
        "trades": float(len(closed)),
        "win_rate": float((net > 0).mean()) if len(net) else float("nan"),
        "profit_factor": float(gains / losses) if losses > 0 else float("nan"),
        "avg_holding_sessions": float(np.mean([t.exit_index - t.entry_index for t in closed])) if closed else float("nan"),
        "avg_renewals": float(np.mean([t.renewals for t in closed])) if closed else float("nan"),
        "turnover_per_year": res.traded_notional / avg_equity / years,
        "costs_paid_pct_of_initial": res.costs_paid / initial,
        "exposure": float(np.mean(res.invested / np.where(res.equity > 0, res.equity, np.nan))),
        "capacity_capped_entries": float(res.capacity_capped),
        "entries_blocked": float(res.entries_blocked),
        "exits_delayed": float(res.exits_delayed),
        "data_error_exits": float(res.data_error_exits),
        "open_at_end": float(sum(t.exit_reason == "open_at_end" for t in res.trades)),
    }
    return m


def equal_weight_curve(close: np.ndarray, universe: np.ndarray, initial: float = 1.0) -> np.ndarray:
    """Daily-rebalanced equal-weight basket of the universe of the previous close (gross, no costs)."""
    rets = close[1:] / close[:-1] - 1
    held = universe[:-1] & np.isfinite(rets)
    with np.errstate(invalid="ignore"):
        sums = np.where(held, rets, 0.0).sum(axis=1)
        counts = held.sum(axis=1)
        daily = np.where(counts > 0, sums / np.maximum(counts, 1), 0.0)
    daily = np.nan_to_num(daily)
    return initial * np.concatenate([[1.0], np.cumprod(1 + daily)])
