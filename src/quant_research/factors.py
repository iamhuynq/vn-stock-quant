"""Factor Engine, factor set f1 (docs/factor-engine-plan.md): point-in-time cross-sectional factor scores.

Built inside `quant build` (same atomic transaction) into `stock_factors`. Raw values use trailing data only;
each date is normalized over the scoring universe of that date:
raw -> winsorize 1% / 99% -> percentile rank (on raw) -> z-score (of the winsorized value) -> quintile bucket,
plus an industry-neutral z (z minus the ICB level-2 mean z of that date).
"""

import hashlib
from dataclasses import dataclass

import duckdb

FACTOR_SET = "f1"
# name: (definition, sign note)
FACTORS = {
    "liquidity": ("ln(adv_value_20); also the size proxy (no market capitalization in the warehouse)",
                  "high = more liquid"),
    "momentum_12_1": ("adj_close[t-21] / adj_close[t-250] - 1; NULL if a price_jump lies in the window",
                      "high = past winner"),
    "momentum_1m": ("return_20d; NULL if a price_jump lies in the last 20 sessions", "high = past winner"),
    "reversal_1w": ("-return_5d; NULL if a price_jump lies in the last 5 sessions", "high = recent loser"),
    "volatility": ("volatility_20", "high = volatile"),
    "beta": ("regr_slope of clean daily returns on mkt_ret_1d over 250 sessions, at least 200 pairs",
             "high = moves more with the market"),
    "order_flow": ("mean order_imbalance over 5 sessions (at least 3 values); order placements, not fills",
                   "high = buyers placed more"),
    "foreign_flow": ("foreign_net_ratio_20; NULL if foreign_inconsistent in the last 20 sessions",
                     "high = foreign net buying"),
    "volume_surge": ("volume_ratio_20", "high = unusual volume"),
}


@dataclass(frozen=True)
class FactorParams:
    min_adv_value: float = 1e9         # scoring universe = ResearchParams() defaults
    min_session_index: int = 20
    min_stocks: int = 30               # per date and factor
    min_industry: int = 3              # scored stocks of an industry for the industry-neutral z
    winsor: float = 0.01


RAW_SQL = """
CREATE OR REPLACE TEMP TABLE factor_raw AS
WITH p AS (
    SELECT symbol, date, adj_close,
           is_traded AND NOT price_jump AND NOT bad_source_date
               AND lag(is_traded) OVER w AND lag(adj_close) OVER w > 0 AS clean,
           adj_close / lag(adj_close) OVER w - 1 AS r,
           lag(adj_close, 21) OVER w AS close_21, lag(adj_close, 250) OVER w AS close_250,
           sum(price_jump::INT) OVER (w ROWS BETWEEN 250 PRECEDING AND CURRENT ROW) AS jumps_250,
           sum(price_jump::INT) OVER (w ROWS BETWEEN 20 PRECEDING AND CURRENT ROW) AS jumps_20,
           sum(price_jump::INT) OVER (w ROWS BETWEEN 5 PRECEDING AND CURRENT ROW) AS jumps_5,
           sum(foreign_inconsistent::INT) OVER (w ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS bad_foreign_20
    FROM daily_panel
    WINDOW w AS (PARTITION BY symbol ORDER BY date)
),
b AS (
    SELECT p.symbol, p.date,
           regr_slope(CASE WHEN p.clean THEN p.r END, m.mkt_ret_1d) OVER v AS beta,
           regr_count(CASE WHEN p.clean THEN p.r END, m.mkt_ret_1d) OVER v AS beta_n
    FROM p JOIN market_daily m USING (date)
    WINDOW v AS (PARTITION BY p.symbol ORDER BY p.date ROWS BETWEEN 249 PRECEDING AND CURRENT ROW)
),
o AS (
    SELECT symbol, date,
           CASE WHEN count(order_imbalance) OVER x >= 3 THEN avg(order_imbalance) OVER x END AS order_flow
    FROM stock_features
    WINDOW x AS (PARTITION BY symbol ORDER BY date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW)
),
wide AS (
    SELECT f.symbol, f.date, f.industry_l2_code AS industry,
           CASE WHEN f.adv_value_20 > 0 THEN ln(f.adv_value_20) END AS liquidity,
           CASE WHEN p.jumps_250 = 0 AND p.close_250 > 0 THEN p.close_21 / p.close_250 - 1 END AS momentum_12_1,
           CASE WHEN p.jumps_20 = 0 THEN f.return_20d END AS momentum_1m,
           CASE WHEN p.jumps_5 = 0 THEN -f.return_5d END AS reversal_1w,
           f.volatility_20 AS volatility,
           CASE WHEN b.beta_n >= 200 THEN b.beta END AS beta,
           o.order_flow,
           CASE WHEN p.bad_foreign_20 = 0 THEN f.foreign_net_ratio_20 END AS foreign_flow,
           f.volume_ratio_20 AS volume_surge
    FROM stock_features f JOIN p USING (symbol, date) JOIN b USING (symbol, date) JOIN o USING (symbol, date)
    WHERE f.is_traded AND f.adv_value_20 > {min_adv_value} AND f.session_index > {min_session_index}
      AND NOT f.price_jump AND NOT f.bad_source_date
)
SELECT symbol, date, industry, factor, value::DOUBLE AS value
FROM (UNPIVOT wide ON {factor_columns} INTO NAME factor VALUE value)
WHERE value IS NOT NULL AND isfinite(value);
"""

