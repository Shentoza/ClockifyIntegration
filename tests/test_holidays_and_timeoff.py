"""Tests for extract_holiday_dates and calculate_time_off_days.

Both functions handle absences that reduce the target hours:
- extract_holiday_dates: parses Clockify holiday API objects
- calculate_time_off_days: sums approved time-off requests as working days
"""
import sys
import os
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from custom_components.clockify_overtime.calculations import (
    calculate_time_off_days,
    extract_holiday_dates,
)

WORKDAYS_MON_FRI = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY"]

# Calendar week 2025-01-06 (Mon) – 2025-01-12 (Sun) — used throughout these tests
WEEK_MON = date(2025, 1, 6)   # Monday
WEEK_TUE = date(2025, 1, 7)   # Tuesday
WEEK_WED = date(2025, 1, 8)   # Wednesday
WEEK_SAT = date(2025, 1, 11)  # Saturday
WEEK_SUN = date(2025, 1, 12)  # Sunday

# Same dates as ISO strings (for building Clockify API fixture objects)
S_MON = WEEK_MON.isoformat()  # "2025-01-06"
S_TUE = WEEK_TUE.isoformat()  # "2025-01-07"
S_WED = WEEK_WED.isoformat()  # "2025-01-08"
S_SAT = WEEK_SAT.isoformat()  # "2025-01-11"
S_SUN = WEEK_SUN.isoformat()  # "2025-01-12"


# ---------------------------------------------------------------------------
# extract_holiday_dates
# ---------------------------------------------------------------------------


def test_extract_holiday_dates_empty():
    # SPEC: The Clockify free plan returns an empty list for holidays.
    # The integration must handle this gracefully — an empty list means
    # no holidays to deduct, not an error.
    assert extract_holiday_dates([]) == set()


def test_extract_holiday_dates_single_day():
    # SPEC: Clockify always uses a date range in the API response, even for
    # single-day holidays (startDate == endDate).  The result must be a set with
    # exactly one date so the day-by-day target lookup can find it.
    holidays = [{"datePeriod": {"startDate": S_MON, "endDate": S_MON}}]
    assert extract_holiday_dates(holidays) == {WEEK_MON}


def test_extract_holiday_dates_range():
    # SPEC: Multi-day holidays (e.g. Easter, Christmas) are stored as a single
    # range in Clockify but must be expanded into individual dates.  The target
    # calculation checks each date individually, so every date in the range
    # must appear in the returned set.
    holidays = [{"datePeriod": {"startDate": S_MON, "endDate": S_WED}}]  # Mon–Wed
    result = extract_holiday_dates(holidays)
    assert result == {WEEK_MON, WEEK_TUE, WEEK_WED}


def test_extract_holiday_dates_missing_start():
    # SPEC: Malformed or partially populated API responses must not crash the
    # integration.  An entry without a 'startDate' key is silently skipped.
    holidays = [{"datePeriod": {"endDate": S_MON}}]
    assert extract_holiday_dates(holidays) == set()


# ---------------------------------------------------------------------------
# calculate_time_off_days
# ---------------------------------------------------------------------------


def _request(start: str, end: str, half_day: bool = False) -> dict:
    """Helper to build a minimal Clockify time-off request object."""
    return {
        "timeOffPeriod": {
            "period": {"start": start, "end": end},
            "halfDay": half_day,
        }
    }


def test_calculate_time_off_days_empty():
    # SPEC: The Clockify free plan returns an empty list for time-off requests.
    # No approved leave → nothing is deducted from the target hours.
    assert calculate_time_off_days([], WORKDAYS_MON_FRI, set()) == 0.0


def test_calculate_time_off_days_full_day_workday():
    # SPEC: An APPROVED full-day leave request on a working day must reduce
    # the target by exactly 1.0 day.  The overtime balance must not go negative
    # just because the user took an approved vacation day.
    assert calculate_time_off_days(
        [_request(S_MON, S_MON)], WORKDAYS_MON_FRI, set()  # single Monday
    ) == 1.0


def test_calculate_time_off_days_half_day():
    # SPEC: Clockify supports half-day leave requests.  A half-day must reduce
    # the target by 0.5, not 1.0 — so the other half of the day still counts
    # toward the expected hours.
    assert calculate_time_off_days(
        [_request(S_MON, S_MON, half_day=True)], WORKDAYS_MON_FRI, set()  # Monday, half
    ) == 0.5


def test_calculate_time_off_days_weekend_only():
    # SPEC: Time-off that spans only weekend days must not deduct anything.
    # Saturday and Sunday are already outside the contracted working days,
    # so they contribute 0 to both actual and target hours.
    assert calculate_time_off_days(
        [_request(S_SAT, S_SUN)], WORKDAYS_MON_FRI, set()  # Sat–Sun only
    ) == 0.0


def test_calculate_time_off_days_overlaps_holiday():
    # SPEC: When a leave request overlaps a public holiday, the holiday day
    # must NOT be counted as a leave day — it was already deducted from the
    # target by extract_holiday_dates.  Counting it again would double-deduct
    # and artificially inflate the overtime balance.
    # Mon–Wed leave, but Wed (2025-01-08) is also a holiday → only 2 days.
    holiday = {WEEK_WED}
    assert calculate_time_off_days(
        [_request(S_MON, S_WED)], WORKDAYS_MON_FRI, holiday  # Mon–Wed, Wed = holiday
    ) == 2.0
