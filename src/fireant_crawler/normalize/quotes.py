"""historical-quotes rows -> quotes_daily rows and adj_ratio_segments rows.

Prices are raw (unadjusted) in thousand VND (`unit` = 1000); values are VND.
`adjRatio` is a cumulative factor relative to the latest session: adjusted = raw / adj_ratio.
"""

from datetime import date, datetime
from typing import Any

from fireant_crawler.normalize.values import NormalizationError, parse_date, to_float

FIELD_MAP: dict[str, str] = {
    "priceOpen": "price_open",
    "priceHigh": "price_high",
    "priceLow": "price_low",
    "priceClose": "price_close",
    "priceAverage": "price_average",
    "priceBasic": "price_basic",
    "totalVolume": "total_volume",
    "dealVolume": "deal_volume",
    "putthroughVolume": "putthrough_volume",
    "totalValue": "total_value",
    "putthroughValue": "putthrough_value",
    "buyForeignQuantity": "buy_foreign_quantity",
    "buyForeignValue": "buy_foreign_value",
    "sellForeignQuantity": "sell_foreign_quantity",
    "sellForeignValue": "sell_foreign_value",
    "buyCount": "buy_count",
    "buyQuantity": "buy_quantity",
    "sellCount": "sell_count",
    "sellQuantity": "sell_quantity",
    "adjRatio": "adj_ratio",
    "currentForeignRoom": "current_foreign_room",
    "propTradingNetDealValue": "prop_trading_net_deal_value",
    "propTradingNetPTValue": "prop_trading_net_pt_value",
    "propTradingNetValue": "prop_trading_net_value",
    "unit": "unit",
}
_KNOWN_KEYS = frozenset(FIELD_MAP) | {"date", "symbol"}


def normalize_quotes(symbol: str, rows: list[dict[str, Any]], fetched_at: datetime) -> list[dict[str, Any]]:
    """Map raw rows; one row per date (later rows win), sorted by date."""
    symbol = symbol.upper()
    by_date: dict[date, dict[str, Any]] = {}
    for raw in rows:
        unknown = set(raw) - _KNOWN_KEYS
        if unknown:
            raise NormalizationError(f"{symbol}: unknown quote fields {sorted(unknown)} (API schema changed?)")
        raw_symbol = raw.get("symbol")
        if raw_symbol is not None and str(raw_symbol).upper() != symbol:
            raise NormalizationError(f"{symbol}: row belongs to {raw_symbol}")
        day = parse_date(raw.get("date"))
        if day is None:
            raise NormalizationError(f"{symbol}: quote row without date")
        row: dict[str, Any] = {"symbol": symbol, "date": day, "fetched_at": fetched_at}
        row.update({column: to_float(raw.get(key)) for key, column in FIELD_MAP.items()})
        by_date[day] = row
    return [by_date[d] for d in sorted(by_date)]


def adj_ratio_segments(quotes: list[dict[str, Any]], fetched_at: datetime) -> list[dict[str, Any]]:
    """Collapse consecutive equal adj_ratio values into [start_date, end_date] segments."""
    segments: list[dict[str, Any]] = []
    for row in sorted(quotes, key=lambda r: r["date"]):
        current = segments[-1] if segments else None
        if current and current["adj_ratio"] == row["adj_ratio"]:
            current["end_date"] = row["date"]
            continue
        segments.append({
            "symbol": row["symbol"],
            "fetched_at": fetched_at,
            "start_date": row["date"],
            "end_date": row["date"],
            "adj_ratio": row["adj_ratio"],
        })
    return segments


def last_traded_date(quotes: list[dict[str, Any]]) -> date | None:
    """Last session with volume > 0. Delisted symbols are forward-filled with zero volume after it."""
    traded = [r["date"] for r in quotes if (r.get("total_volume") or 0) > 0]
    return max(traded, default=None)
