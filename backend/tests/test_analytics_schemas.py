from datetime import UTC, date, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.analytics.schemas import AnalyticsPeriodQuery


def test_analytics_period_defaults_to_thirty_inclusive_utc_days() -> None:
    period = AnalyticsPeriodQuery()

    assert period.start_date is not None
    assert period.end_date is not None
    assert period.end_date == datetime.now(UTC).date()
    assert (period.end_date - period.start_date).days == 29


def test_analytics_period_uses_explicit_end_as_default_window_anchor() -> None:
    period = AnalyticsPeriodQuery(end_date=date(2026, 7, 17))

    assert period.start_date == date(2026, 6, 18)
    assert period.end_date == date(2026, 7, 17)


def test_analytics_period_uses_today_when_only_start_is_given() -> None:
    start = datetime.now(UTC).date() - timedelta(days=5)
    period = AnalyticsPeriodQuery(start_date=start)

    assert period.start_date == start
    assert period.end_date == datetime.now(UTC).date()


@pytest.mark.parametrize(
    ("start_date", "end_date"),
    [
        (date(2026, 7, 18), date(2026, 7, 17)),
        (date(2025, 7, 16), date(2026, 7, 17)),
    ],
)
def test_analytics_period_rejects_reverse_or_overlong_range(
    start_date: date,
    end_date: date,
) -> None:
    with pytest.raises(ValidationError):
        AnalyticsPeriodQuery(start_date=start_date, end_date=end_date)
