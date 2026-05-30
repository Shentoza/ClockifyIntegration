"""Tests for calculate_target_hours.

Verifies that expected working hours are counted correctly across date ranges,
taking into account working-day configuration and public holidays.
"""
import sys
import os
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from custom_components.clockify_overtime.calculations import calculate_target_hours

WORKDAYS_MON_FRI = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY"]
WORKDAYS_MON_THU = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY"]

# A concrete calendar week used across all tests: 2025-01-06 (Mon) – 2025-01-12 (Sun)
WEEK_MON = date(2025, 1, 6)   # Monday
WEEK_TUE = date(2025, 1, 7)   # Tuesday
WEEK_WED = date(2025, 1, 8)   # Wednesday
WEEK_THU = date(2025, 1, 9)   # Thursday
WEEK_FRI = date(2025, 1, 10)  # Friday
WEEK_SAT = date(2025, 1, 11)  # Saturday
WEEK_SUN = date(2025, 1, 12)  # Sunday


def test_calculate_target_hours_basic():
    # SPEC: The simplest case — one full working week, constant 40 h contract.
    # Verifies that the per-day rate (40 h / 5 days = 8 h) is applied correctly
    # and that start and end dates are both INCLUSIVE.
    result = calculate_target_hours(
        WEEK_MON, WEEK_FRI, 40.0, WORKDAYS_MON_FRI, set()
    )
    assert result == 40.0


def test_calculate_target_hours_with_holiday_on_workday():
    # SPEC: Public holidays on working days must reduce the target — the user
    # cannot be expected to have worked on a statutory holiday.
    # Wed 2025-01-08 is treated as a holiday → only 4 billable days that week.
    holiday = {WEEK_WED}
    result = calculate_target_hours(
        WEEK_MON, WEEK_FRI, 40.0, WORKDAYS_MON_FRI, holiday
    )
    assert result == 32.0


def test_calculate_target_hours_holiday_on_weekend():
    # SPEC: A public holiday that falls on a weekend must NOT reduce the target.
    # Saturday is already outside the working-day config; counting it twice would
    # incorrectly inflate the overtime balance.
    holiday = {WEEK_SAT}
    result = calculate_target_hours(
        WEEK_MON, WEEK_SUN, 40.0, WORKDAYS_MON_FRI, holiday
    )
    assert result == 40.0


def test_calculate_target_hours_four_day_week():
    # SPEC: The daily rate must be derived from the configured working days, not
    # hardcoded to 5.  A user contracted Mon–Thu at 32 h/week works 8 h/day —
    # the same daily rate as a 40 h/5-day contract.
    result = calculate_target_hours(
        WEEK_MON, WEEK_THU, 32.0, WORKDAYS_MON_THU, set()
    )
    assert result == 32.0


def test_calculate_target_hours_deducts_time_off_days():
    # SPEC: Approved time-off days are deducted from the target at the
    # hours-per-day rate (hours_per_week / num_working_days).  One leave day on
    # a standard 40 h / 5-day contract must reduce the target by exactly 8 h.
    result = calculate_target_hours(
        WEEK_MON, WEEK_FRI, 40.0, WORKDAYS_MON_FRI, set(), time_off_days=1.0
    )
    assert result == 32.0


def test_calculate_target_hours_half_day_timeoff_reduces_by_half_day():
    # SPEC: A half-day of approved leave (time_off_days=0.5) must reduce the
    # target by exactly hours_per_day / 2.  On a 40 h / 5-day contract that is
    # 4 h — not a full 8 h day — so the user must still work the other half.
    result = calculate_target_hours(
        WEEK_MON, WEEK_FRI, 40.0, WORKDAYS_MON_FRI, set(), time_off_days=0.5
    )
    assert result == 36.0


# ---------------------------------------------------------------------------
# Progressive today tests
# ---------------------------------------------------------------------------
# All tests below use WEEK_MON..WEEK_FRI as the period.
# today = WEEK_FRI (end date); Mon–Thu are full working days.
# hours_per_day = 40 h / 5 days = 8 h/day; 4 past days = 32 h before today.


def test_progressive_today_no_hours_tracked():
    # SPEC: When the current day is a working day but no hours have been
    # tracked yet, today must contribute 0 h to the target.  This prevents
    # the overnight "overtime drop" where the balance falls by a full
    # hours_per_day at midnight before any work has been recorded.
    result = calculate_target_hours(
        WEEK_MON, WEEK_FRI, 40.0, WORKDAYS_MON_FRI, set(),
        today_actual_hours=0.0,
    )
    assert result == 32.0  # Mon-Thu only; Fri contributes 0


def test_progressive_today_partial_hours():
    # SPEC: When fewer hours have been tracked today than the daily
    # requirement, today's contribution to the target equals the hours
    # actually tracked.  The balance stays at 0 — no deficit accumulates
    # during an in-progress working day.
    result = calculate_target_hours(
        WEEK_MON, WEEK_FRI, 40.0, WORKDAYS_MON_FRI, set(),
        today_actual_hours=5.0,
    )
    assert result == 37.0  # 32 h (Mon-Thu) + 5 h (today so far)


def test_progressive_today_exactly_full_hours():
    # SPEC: When exactly the daily requirement has been tracked today,
    # today's contribution equals hours_per_day — identical to the
    # non-progressive result.  The balance is 0 (no overtime, no deficit).
    result = calculate_target_hours(
        WEEK_MON, WEEK_FRI, 40.0, WORKDAYS_MON_FRI, set(),
        today_actual_hours=8.0,
    )
    assert result == 40.0  # 32 h + 8 h = full week target


def test_progressive_today_overtime():
    # SPEC: When more than hours_per_day have been tracked today (e.g. 9 h
    # on an 8 h day), today's target contribution is capped at hours_per_day.
    # The overtime (1 h) appears in the balance, not in the target.
    result = calculate_target_hours(
        WEEK_MON, WEEK_FRI, 40.0, WORKDAYS_MON_FRI, set(),
        today_actual_hours=9.0,
    )
    assert result == 40.0  # cap at 8 h; the extra 1 h shows as overtime


def test_progressive_today_half_day_timeoff_cap():
    # SPEC: When a half-day off is taken today (today_time_off_days=0.5),
    # the effective daily cap is halved (4 h for an 8 h/day contract).
    # Working more than 4 h generates overtime; working less generates no
    # deficit.  The global time_off_days subtraction excludes today's
    # time-off (caller responsibility) so there is no double-deduction.
    # today_actual=5 h > cap=4 h → today contributes 4 h → balance = +1 h.
    result = calculate_target_hours(
        WEEK_MON, WEEK_FRI, 40.0, WORKDAYS_MON_FRI, set(),
        time_off_days=0.0,  # today's time-off already excluded from global
        today_actual_hours=5.0,
        today_time_off_days=0.5,
    )
    assert result == 36.0  # 32 h (Mon-Thu) + 4 h (today capped at half-day)


def test_progressive_today_no_contribution_on_holiday():
    # SPEC: When today is a public holiday it is already excluded from the
    # target.  Passing today_actual_hours must not add any hours for a
    # holiday — the progressive logic only activates for working days.
    result = calculate_target_hours(
        WEEK_MON, WEEK_FRI, 40.0, WORKDAYS_MON_FRI, {WEEK_FRI},
        today_actual_hours=8.0,
    )
    assert result == 32.0  # Fri is holiday; even 8 h tracked adds nothing
