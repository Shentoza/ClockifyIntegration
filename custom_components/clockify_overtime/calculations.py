"""Pure calculation helpers — no Home Assistant or API dependencies.

All functions in this module are free of side-effects and have no
dependency on the Home Assistant framework, making them trivially
unit-testable with plain pytest.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

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
    time_off_days: float = 0.0,
    today_actual_hours: float | None = None,
    today_time_off_days: float = 0.0,
    current_date: date | None = None,
) -> float:
    """Return expected (target) hours from *start* to *end* inclusive.

    *hours_per_week* is the contracted weekly hours applied uniformly across
    the entire period.  Use the correction entity to compensate for any
    mid-period contract changes.

    *working_days* is a list of Clockify weekday-name strings such as
    ``["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY"]``.

    Days that are in *holiday_dates* or that fall outside *working_days*
    are not counted towards the target.

    *time_off_days* approved leave days are deducted from the target using
    the same *hours_per_day* rate, preventing double-deduction with holidays.
    Must NOT include any time-off that falls on *end* when *today_actual_hours*
    is provided, because today's time-off is handled via *today_time_off_days*.

    *today_actual_hours* enables progressive tracking for the last day of the
    period (*end*) only when it matches *current_date* (today's calendar date).
    Instead of immediately adding the full *hours_per_day* at midnight,
    today's contribution scales with the hours actually tracked so far, capped
    at the effective daily requirement.  Pass the hours that match the active
    tracking mode (total or billable).

    When the date changes (e.g. from Friday to Saturday), *end* no longer matches
    *current_date*, so the previous day automatically becomes a fixed full day.

    *today_time_off_days* is the time-off fraction consumed on *end* today
    (0.0 = none, 0.5 = half-day, 1.0 = full day).  It reduces today's cap so
    a half-day off still generates overtime once the remaining half is exceeded.

    *current_date* (default None) is today's calendar date.  If provided and
    equals *end*, progressive tracking is enabled for that day. Otherwise,
    all days are counted as full working days.
    Use this to automatically disable progressive tracking after midnight
    without needing an explicit cutoff-hour setting.
    """
    work_day_numbers = {WEEKDAY_MAP[d] for d in working_days if d in WEEKDAY_MAP}
    num_work_days_per_week = len(work_day_numbers) or 5  # safety: avoid zero division
    hours_per_day = hours_per_week / num_work_days_per_week
    total_hours = 0.0
    current = start
    while current <= end:
        if current.weekday() in work_day_numbers and current not in holiday_dates:
            # Progressive only if: end is today AND current_date matches end AND hours provided
            if current == end and current == current_date and today_actual_hours is not None:
                # Progressive: target grows with tracked hours, capped at daily requirement
                today_cap = max(0.0, hours_per_day * (1.0 - today_time_off_days))
                total_hours += min(today_actual_hours, today_cap)
            else:
                # Full day: all other dates (past or future)
                total_hours += hours_per_day
        current += timedelta(days=1)
    return round(total_hours - time_off_days * hours_per_day, 2)


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
        start_str = period.get("startDate")
        if not start_str:
            continue
        start = date.fromisoformat(start_str[:10])
        end_str = period.get("endDate")
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
    period_start: date | None = None,
    period_end: date | None = None,
    timezone_name: str | None = None,
) -> float:
    """Return total working days consumed by APPROVED time-off requests.

    For each request the date range is walked day by day, counting only
    days that match *working_days* and are not in *holiday_dates*.
    Half-day requests are counted as 0.5 days.

    *period_start* and *period_end* clamp each request to the tracking
    period.  This prevents requests that overlap the period boundary
    (e.g. leave starting before the tracking start date) from counting
    days that should not reduce the target.
    """
    work_day_numbers = {WEEKDAY_MAP[d] for d in working_days if d in WEEKDAY_MAP}
    total = 0.0
    for req in requests:
        time_off_period = req.get("timeOffPeriod", {})
        period = time_off_period.get("period", {})
        start_str = period.get("start")
        if not start_str:
            continue
        start = _iso_to_local_date(start_str, timezone_name)
        end_str = period.get("end")
        end = _iso_to_local_date(end_str, timezone_name) if end_str else start
        is_half_day = time_off_period.get("halfDay", False)

        # Clamp to the tracking period so pre-period days are not counted
        if period_start:
            start = max(start, period_start)
        if period_end:
            end = min(end, period_end)
        if start > end:
            continue

        days = sum(
            1
            for i in range((end - start).days + 1)
            if (d := start + timedelta(days=i)).weekday() in work_day_numbers
            and d not in holiday_dates
        )
        total += days * 0.5 if is_half_day else days
    return total


def split_time_off_days(
    requests: list[dict[str, Any]],
    working_days: list[str],
    holiday_dates: set[date],
    period_start: date,
    today: date,
    timezone_name: str | None = None,
) -> tuple[float, float, float]:
    """Split approved time-off into past days, today, and total.

    Returns a tuple of ``(past_days, today_days, total_days)`` where:
    - ``past_days`` covers ``[period_start, today-1]``
    - ``today_days`` covers only ``[today, today]``
    - ``total_days`` covers ``[period_start, today]``

    Using explicit windows avoids relying on subtraction (``total - today``),
    which can hide inconsistencies when API responses change during refreshes.
    """
    total_days = calculate_time_off_days(
        requests,
        working_days,
        holiday_dates,
        period_start=period_start,
        period_end=today,
        timezone_name=timezone_name,
    )
    today_days = calculate_time_off_days(
        requests,
        working_days,
        holiday_dates,
        period_start=today,
        period_end=today,
        timezone_name=timezone_name,
    )

    if today <= period_start:
        past_days = 0.0
    else:
        past_days = calculate_time_off_days(
            requests,
            working_days,
            holiday_dates,
            period_start=period_start,
            period_end=today - timedelta(days=1),
            timezone_name=timezone_name,
        )

    return round(past_days, 2), round(today_days, 2), round(total_days, 2)


def _iso_to_local_date(value: str, timezone_name: str | None) -> date:
    """Convert an ISO date/datetime string into a local calendar date.

    Clockify time-off periods can come as UTC datetimes. Converting to the
    Home Assistant timezone avoids day-shift errors around midnight.
    If *timezone_name* is None or fails to resolve, UTC is used.
    """
    if "T" not in value:
        return date.fromisoformat(value[:10])

    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if timezone_name and dt.tzinfo is not None:
        try:
            dt = dt.astimezone(ZoneInfo(timezone_name))
        except Exception:
            # Keep UTC date if timezone lookup fails unexpectedly.
            pass
    return dt.date()


# ---------------------------------------------------------------------------
# Time-entry duration
# ---------------------------------------------------------------------------


def entry_duration_seconds(
    entry: dict[str, Any],
    now_utc: datetime | None = None,
) -> float:
    """Return the duration of a Clockify time entry in seconds.

    For running timers (no *end* timestamp) *now_utc* is used as the end time.
    Pass a fixed datetime in tests to make the result deterministic.
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
        else (now_utc or datetime.now(timezone.utc))
    )
    return max(0.0, (end - start).total_seconds())


