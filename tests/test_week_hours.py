"""Tests for calculate_period_hours.

Verifies period-based totals for calendar-week sensors, including clipping at
period boundaries and billable filtering.
"""
import os
import sys
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from custom_components.clockify_overtime.calculations import calculate_period_hours


# Calendar week used in all tests: Mon 2025-01-06 to Sun 2025-01-12
CW2_2025_MON = date(2025, 1, 6)
CW2_2025_SUN = date(2025, 1, 12)

# Boundary-adjacent timestamps used for overlap clipping checks
SUN_BEFORE_CW_START_23 = "2025-01-05T23:00:00Z"
MON_CW_START_01 = "2025-01-06T01:00:00Z"
SUN_CW_END_23 = "2025-01-12T23:00:00Z"
MON_AFTER_CW_END_01 = "2025-01-13T01:00:00Z"

# In-week timestamps used for regular accumulation checks
MON_WORK_START = "2025-01-06T08:00:00Z"
MON_WORK_END_1H = "2025-01-06T09:00:00Z"
MON_WORK_END_2H = "2025-01-06T10:00:00Z"
TUE_WORK_START = "2025-01-07T08:00:00Z"
TUE_WORK_END_3H = "2025-01-07T11:00:00Z"
WED_WORK_START = "2025-01-08T08:00:00Z"
WED_WORK_END_1H = "2025-01-08T09:00:00Z"

# Running timer reference timestamp
MON_NOON_NOW = datetime(2025, 1, 6, 12, 0, 0, tzinfo=timezone.utc)


def _entry(
    start: str | None,
    end: str | None,
    *,
    billable: bool = False,
    project_id: str | None = None,
    entry_type: str = "REGULAR",
) -> dict:
    interval: dict[str, str] = {}
    if start is not None:
        interval["start"] = start
    if end is not None:
        interval["end"] = end
    return {
        "type": entry_type,
        "billable": billable,
        "projectId": project_id,
        "timeInterval": interval,
    }


def test_calculate_period_hours_basic_and_excluded_projects():
    # SPEC: Calendar-week totals must include all overlapping regular entries,
    # while billable totals must include only billable entries not listed in
    # excluded_project_ids.
    entries = [
        _entry(MON_WORK_START, MON_WORK_END_2H, billable=True, project_id="a"),
        _entry(TUE_WORK_START, TUE_WORK_END_3H, billable=True, project_id="skip"),
        _entry(WED_WORK_START, WED_WORK_END_1H, billable=False, project_id="a"),
    ]

    total, billable = calculate_period_hours(
        entries,
        period_start=CW2_2025_MON,
        period_end=CW2_2025_SUN,
        excluded_project_ids=["skip"],
    )

    assert total == 6.0
    assert billable == 2.0


def test_calculate_period_hours_clips_overlapping_entries():
    # SPEC: Entries that overlap the period boundary must be clipped to the
    # in-period part only, otherwise hours from neighboring weeks leak into
    # the current calendar-week sensor.
    entries = [
        _entry(SUN_BEFORE_CW_START_23, MON_CW_START_01, billable=True, project_id="a"),
        _entry(SUN_CW_END_23, MON_AFTER_CW_END_01, billable=True, project_id="a"),
    ]

    total, billable = calculate_period_hours(
        entries,
        period_start=CW2_2025_MON,
        period_end=CW2_2025_SUN,
        excluded_project_ids=[],
    )

    assert total == 2.0
    assert billable == 2.0


def test_calculate_period_hours_ignores_break_and_handles_running_timer():
    # SPEC: Break entries must never count toward totals; running timers with no
    # end timestamp must be counted up to the provided now_utc reference.
    entries = [
        _entry(MON_WORK_START, MON_WORK_END_1H, billable=True, project_id="a", entry_type="BREAK"),
        _entry(MON_WORK_END_2H, None, billable=True, project_id="a"),
        _entry(None, MON_WORK_END_1H, billable=True, project_id="a"),
    ]

    total, billable = calculate_period_hours(
        entries,
        period_start=CW2_2025_MON,
        period_end=CW2_2025_SUN,
        excluded_project_ids=[],
        now_utc=MON_NOON_NOW,
    )

    assert total == 2.0
    assert billable == 2.0
