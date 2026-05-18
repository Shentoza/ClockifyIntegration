"""Tests for entry_duration_seconds.

Verifies that Clockify time-entry objects are converted to seconds correctly,
including edge cases like missing start timestamps and zero-length entries.
Running-timer entries (no end timestamp) are not tested here because they
depend on datetime.now() and are non-deterministic.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from custom_components.clockify_overtime.calculations import entry_duration_seconds


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
    # is arithmetically correct (08:00 → 10:00 = 7200 s).
    assert entry_duration_seconds(_entry("2025-01-06T08:00:00Z", "2025-01-06T10:00:00Z")) == 7200.0


def test_entry_duration_seconds_missing_start():
    # SPEC: Clockify may return incomplete entries (e.g. if data was corrupted
    # or partially synced).  An entry without a start timestamp must return 0
    # and must not raise an exception — it is silently ignored in the total.
    assert entry_duration_seconds(_entry(None, "2025-01-06T10:00:00Z")) == 0.0


def test_entry_duration_seconds_zero_duration():
    # SPEC: A user who clicked start and stop within the same second produces
    # an entry where start == end.  The result must be exactly 0.0, not
    # negative (which would incorrectly reduce the actual hours total).
    assert entry_duration_seconds(_entry("2025-01-06T08:00:00Z", "2025-01-06T08:00:00Z")) == 0.0
