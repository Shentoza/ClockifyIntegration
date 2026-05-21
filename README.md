# Clockify Overtime Tracker — Home Assistant Integration

This integration connects to the Clockify time-tracking API and computes an overtime balance. It deducts approved time-off requests and public holidays from the expected work hours, so the balance always reflects what you actually owe or are owed.

## Features

- Tracks total and billable hours since a configurable start date
- Calculates target (expected) hours based on weekly contracted hours and working-day schedule
- Deducts approved time-off requests and public holidays from the target
- Settable correction/payout offset directly from the Home Assistant UI (number entity)
- All sensors grouped under one logical device per Clockify user
- Target Hours sensor marked as Diagnostic (hidden from main dashboard)

## Sensors

| Entity | Unit | HA Category | Description |
|---|---|---|---|
| Total Hours | h | (main) | All non-break time entries since start date |
| Billable Hours | h | (main) | Only entries flagged billable and not excluded (billable mode only) |
| Target Hours | h | Diagnostic | Expected hours based on schedule and contracted hours |
| Overtime Balance | h | (main) | Total/Billable hours - Target hours + Correction hours |

## Controls

| Entity | Unit | HA Category | Description |
|---|---|---|---|
| Correction Hours | h | Config | Manual balance adjustment — positive hours are added to the balance, negative hours are subtracted. Adjust without opening integration settings. |

## Setup

1. Copy the `clockify_overtime` folder into your `custom_components/` directory
2. Restart Home Assistant
3. Go to **Settings → Integrations → Add Integration** and search for "Clockify Overtime"
4. **Step 1:** Enter your Clockify API key (found at <https://app.clockify.me/user/settings>)
5. **Step 2:** Configure working days, weekly hours, start date, and tracking mode

## Configuration Reference

| Field | Default | Description |
|---|---|---|
| Tracking mode | All hours | Whether to use all booked hours or only billable project hours for the balance |
| Working days | Mon–Fri | Days of the week you are contracted to work |
| Target hours per week | 40 h | Contracted weekly working hours |
| Tracking start date | today | Date from which overtime is counted |
| Update interval | 30 min | How often the integration polls the Clockify API |
| Projects to exclude | (none) | Projects excluded from the billable hours count |
| Correction / payout offset | 0 h | Manual balance adjustment (see note below) |

> **Note — changing Working Days or Target Hours per Week mid-period:** These settings apply uniformly across the entire tracking period. If you reduce your contracted hours or change your working-day schedule partway through the year, the recalculated target will jump and your balance will shift accordingly. Two options to handle this:
> - **Reset the tracking start date** to the date of the change. The integration then only looks at data from that point forward and the new settings are correct from day one. Any overtime accumulated before the change is lost from the calculation — carry it over manually via the **Correction / payout offset** entity.
> - **Keep the existing start date** and use the **Correction / payout offset** entity to compensate for the recalculation error: enter the difference between what the old settings would have produced and what the new settings calculate for the historical portion.

## Architecture

- **KISS & Readability**: The integration intentionally avoids over-abstraction. Helper functions use descriptive names and are free of side effects.
- **Pure calculation module**: All math lives in `calculations.py` — no HA framework imports. This makes the functions trivially unit-testable with plain `pytest`.
- **Smart reload**: Changing the correction/payout offset via the number entity only triggers a coordinator data-refresh, not a full integration reload. Structural changes (scan interval, working days, target hours, etc.) still trigger a full reload.

## Running Tests

The tests only cover the pure calculation logic in `calculations.py`. They have
no dependency on the Home Assistant framework and run with plain `pytest`.

```bash
# Install pytest once (if not already installed)
pip install pytest

# Run all tests
pytest tests/

# Run a specific test file
pytest tests/test_target_hours.py

# Run with verbose output
pytest tests/ -v
```

### Test files

| File | What it covers |
|---|---|
| `test_target_hours.py` | Expected-hours calculation with holidays and custom working days |
| `test_holidays_and_timeoff.py` | Expanding Clockify holiday ranges; deducting approved time-off requests |
| `test_time_entries.py` | Converting Clockify time-entry objects to seconds |

`tests/conftest.py` stubs out all `homeassistant.*` imports with `MagicMock` so the
package can be imported without a running HA instance or the `homeassistant` pip package.

Each test includes a `# SPEC:` comment that describes the business rule being
verified. These comments are intentionally written as specifications so that a
refactoring pass can use them to validate that behaviour has not changed.

## AI Disclosure

This integration was developed with the assistance of **GitHub Copilot** (powered by **Claude Sonnet 4.6**). The AI was used for code generation, architecture decisions, and documentation. All generated code was reviewed for correctness and security. The project follows the KISS (Keep It Simple, Stupid) principle and prioritises readability over cleverness.
