"""Tests for entry_duration_seconds.

Verifies that Clockify time-entry objects are converted to seconds correctly,
including edge cases like missing start timestamps and zero-length entries.
"""
import sys
import os
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from custom_components.clockify_overtime.calculations import entry_duration_seconds

# A Monday work session used across all tests: Mon 2025-01-06, 08:00–10:00 UTC
MON_START = "2025-01-06T08:00:00Z"  # Monday 08:00 UTC
MON_END   = "2025-01-06T10:00:00Z"  # Monday 10:00 UTC  (2 h = 7 200 s)


def _entry(start: str | None, end: str | None) -> dict:
    """Build a minimal Clockify time-entry object."""
    interval: dict = {}
    if start is not None:
        interval["start"] = start
    if end is not None:
        interval["end"] = end
    return {"timeInterval": interval}


def test_entry_duration_seconds_complete():
    # SPEC: The standard case — a completed entry with both start and end
    # timestamps.  Verifies the conversion from ISO 8601 UTC strings to seconds
    # is arithmetically correct (Mon 08:00 → 10:00 = 7 200 s).
    assert entry_duration_seconds(_entry(MON_START, MON_END)) == 7200.0


def test_entry_duration_seconds_missing_start():
    # SPEC: Clockify may return incomplete entries (e.g. if data was corrupted
    # or partially synced).  An entry without a start timestamp must return 0
    # and must not raise an exception — it is silently ignored in the total.
    assert entry_duration_seconds(_entry(None, MON_END)) == 0.0


def test_entry_duration_seconds_zero_duration():
    # SPEC: A user who clicked start and stop within the same second produces
    # an entry where start == end.  The result must be exactly 0.0, not
    # negative (which would incorrectly reduce the actual hours total).
    assert entry_duration_seconds(_entry(MON_START, MON_START)) == 0.0


def test_entry_duration_seconds_running_timer():
    # SPEC: A running timer (no end timestamp) must use the provided now_utc
    # reference time as the end, making the result fully deterministic.
    # Mon 08:00 → now_utc 10:30 = 2.5 h = 9 000 s.
    now = datetime(2025, 1, 6, 10, 30, 0, tzinfo=timezone.utc)
    assert entry_duration_seconds(_entry(MON_START, None), now_utc=now) == 9000.0
