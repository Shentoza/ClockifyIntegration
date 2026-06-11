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
    split_time_off_days,
    _iso_to_local_date,
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


def test_calculate_time_off_days_clamps_to_period_start():
    # SPEC: A leave request that starts BEFORE the tracking start date must only
    # count working days that fall within the tracking period.  Clockify returns
    # requests that *overlap* the query window, not only those that start inside
    # it, so without clamping the same leave days would be counted twice —
    # once outside the period (where no target was accrued) and once inside.
    # This was the root cause of the 128 h vs 160 h discrepancy:
    # leave ran 2026-03-25 – 2026-04-09 but tracking started 2026-04-01,
    # so only the Apr 1–9 portion must be deducted.
    #
    # Request spans the full week Mon–Sun but tracking only starts Wed.
    period_start = WEEK_WED  # tracking starts Wednesday
    period_end = WEEK_SUN    # end of the same week
    assert calculate_time_off_days(
        [_request(S_MON, S_SUN)],   # leave starts Monday (before tracking)
        WORKDAYS_MON_FRI,
        set(),
        period_start=period_start,
        period_end=period_end,
    ) == 3.0  # only Wed, Thu, Fri count (Mon–Tue precede tracking start)


def test_calculate_time_off_days_half_day_with_holiday_same_day():
    # SPEC: When a half-day leave request falls on the same day as a public
    # holiday, the day must count as 0 leave days — NOT 0.5.  The holiday
    # already removes the full day from the target via extract_holiday_dates;
    # counting 0.5 days of leave on top would double-deduct and artificially
    # inflate the overtime balance.
    holiday = {WEEK_MON}
    assert calculate_time_off_days(
        [_request(S_MON, S_MON, half_day=True)],
        WORKDAYS_MON_FRI,
        holiday,
    ) == 0.0  # Mon is holiday; leave cannot stack on it


def test_split_time_off_days_multiday_leave_windowing():
    # SPEC: A multi-day sick leave must be split into stable buckets:
    # past days [start..today-1], today-only, and total [start..today].
    # This avoids subtraction-based drift in coordinator target assembly.
    requests = [_request(S_TUE, S_SUN)]

    past_days, today_days, total_days = split_time_off_days(
        requests,
        WORKDAYS_MON_FRI,
        set(),
        period_start=WEEK_MON,
        today=WEEK_WED,
    )

    assert past_days == 1.0  # Tuesday
    assert today_days == 1.0  # Wednesday
    assert total_days == 2.0  # Tuesday + Wednesday


def test_split_time_off_days_today_is_period_start():
    # SPEC: If tracking starts today, past_days must be 0 and all approved
    # leave for today appears only in today_days and total_days.
    requests = [_request(S_WED, S_WED)]

    past_days, today_days, total_days = split_time_off_days(
        requests,
        WORKDAYS_MON_FRI,
        set(),
        period_start=WEEK_WED,
        today=WEEK_WED,
    )

    assert past_days == 0.0
    assert today_days == 1.0
    assert total_days == 1.0


def test_calculate_time_off_days_plain_date_strings():
    # SPEC: When time-off requests use plain date strings (ISO format without
    # time component), they must be parsed correctly without timezone handling.
    # This is the baseline case that must work everywhere.
    requests = [_request("2026-06-08", "2026-06-08", half_day=False)]
    assert calculate_time_off_days(
        requests, WORKDAYS_MON_FRI, set()
    ) == 1.0


def test_calculate_time_off_days_utc_datetime_without_timezone_param():
    # SPEC: When Clockify sends a UTC datetime string without a configured
    # timezone_name in the integration, the UTC date is used directly.
    # This matches the default behavior (timezone_name=None).
    requests = [
        _request("2026-06-08T22:00:00Z", "2026-06-09T21:59:59Z", half_day=False)
    ]
    # UTC interpretation: 22:00 UTC June 8 to 21:59 UTC June 9 spans both dates
    assert (
        calculate_time_off_days(requests, WORKDAYS_MON_FRI, set(), timezone_name=None)
        == 2.0
    )


def test_iso_to_local_date_plain_date_string():
    # SPEC: Plain date strings (no time component) must be parsed correctly
    # regardless of timezone_name setting (timezone is ignored for dates).
    assert _iso_to_local_date("2026-06-08", None) == date(2026, 6, 8)
    assert _iso_to_local_date("2026-06-08", "UTC") == date(2026, 6, 8)


def test_iso_to_local_date_utc_datetime_no_timezone():
    # SPEC: UTC datetime strings without a timezone_name are converted using UTC.
    # 22:00 UTC on June 8 is still June 8 in UTC.
    assert _iso_to_local_date("2026-06-08T22:00:00Z", None) == date(2026, 6, 8)


def test_iso_to_local_date_utc_datetime_with_utc_timezone():
    # SPEC: Explicitly passing timezone_name="UTC" produces the same result as
    # timezone_name=None (both use UTC), ensuring consistent behavior.
    assert (
        _iso_to_local_date("2026-06-08T22:00:00Z", "UTC") == date(2026, 6, 8)
    )

