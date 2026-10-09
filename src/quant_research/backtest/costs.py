"""Cost model v1 (docs/economic-validation-plan.md): commission + sell tax + half-spread + square-root impact.

Inputs are built by `quant build` into `stock_trading_costs`, point in time: the row of date t uses data up
to t only, and the engine reads the row of the previous close (the decision time).
- Tick floor: half a tick over the raw close (tick rule of daily_panel: HOSE 10 / 50 / 100 VND, else 100).
- CHL estimate (Abdi-Ranaldo 2017): S^2 = 4 mean[(c_k - eta_k)(c_k - eta_{k+1})] over the pairs inside the
  last 21 sessions (k + 1 <= t), eta = mid of log high and log low; half-spread = S / 2, NULL under 10 pairs.
"""

import math
from dataclasses import dataclass

import duckdb
import numpy as np

MIN_PAIRS = 10

INPUTS_SQL = """
CREATE OR REPLACE TABLE stock_trading_costs AS
WITH p AS (
    SELECT symbol, date, close_raw, exchange_now, adj_close, adj_high, adj_low,
           is_traded AND NOT price_jump AND NOT bad_source_date AND adj_high > 0 AND adj_low > 0 AND adj_close > 0
               AS ok,
           ln(adj_close) AS c, (ln(adj_high) + ln(adj_low)) / 2 AS eta
    FROM daily_panel
),
pairs AS (
    SELECT symbol, date,
           CASE WHEN ok AND lag(ok) OVER w THEN (lag(c) OVER w - lag(eta) OVER w) * (lag(c) OVER w - eta) END AS prod
    FROM p WINDOW w AS (PARTITION BY symbol ORDER BY date)
),
chl AS (
    SELECT symbol, date,
           CASE WHEN count(prod) OVER x >= {min_pairs} THEN sqrt(greatest(4 * avg(prod) OVER x, 0)) / 2 END AS chl
    FROM pairs WINDOW x AS (PARTITION BY symbol ORDER BY date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW)
),
t AS (
    SELECT symbol, date,
           CASE WHEN close_raw > 0 THEN 0.5 * (CASE WHEN exchange_now = 'HSX' THEN
                    CASE WHEN close_raw < 10 THEN 0.01 WHEN close_raw < 50 THEN 0.05 ELSE 0.1 END
                ELSE 0.1 END) / close_raw END AS tick_half_spread       -- prices in thousand VND
    FROM p
)
SELECT t.symbol, t.date, t.tick_half_spread, chl.chl AS chl_half_spread,
       CASE WHEN t.tick_half_spread IS NOT NULL OR chl.chl IS NOT NULL
            THEN greatest(coalesce(chl.chl, 0), coalesce(t.tick_half_spread, 0)) END AS half_spread,
       f.volatility_20 AS sigma_20, f.adv_value_20
FROM t JOIN chl USING (symbol, date) JOIN stock_features f USING (symbol, date)
ORDER BY t.symbol, t.date;
"""


def build_cost_inputs(con: duckdb.DuckDBPyConnection) -> int:
    con.execute(INPUTS_SQL.format(min_pairs=MIN_PAIRS))
    return con.execute("SELECT count(*) FROM stock_trading_costs").fetchone()[0]


@dataclass(frozen=True)
class CostModel:
    """Extra cost per side on top of the strategy's commission and sell tax (fractions of traded value)."""
    k: float = 1.0                          # square-root impact coefficient
    spread: str = "max"                     # "max" = max(tick floor, CHL); "tick" = tick floor only (lower bound);
                                            # "none" = no spread (with k = 0: the flat costs plus extra_flat only)
    extra_flat: float = 0.0                 # added per side (break-even search)
    fallback_half_spread: float = 0.005     # inputs missing (new listing, no estimate)
    fallback_sigma: float = 0.03

    @property
    def name(self) -> str:
        return (f"v1_k{self.k:g}" + {"tick": "_tick", "none": "_nospread"}.get(self.spread, "")
                + (f"_plus{self.extra_flat:g}" if self.extra_flat else ""))

    def side(self, half_spread: float, sigma: float, adv: float, notional: float) -> tuple[float, bool]:
        """(cost fraction, used a fallback) for one side of `notional` VND."""
        fallback = False
        if not np.isfinite(half_spread):
            half_spread, fallback = self.fallback_half_spread, True
        if not np.isfinite(sigma):
            sigma, fallback = self.fallback_sigma, True
        if notional <= 0:
            return half_spread + self.extra_flat, fallback
        if not np.isfinite(adv) or adv <= 0:
            participation, fallback = 1.0, True             # unknown liquidity: as if trading one full ADV
        else:
            participation = notional / adv
        return half_spread + self.k * sigma * math.sqrt(participation) + self.extra_flat, fallback