def calculate_period_hours(
    entries: list[dict[str, Any]],
    period_start: date,
    period_end: date,
    excluded_project_ids: list[str],
    now_utc: datetime | None = None,
) -> tuple[float, float]:
    """Return total and billable hours for a period, clipped to day boundaries.

    The period is inclusive on both dates and interpreted in UTC.
    Billable hours include only entries marked billable and not excluded via
    *excluded_project_ids*.
    """
    if period_end < period_start:
        return 0.0, 0.0

    start_dt = datetime.combine(period_start, datetime.min.time(), tzinfo=timezone.utc)
    end_exclusive_dt = datetime.combine(
        period_end + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc
    )

    total_seconds = 0.0
    billable_seconds = 0.0
    now_value = now_utc or datetime.now(timezone.utc)

    for entry in entries:
        if entry.get("type") == "BREAK":
            continue

        interval = entry.get("timeInterval", {})
        start_str = interval.get("start")
        if not start_str:
            continue

        entry_start = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
        end_str = interval.get("end")
        entry_end = (
            datetime.fromisoformat(end_str.replace("Z", "+00:00"))
            if end_str
            else now_value
        )

        overlap_start = max(entry_start, start_dt)
        overlap_end = min(entry_end, end_exclusive_dt)
        overlap_seconds = max(0.0, (overlap_end - overlap_start).total_seconds())
        if overlap_seconds <= 0:
            continue

        total_seconds += overlap_seconds
        if entry.get("billable", False) and entry.get("projectId") not in excluded_project_ids:
            billable_seconds += overlap_seconds

    return round(total_seconds / 3600, 2), round(billable_seconds / 3600, 2)
