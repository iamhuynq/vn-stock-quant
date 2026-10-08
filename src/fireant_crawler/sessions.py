"""The last session whose data is final: today after 18:00 Vietnam time on a weekday, else the previous weekday.

During and right after trading hours the API may return the session still in progress. Storing such a row
is harmful twice: it is not the closing data, and the per-day update checkpoint would make the evening run
skip the symbol. So the crawler fetches, and the daily scanner scans, only up to this date. Same rule as
target_day() in scripts/daily.sh. Holidays need no special case: a holiday simply has no rows.
"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
FINAL_HOUR = 18


def final_session(now: datetime) -> date:
    local = now.astimezone(VN_TZ) if now.tzinfo else now
    d = local.date() if (local.weekday() < 5 and local.hour >= FINAL_HOUR) else local.date() - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d
