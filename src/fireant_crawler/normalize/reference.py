"""Reference data: symbol info, fundamental snapshots, ICB industries.

Unit note: fundamental 52-week prices are in VND (not thousand VND like quotes).
"""

from datetime import datetime
from typing import Any

from fireant_crawler.normalize.values import NormalizationError, nfc, to_float

_FUNDAMENTAL_MAP = {
    "sharesOutstanding": "shares_outstanding",
    "freeShares": "free_shares",
    "beta": "beta",
    "dividend": "dividend_vnd",
    "dividendYield": "dividend_yield",
    "marketCap": "market_cap_vnd",
    "low52Week": "low_52w_vnd",
    "high52Week": "high_52w_vnd",
    "priceChange1y": "price_change_1y",
    "avgVolume10d": "avg_volume_10d",
    "avgVolume3m": "avg_volume_3m",
    "pe": "pe",
    "eps": "eps_vnd",
    "sales_TTM": "sales_ttm_vnd",
    "netProfit_TTM": "net_profit_ttm_vnd",
    "insiderOwnership": "insider_ownership",
    "institutionOwnership": "institution_ownership",
    "foreignOwnership": "foreign_ownership",
}


def normalize_symbol(raw: dict[str, Any], fetched_at: datetime, source: str) -> dict[str, Any]:
    symbol = raw.get("symbol")
    if not symbol:
        raise NormalizationError(f"Symbol payload without symbol: {raw!r:.200}")
    return {
        "symbol": str(symbol).upper(),
        "fetched_at": fetched_at,
        "name": nfc(raw.get("name")),
        "exchange": raw.get("exchange"),
        "type": raw.get("type"),
        "is_listing": raw.get("isListing"),
        "industry_code": raw.get("industryCode"),
        "icb_code": raw.get("icbCode"),
        "source": source,
    }


def normalize_fundamental(symbol: str, raw: dict[str, Any], fetched_at: datetime) -> dict[str, Any]:
    row: dict[str, Any] = {"symbol": symbol.upper(), "fetched_at": fetched_at, "company_type": raw.get("companyType")}
    row.update({column: to_float(raw.get(key)) for key, column in _FUNDAMENTAL_MAP.items()})
    return row


def normalize_icb(rows: list[dict[str, Any]], fetched_at: datetime) -> list[dict[str, Any]]:
    return [
        {
            "industry_code": str(r["industryCode"]),
            "level": r.get("level"),
            "name": nfc(r.get("name")),
            "description": nfc(r.get("description")),
            "fetched_at": fetched_at,
        }
        for r in rows
    ]
