"""final_session: the last session whose data is final (same rule as daily.sh target_day)."""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from fireant_crawler.sessions import final_session

VN = ZoneInfo("Asia/Ho_Chi_Minh")


@pytest.mark.parametrize("now, expected", [
    (datetime(2026, 10, 5, 10, 0, tzinfo=VN), date(2026, 10, 2)),    # Monday in session -> Friday
    (datetime(2026, 10, 5, 17, 59, tzinfo=VN), date(2026, 10, 2)),
    (datetime(2026, 10, 5, 18, 0, tzinfo=VN), date(2026, 10, 5)),    # Monday evening -> Monday
    (datetime(2026, 10, 6, 9, 0, tzinfo=VN), date(2026, 10, 5)),     # Tuesday morning -> Monday
    (datetime(2026, 10, 10, 20, 0, tzinfo=VN), date(2026, 10, 9)),   # Saturday -> Friday
    (datetime(2026, 10, 11, 23, 0, tzinfo=VN), date(2026, 10, 9)),   # Sunday -> Friday
    (datetime(2026, 10, 5, 11, 30, tzinfo=UTC), date(2026, 10, 5)),  # 18:30 in Vietnam
    (datetime(2026, 10, 5, 10, 59, tzinfo=UTC), date(2026, 10, 2)),  # 17:59 in Vietnam
])
def test_final_session(now, expected):
    assert final_session(now) == expected
