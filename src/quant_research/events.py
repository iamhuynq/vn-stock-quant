"""Event catalog v1 (Phase 5): names and descriptions of the events built by sql/06_stock_events.sql.

The catalog version is a hash of that SQL file, so changing a threshold creates a new version and earlier
event-study runs and daily rows stay attributable to the old definitions.
"""

import hashlib
from importlib import resources

EVENT_TYPES: dict[str, str] = {
    "PRICE_SURGE": "return_1d >= +5%",
    "PRICE_DROP": "return_1d <= -5%",
    "VOLUME_SPIKE": "volume >= 3x its 20-session average (doc 24)",
    "FOREIGN_BUY_SPIKE": "foreign net buying >= 50% of the 20-session average traded value",
    "FOREIGN_SELL_SPIKE": "foreign net selling >= 50% of the 20-session average traded value",
    "ORDER_IMBALANCE_SPIKE_BUY": "order_imbalance >= +0.5",
    "ORDER_IMBALANCE_SPIKE_SELL": "order_imbalance <= -0.5",
    "VOLATILITY_SPIKE": "day range >= 2.5x ATR(14)",
    "BREAKOUT": "close above the highest close of the previous 60 sessions",
    "BREAKDOWN": "close below the lowest close of the previous 60 sessions",
    "DIVERGENCE_UP_FOREIGN_SELL": "return_5d >= +5% while foreigners sold over 5 sessions",
    "DIVERGENCE_DOWN_FOREIGN_BUY": "return_5d <= -5% while foreigners bought over 5 sessions",
}
DAILY_PREFIX = "EVENT_"


def catalog_version() -> str:
    sql = resources.files("quant_research").joinpath("sql", "06_stock_events.sql").read_bytes()
    return hashlib.sha256(sql).hexdigest()[:8]
