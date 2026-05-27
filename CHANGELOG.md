# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.0] - 2026-05-27

### Added
- You can now add sensors for the working times of this and last week

## [0.2.0] - 2026-05-21

### Added

- Per-project sensors: select any number of projects in the config / options flow and get a dedicated sensor per project showing total hours booked in the tracking period.

## [0.1.0] - 2026-05-21

### Added

- Initial release
- Async Clockify API client (`api.py`) with automatic pagination for all list endpoints
- `DataUpdateCoordinator`-based integration with configurable polling interval
- **Sensors**: Total Hours, Billable Hours, Target Hours, Overtime Balance
- **Number entity**: Correction Hours — adjust the balance without a full reload
- **Service actions**: `adjust_correction_hours` (add/subtract hours) and `reset_correction_hours` (set to zero)
- **Config flow** (2-step wizard): API key validation → tracking settings
- **Options flow**: update any setting at any time via *Settings → Integrations → Configure*
- Tracking modes: *all booked hours* or *billable project hours only*
- Configurable working days, contracted hours per week, and tracking start date
- Project exclusion list: remove specific projects from the billable hours total
- Holiday support via the Clockify holidays API (gracefully falls back to zero on the free plan)
- Time-off / leave support via the Clockify time-off API (gracefully falls back to zero on the free plan); time-off requests are clamped to the tracking period so days before the start date are not counted
- HACS-ready: `hacs.json`, `brand/icon.png`, GitHub Actions CI for HACS Action and Hassfest validation
- German (`de`) and English (`en`) translations