NORMALIZE_SQL = """
CREATE OR REPLACE TABLE stock_factors AS
WITH n AS (
    SELECT date, factor, count(*) AS n,
           quantile_cont(value, {winsor}) AS lo, quantile_cont(value, 1 - {winsor}) AS hi
    FROM factor_raw GROUP BY ALL
),
w AS (
    SELECT r.*, least(greatest(r.value, n.lo), n.hi) AS winsorized
    FROM factor_raw r JOIN n USING (date, factor) WHERE n.n >= {min_stocks}
),
z AS (
    SELECT *,
           percent_rank() OVER (PARTITION BY date, factor ORDER BY value) AS rank_pct,
           (winsorized - avg(winsorized) OVER g) / nullif(stddev_pop(winsorized) OVER g, 0) AS z
    FROM w WINDOW g AS (PARTITION BY date, factor)
)
SELECT date, symbol, factor, industry, value, winsorized, rank_pct, z,
       1 + least(4, floor(rank_pct * 5))::INTEGER AS bucket,
       CASE WHEN industry IS NOT NULL AND count(z) OVER i >= {min_industry} THEN z - avg(z) OVER i END AS z_industry
FROM z WINDOW i AS (PARTITION BY date, factor, industry)
ORDER BY date, factor, symbol;
"""


def version() -> str:
    """Hash of the factor definitions and SQL: changes whenever the meaning of a score changes."""
    text = RAW_SQL + NORMALIZE_SQL + repr(sorted(FACTORS.items()))
    return hashlib.sha256(text.encode()).hexdigest()[:8]


def build_factors(con: duckdb.DuckDBPyConnection, params: FactorParams = FactorParams()) -> int:
    """Create stock_factors and factor_definitions from daily_panel, market_daily and stock_features."""
    con.execute(RAW_SQL.format(min_adv_value=float(params.min_adv_value),
                               min_session_index=int(params.min_session_index),
                               factor_columns=", ".join(FACTORS)))
    con.execute(NORMALIZE_SQL.format(winsor=float(params.winsor), min_stocks=int(params.min_stocks),
                                     min_industry=int(params.min_industry)))
    con.execute("DROP TABLE factor_raw")
    con.execute("""CREATE OR REPLACE TABLE factor_definitions (factor VARCHAR PRIMARY KEY, factor_set VARCHAR,
                   version VARCHAR, definition VARCHAR, sign_note VARCHAR)""")
    con.executemany("INSERT INTO factor_definitions VALUES (?, ?, ?, ?, ?)",
                    [(name, FACTOR_SET, version(), d, s) for name, (d, s) in FACTORS.items()])
    return con.execute("SELECT count(*) FROM stock_factors").fetchone()[0]
