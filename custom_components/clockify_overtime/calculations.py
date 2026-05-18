"""Pure calculation helpers — no Home Assistant or API dependencies.

All functions in this module are free of side-effects and have no
dependency on the Home Assistant framework, making them trivially
unit-testable with plain pytest.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from .const import WEEKDAY_MAP


# ---------------------------------------------------------------------------
# Target hours
# ---------------------------------------------------------------------------


def calculate_target_hours(
    start: date,
    end: date,
    hours_per_week: float,
    working_days: list[str],
    holiday_dates: set[date],
) -> float:
    """Return expected (target) hours from *start* to *end* inclusive.

    *hours_per_week* is the contracted weekly hours applied uniformly across
    the entire period.  Use the correction entity to compensate for any
    mid-period contract changes.

    *working_days* is a list of Clockify weekday-name strings such as
    ``["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY"]``.

    Days that are in *holiday_dates* or that fall outside *working_days*
    are not counted towards the target.
    """
    work_day_numbers = {WEEKDAY_MAP[d] for d in working_days if d in WEEKDAY_MAP}
    num_work_days_per_week = len(work_day_numbers) or 5  # safety: avoid zero division
    hours_per_day = hours_per_week / num_work_days_per_week
    total_hours = 0.0
    current = start
    while current <= end:
        if current.weekday() in work_day_numbers and current not in holiday_dates:
            total_hours += hours_per_day
        current += timedelta(days=1)
    return round(total_hours, 2)


# ---------------------------------------------------------------------------
# Holiday helpers
# ---------------------------------------------------------------------------


def extract_holiday_dates(holidays: list[dict[str, Any]]) -> set[date]:
    """Flatten Clockify holiday objects into a set of individual dates.

    Each holiday may span multiple days via ``datePeriod.start/end``.
    """
    dates: set[date] = set()
    for h in holidays:
        period = h.get("datePeriod", {})
        start_str = period.get("start")
        if not start_str:
            continue
        start = date.fromisoformat(start_str[:10])
        end_str = period.get("end")
        end = date.fromisoformat(end_str[:10]) if end_str else start
        current = start
        while current <= end:
            dates.add(current)
            current += timedelta(days=1)
    return dates


# ---------------------------------------------------------------------------
# Time-off helpers
# ---------------------------------------------------------------------------


def calculate_time_off_days(
    requests: list[dict[str, Any]],
    working_days: list[str],
    holiday_dates: set[date],
) -> float:
    """Return total working days consumed by APPROVED time-off requests.

    For each request the date range is walked day by day, counting only
    days that match *working_days* and are not in *holiday_dates*.
    Half-day requests are counted as 0.5 days.
    """
    work_day_numbers = {WEEKDAY_MAP[d] for d in working_days if d in WEEKDAY_MAP}
    total = 0.0
    for req in requests:
        time_off_period = req.get("timeOffPeriod", {})
        period = time_off_period.get("period", {})
        start_str = period.get("start")
        if not start_str:
            continue
        start = date.fromisoformat(start_str[:10])
        end_str = period.get("end")
        end = date.fromisoformat(end_str[:10]) if end_str else start
        is_half_day = time_off_period.get("halfDay", False)

        days = sum(
            1
            for i in range((end - start).days + 1)
            if (d := start + timedelta(days=i)).weekday() in work_day_numbers
            and d not in holiday_dates
        )
        total += days * 0.5 if is_half_day else days
    return total


# ---------------------------------------------------------------------------
# Time-entry duration
# ---------------------------------------------------------------------------


def entry_duration_seconds(entry: dict[str, Any]) -> float:
    """Return the duration of a Clockify time entry in seconds.

    For running timers (no *end* timestamp) the current UTC time is used,
    so live timers contribute to the total hours in real time.
    """
    interval = entry.get("timeInterval", {})
    start_str = interval.get("start")
    if not start_str:
        return 0.0
    start = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
    end_str = interval.get("end")
    end = (
        datetime.fromisoformat(end_str.replace("Z", "+00:00"))
        if end_str
        else datetime.now(timezone.utc)
    )
    return max(0.0, (end - start).total_seconds())
