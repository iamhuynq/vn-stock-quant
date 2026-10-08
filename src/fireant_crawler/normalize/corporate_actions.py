"""events/search rows -> corporate_actions rows.

FireAnt field names are shifted relative to their usual meaning (verified on VOS 2026-10-01):
  recordDate       -> ex_date       (ngay giao dich khong huong quyen, KHQ)
  registrationDate -> record_date   (ngay chot danh sach)
  executionDate    -> payment_date  (ngay thuc hien; null for ~9% of events)
"""

import re
from datetime import datetime
from typing import Any

from fireant_crawler.normalize.values import NormalizationError, nfc, parse_date, parse_vn_number

TYPE_NAMES = {1: "cash_dividend", 2: "stock_dividend", 3: "rights_issue"}

_NUM = r"[0-9.,e+\-]*"
_PERIOD = r"Cổ tức (?:đợt (?P<installment>\d*)/(?P<year_a>\d*)|năm (?P<year_b>\d*))"
_PATTERNS = {
    1: re.compile(rf"^{_PERIOD} bằng tiền, tỷ lệ (?P<cash>{_NUM})đ/CP$"),
    2: re.compile(rf"^{_PERIOD} bằng cổ phiếu, tỷ lệ (?P<held>{_NUM}):(?P<received>{_NUM})$"),
    3: re.compile(rf"^Phát hành CP cho CĐHH, tỷ lệ (?P<held>{_NUM}):(?P<received>{_NUM}), giá (?P<price>{_NUM})đ/CP$"),
}


def _int_or_none(text: str | None) -> int | None:
    return int(text) if text else None


def _parse_title(event_type: int, title: str) -> dict[str, Any]:
    parsed: dict[str, Any] = {
        "period_year": None, "installment": None, "cash_per_share_vnd": None,
        "ratio_held": None, "ratio_received": None, "issue_price_vnd": None, "title_parsed": False,
    }
    pattern = _PATTERNS.get(event_type)
    match = pattern.match(title) if pattern else None
    if not match:
        return parsed
    groups = match.groupdict()
    parsed["title_parsed"] = True
    parsed["period_year"] = _int_or_none(groups.get("year_a") or groups.get("year_b"))
    parsed["installment"] = _int_or_none(groups.get("installment"))
    parsed["cash_per_share_vnd"] = parse_vn_number(groups.get("cash"))
    parsed["ratio_held"] = parse_vn_number(groups.get("held"))
    parsed["ratio_received"] = parse_vn_number(groups.get("received"))
    parsed["issue_price_vnd"] = parse_vn_number(groups.get("price"))
    return parsed


def normalize_corporate_actions(rows: list[dict[str, Any]], fetched_at: datetime) -> list[dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for raw in rows:
        event_id = raw.get("eventID")
        if not isinstance(event_id, int):
            raise NormalizationError(f"Event without integer eventID: {raw!r:.200}")
        event_type = raw.get("type")
        title = nfc(raw.get("title")) or ""
        out[event_id] = {
            "event_id": event_id,
            "symbol": str(raw.get("symbol") or "").upper(),
            "company_name": nfc(raw.get("name")),
            "event_type": event_type,
            "event_type_name": TYPE_NAMES.get(event_type, "unknown"),
            "title": title,
            "ex_date": parse_date(raw.get("recordDate")),
            "record_date": parse_date(raw.get("registrationDate")),
            "payment_date": parse_date(raw.get("executionDate")),
            **_parse_title(event_type, title),
            "fetched_at": fetched_at,
        }
    return [out[k] for k in sorted(out)]
