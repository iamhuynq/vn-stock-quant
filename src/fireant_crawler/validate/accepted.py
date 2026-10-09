"""Reviewed exceptions for error-level validation checks.

An error-level finding stops the daily pipeline before `quant build`. A finding that was investigated and
accepted is listed here with its reason; the key is the first column of the check's offending row
(usually a date), as text. Add entries only after looking at the data, never to silence a check.
"""

ACCEPTED: dict[str, dict[str, str]] = {
    # check name: {first-column value: reason}
    "recent_corrupt_source_dates": {
        "2025-07-16": "source-wide volume corruption, flagged in daily_panel.bad_source_date and excluded "
                      "from every universe (docs/data-dictionary.md)",
    },
}
