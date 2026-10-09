"""Benchmarks and matched controls (docs/economic-validation-plan.md).

- Liquidity-weighted universe: daily weights proportional to ADV20 at the previous close (the value-weight
  proxy; the warehouse has no market capitalization). Gross, like the equal-weight benchmark.
- Matched random controls: each day, every candidate of the strategy's selector is replaced by a random
  universe stock with the same key (ICB level-2 industry, or Factor Engine beta quintile), so the control
  holds the same industry / beta mix with random names.
"""

import duckdb
import numpy as np

from quant_research.backtest.data import Market
from quant_research.backtest.engine import Selector, signal_selector

NO_KEY = "__none__"


def liquidity_weighted_curve(close: np.ndarray, universe: np.ndarray, adv: np.ndarray,
                             initial: float = 1.0) -> np.ndarray:
    rets = close[1:] / close[:-1] - 1
    w = np.where(universe[:-1] & np.isfinite(rets) & np.isfinite(adv[:-1]) & (adv[:-1] > 0), adv[:-1], 0.0)
    total = w.sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        daily = np.where(total > 0, (w * np.nan_to_num(rets)).sum(axis=1) / np.where(total > 0, total, 1), 0.0)
    return initial * np.concatenate([[1.0], np.cumprod(1 + daily)])


def matched_random_selector(seed: int, keys: np.ndarray, base: Selector = signal_selector) -> Selector:
    """Replace each candidate of `base` by a random universe stock with the same key on that date."""
    rng = np.random.default_rng(seed)

    def select(market: Market, i: int) -> list[int]:
        wanted = base(market, i)
        if not wanted:
            return []
        pools: dict = {}
        for j in np.flatnonzero(market.universe[i]):
            pools.setdefault(_key(keys[i, j]), []).append(int(j))
        chosen: list[int] = []
        taken: set[int] = set()
        for j in wanted:
            pool = [c for c in pools.get(_key(keys[i, j]), []) if c not in taken]
            if pool:
                pick = pool[int(rng.integers(len(pool)))]
                chosen.append(pick)
                taken.add(pick)
        return chosen
    return select


def _key(value) -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return NO_KEY
    return str(value)


def key_matrices(con: duckdb.DuckDBPyConnection, market: Market, schema: str = "rs") -> dict[str, np.ndarray]:
    """{"industry": ICB level-2 code per (date, symbol), "beta": beta quintile per (date, symbol)}."""
    d_index = {d: i for i, d in enumerate(market.dates.tolist())}
    s_index = {s: j for j, s in enumerate(market.symbols.tolist())}
    start, end = market.dates[0].item(), market.dates[-1].item()
    out = {}
    for name, sql in (
            ("industry", f"""SELECT symbol, date, industry_l2_code AS k FROM {schema}.stock_features
                             WHERE date BETWEEN ? AND ?"""),
            ("beta", f"""SELECT symbol, date, bucket::VARCHAR AS k FROM {schema}.stock_factors
                         WHERE factor = 'beta' AND date BETWEEN ? AND ?""")):
        mat = np.full(market.open.shape, None, dtype=object)
        df = con.execute(sql, [start, end]).df()
        if not df.empty:
            i = np.array([d_index.get(d, -1) for d in df["date"].dt.date], dtype=int)
            j = np.array([s_index.get(s, -1) for s in df["symbol"]], dtype=int)
            ok = (i >= 0) & (j >= 0)
            mat[i[ok], j[ok]] = df["k"].to_numpy(object)[ok]
        out[name] = mat
    return out
