"""Raw envelope -> warehouse. Shared by live jobs and the `normalize` rebuild, so both stay identical."""

import re
from datetime import datetime
from typing import Any

from fireant_crawler.normalize.corporate_actions import normalize_corporate_actions
from fireant_crawler.normalize.quotes import adj_ratio_segments, normalize_quotes
from fireant_crawler.normalize.reference import normalize_fundamental, normalize_icb, normalize_symbol
from fireant_crawler.normalize.report_marks import normalize_report_marks
from fireant_crawler.normalize.values import NormalizationError
from fireant_crawler.store.warehouse import Warehouse

INGESTED_JOBS = ("universe", "corporate_actions", "quotes", "report_marks", "fundamental", "icb")
_SYMBOL_PATH = re.compile(r"^/symbols/([A-Za-z0-9-]+)$")


def _as_list(data: Any, job: str) -> list[dict[str, Any]]:
    if not isinstance(data, list):
        raise NormalizationError(f"{job}: expected a list payload, got {type(data).__name__}")
    return data


def ingest(warehouse: Warehouse, job: str, key: str, envelope: dict[str, Any]) -> int:
    """Upsert one raw response. Returns the number of primary rows written."""
    fetched_at = datetime.fromisoformat(envelope["fetched_at"])
    data = envelope["data"]
    path = envelope["request"]["path"]

    if job == "quotes":
        quotes = normalize_quotes(key, _as_list(data, job), fetched_at)
        warehouse.upsert("adj_ratio_segments", adj_ratio_segments(quotes, fetched_at))
        return warehouse.upsert("quotes_daily", quotes)
    if job == "corporate_actions":
        return warehouse.upsert("corporate_actions", normalize_corporate_actions(_as_list(data, job), fetched_at))
    if job == "report_marks":
        return warehouse.upsert("report_marks", normalize_report_marks(key, _as_list(data, job), fetched_at))
    if job == "fundamental":
        if not isinstance(data, dict):
            raise NormalizationError(f"fundamental {key}: expected an object payload")
        return warehouse.upsert("fundamental_snapshots", [normalize_fundamental(key, data, fetched_at)])
    if job == "icb":
        return warehouse.upsert("icb_industries", normalize_icb(_as_list(data, job), fetched_at))
    if job == "universe":
        if path == "/symbols/search":
            rows = [normalize_symbol(r, fetched_at, source="search") for r in _as_list(data, job)]
            return warehouse.upsert("symbols", rows)
        if _SYMBOL_PATH.match(path) and isinstance(data, dict):
            return warehouse.upsert("symbols", [normalize_symbol(data, fetched_at, source="symbol")])
        return 0  # /instruments is kept raw only, as a cross-check
    raise ValueError(f"No ingest rule for job {job!r}")
