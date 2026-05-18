# Clockify Overtime Tracker — Agent Guidelines

## Architecture

```
custom_components/clockify_overtime/
├── api.py            # Async Clockify HTTP client (no HA logic)
├── calculations.py   # Pure calculation helpers (no HA imports)
├── const.py          # All constants in one place
├── __init__.py       # HA integration lifecycle + DataUpdateCoordinator
├── config_flow.py    # Setup wizard (2-step) + OptionsFlow
├── sensor.py         # Read-only HA sensor entities
└── number.py         # Settable number entity (correction_hours)
tests/
├── conftest.py                  # Stubs homeassistant.* so pytest runs without HA
├── test_json_files.py           # validates all JSON files + translation key coverage
├── test_target_hours.py         # calculate_target_hours
├── test_holidays_and_timeoff.py # extract_holiday_dates, calculate_time_off_days
└── test_time_entries.py         # entry_duration_seconds
```

The key design principle: **`calculations.py` has zero HA dependencies.** All
business logic lives there. `__init__.py` wires HA to those functions; it should
contain as little logic as possible.

## Code Style

**KISS and readability are non-negotiable.** Prefer:
- Descriptive function and variable names over short ones
- Flat code over nested abstractions
- One function, one responsibility
- Explicit over implicit

Avoid:
- Helper abstractions used only once
- Generic wrappers around already-simple operations
- Adding parameters "for future flexibility"

## Build and Test

```bash
# Run all tests (no HA install needed)
pytest tests/

# Syntax-check all integration files
python -m py_compile custom_components/clockify_overtime/*.py

# Restart the local HA dev container after code changes
docker restart ha-dev
```

## Conventions

### Pure functions in `calculations.py`

Every function that computes a value without side effects belongs in
`calculations.py`. The rule: if the function does not import anything from
`homeassistant.*`, it goes there.

When adding a new calculation:
1. Write it in `calculations.py` with a plain Python signature
2. Write a test for it in the appropriate `tests/test_*.py` file
3. Import and call it from `__init__.py`

### Test comments as specifications

Every test function starts with a `# SPEC:` comment. This comment describes the
**business rule** being verified, not the implementation. Write it so that a
future refactoring agent can read it and confirm the behaviour has been preserved
without understanding the implementation details.

Example:
```python
def test_calculate_time_off_days_overlaps_holiday():
    # SPEC: When a leave request overlaps a public holiday, the holiday day
    # must NOT be counted as a leave day — it was already deducted from the
    # target by extract_holiday_dates. Counting it again would double-deduct
    # and artificially inflate the overtime balance.
    ...
```

### Smart reload vs. coordinator refresh

Changing a *structural* setting (scan interval, working days, tracking mode,
start date, hours per week) requires a full integration reload because the
coordinator is reconfigured at startup.

Changing `correction_hours` alone — whether via the number entity or the options
flow — must only trigger `coordinator.async_request_refresh()`. The
`_async_options_updated` listener in `__init__.py` enforces this via
`_structural_snapshot`.

Do not add new config keys to `_structural_snapshot` unless a reload is genuinely
required to apply them.

## AI Disclosure

This integration was developed with **GitHub Copilot** (Claude Sonnet 4.6).
The AI handled code generation, architecture, and documentation. All output was
reviewed for correctness and security.
