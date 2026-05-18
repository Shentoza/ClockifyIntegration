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


def test_calculate_target_hours_basic():
    # SPEC: The simplest case — one full working week, constant 40 h contract.
    # Verifies that the per-day rate (40 h / 5 days = 8 h) is applied correctly
    # and that start and end dates are both INCLUSIVE.
    result = calculate_target_hours(
        date(2025, 1, 6), date(2025, 1, 10), 40.0, WORKDAYS_MON_FRI, set()
    )
    assert result == 40.0


def test_calculate_target_hours_with_holiday_on_workday():
    # SPEC: Public holidays on working days must reduce the target — the user
    # cannot be expected to have worked on a statutory holiday.
    # Wed 2025-01-08 is treated as a holiday → only 4 billable days that week.
    holiday = {date(2025, 1, 8)}
    result = calculate_target_hours(
        date(2025, 1, 6), date(2025, 1, 10), 40.0, WORKDAYS_MON_FRI, holiday
    )
    assert result == 32.0


def test_calculate_target_hours_holiday_on_weekend():
    # SPEC: A public holiday that falls on a weekend must NOT reduce the target.
    # Saturday is already outside the working-day config; counting it twice would
    # incorrectly inflate the overtime balance.
    holiday = {date(2025, 1, 11)}  # Saturday
    result = calculate_target_hours(
        date(2025, 1, 6), date(2025, 1, 12), 40.0, WORKDAYS_MON_FRI, holiday
    )
    assert result == 40.0


def test_calculate_target_hours_four_day_week():
    # SPEC: The daily rate must be derived from the configured working days, not
    # hardcoded to 5.  A user contracted Mon–Thu at 32 h/week works 8 h/day —
    # the same daily rate as a 40 h/5-day contract.
    result = calculate_target_hours(
        date(2025, 1, 6), date(2025, 1, 9), 32.0, WORKDAYS_MON_THU, set()
    )
    assert result == 32.0
