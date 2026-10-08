"""Parsing helpers for FireAnt payloads (Vietnamese number format, ISO date-times)."""

import unicodedata
from datetime import date, datetime


class NormalizationError(ValueError):
    """Raw payload does not match the expected shape; fail loudly instead of guessing."""


def parse_vn_number(text: str | None) -> float | None:
    """'1.100' -> 1100, '1.538,7' -> 1538.7, '-23,3' -> -23.3, '+8,4' -> 8.4, '1e+05' -> 100000."""
    if text is None:
        return None
    s = text.strip()
    if not s:
        return None
    try:
        if "e" in s.lower():
            return float(s.replace(",", "."))
        return float(s.replace(".", "").replace(",", "."))
    except ValueError as exc:
        raise NormalizationError(f"Not a number: {text!r}") from exc


def parse_date(value: str | None) -> date | None:
    """'2026-10-01T00:00:00' -> date(2026, 10, 1). None stays None."""
    if value is None or value == "":
        return None
    try:
        return datetime.fromisoformat(str(value)).date()
    except ValueError as exc:
        raise NormalizationError(f"Not an ISO date: {value!r}") from exc


def to_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise NormalizationError(f"Expected a number, got {value!r}")
    return float(value)


def nfc(text: str | None) -> str | None:
    return unicodedata.normalize("NFC", text) if text is not None else None
