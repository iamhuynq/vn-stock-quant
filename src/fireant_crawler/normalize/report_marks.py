"""timescale-marks rows -> report_marks rows.

Label F: financial report release, title like
  'BCTC quý 2/2019|DT: 414,5 tỷ, +8,4% (vs. Q2/18)|LN: -23,3 tỷ, -3,9% (vs. Q2/18)'
  'BCTC năm 2019|DT: 1.538,7 tỷ, -9,4% (vs. 2018)|LN: 51,1 tỷ, +197,1% (vs. 2018)'
Labels D (cash dividend), S (stock dividend), I (rights issue): corporate-action marks whose details
live in corporate_actions; only the raw title is kept. Securities firms may omit revenue ('DT:  tỷ').
Revenue/profit are in billion VND. The release date is a date without time: treat the
information as usable from the next session to avoid look-ahead bias.
"""

import re
from datetime import datetime
from typing import Any

from fireant_crawler.normalize.values import NormalizationError, nfc, parse_date, parse_vn_number

_HEADER = re.compile(r"^BCTC (?:quý (?P<quarter>[1-4])/(?P<year_q>\d{4})|năm (?P<year_y>\d{4}))$")
_METRIC = re.compile(r"^(?P<key>DT|LN):\s*(?P<value>[-+0-9.,e]*) tỷ(?:, (?P<pct>[-+0-9.,e]+)% \(vs\. [^)]*\))?$")
_METRIC_COLUMNS = {"DT": ("revenue_bn", "revenue_yoy_pct"), "LN": ("profit_bn", "profit_yoy_pct")}
CORPORATE_ACTION_LABELS = frozenset({"D", "S", "I"})


def _parse_financial_title(title: str) -> dict[str, Any]:
    parsed: dict[str, Any] = {
        "period_type": None, "fiscal_year": None, "fiscal_quarter": None,
        "revenue_bn": None, "revenue_yoy_pct": None, "profit_bn": None, "profit_yoy_pct": None,
        "title_parsed": False,
    }
    header, *metrics = title.split("|")
    match = _HEADER.match(header.strip())
    if not match:
        return parsed
    if match["quarter"]:
        parsed.update(period_type="Q", fiscal_year=int(match["year_q"]), fiscal_quarter=int(match["quarter"]))
    else:
        parsed.update(period_type="Y", fiscal_year=int(match["year_y"]))
    for part in metrics:
        metric = _METRIC.match(part.strip())
        if not metric:
            return parsed
        value_col, pct_col = _METRIC_COLUMNS[metric["key"]]
        parsed[value_col] = parse_vn_number(metric["value"])
        parsed[pct_col] = parse_vn_number(metric["pct"])
    parsed["title_parsed"] = True
    return parsed


def normalize_report_marks(symbol: str, rows: list[dict[str, Any]], fetched_at: datetime) -> list[dict[str, Any]]:
    symbol = symbol.upper()
    out: dict[str, dict[str, Any]] = {}
    for raw in rows:
        mark_id = raw.get("id")
        if not mark_id:
            raise NormalizationError(f"{symbol}: timescale mark without id")
        label = raw.get("label")
        title = nfc(raw.get("title")) or ""
        row: dict[str, Any] = {
            "symbol": symbol,
            "mark_id": str(mark_id),
            "label": label,
            "release_date": parse_date(raw.get("date")),
            "title": title,
            **_parse_financial_title(title),
            "fetched_at": fetched_at,
        }
        if label != "F":
            row["title_parsed"] = label in CORPORATE_ACTION_LABELS
        out[row["mark_id"]] = row
    return sorted(out.values(), key=lambda r: (r["release_date"], r["mark_id"]))
