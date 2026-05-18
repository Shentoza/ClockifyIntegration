"""Clockify Overtime Tracker — integration setup and DataUpdateCoordinator."""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ClockifyApi, ClockifyApiError
from .const import (
    CONF_API_KEY,
    CONF_CORRECTION_HOURS,
    CONF_EXCLUDED_PROJECT_IDS,
    CONF_HOURS_PER_DAY,
    CONF_SCAN_INTERVAL,
    CONF_START_DATE,
    CONF_TRACKING_MODE,
    DEFAULT_CORRECTION_HOURS,
    DEFAULT_HOURS_PER_DAY,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TRACKING_MODE,
    DEFAULT_WORKING_DAYS,
    DOMAIN,
    PLATFORMS,
    TRACKING_MODE_BILLABLE,
    WEEKDAY_MAP,
)

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# HA integration lifecycle
# ---------------------------------------------------------------------------


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Clockify Overtime domain (YAML bootstrap — no-op)."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a config entry: create API client, coordinator, forward to platforms."""
    hass.data.setdefault(DOMAIN, {})

    session = async_get_clientsession(hass)
    api = ClockifyApi(entry.data[CONF_API_KEY], session)

    try:
        user_info = await api.get_user_info()
    except ClockifyApiError as err:
        _LOGGER.error("Cannot connect to Clockify: %s", err)
        return False

    coordinator = ClockifyOvertimeCoordinator(hass, api, entry, user_info)
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "user_info": user_info,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Reload integration when user saves new options
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the integration whenever the options flow saves new values."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry and clean up."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


# ---------------------------------------------------------------------------
# DataUpdateCoordinator
# ---------------------------------------------------------------------------


class ClockifyOvertimeCoordinator(DataUpdateCoordinator):
    """Fetches data from Clockify and computes overtime balance."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: ClockifyApi,
        entry: ConfigEntry,
        user_info: dict[str, Any],
    ) -> None:
        self.api = api
        self.entry = entry
        self.user_info = user_info
        self._workspace_id: str = user_info.get("defaultWorkspace", "")
        # Cached after first successful load
        self._workspace_working_days: list[str] = []

        scan_interval = int(_opt(entry, CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=scan_interval),
        )

    # ------------------------------------------------------------------

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self._fetch_and_compute()
        except ClockifyApiError as err:
            raise UpdateFailed(f"Clockify API error: {err}") from err

    async def _fetch_and_compute(self) -> dict[str, Any]:
        # 1. Load workspace working-days once (cached)
        if not self._workspace_working_days:
            workspaces = await self.api.get_workspaces()
            for ws in workspaces:
                if ws["id"] == self._workspace_id:
                    settings = ws.get("workspaceSettings", {})
                    self._workspace_working_days = settings.get(
                        "workingDays", DEFAULT_WORKING_DAYS
                    )
                    break
            if not self._workspace_working_days:
                self._workspace_working_days = list(DEFAULT_WORKING_DAYS)

        # 2. Read config (options override entry.data)
        start_date_str: str = _opt(self.entry, CONF_START_DATE, "")
        hours_per_day: float = float(_opt(self.entry, CONF_HOURS_PER_DAY, DEFAULT_HOURS_PER_DAY))
        tracking_mode: str = _opt(self.entry, CONF_TRACKING_MODE, DEFAULT_TRACKING_MODE)
        excluded_ids: list[str] = _opt(self.entry, CONF_EXCLUDED_PROJECT_IDS, [])
        correction_hours: float = float(
            _opt(self.entry, CONF_CORRECTION_HOURS, DEFAULT_CORRECTION_HOURS)
        )

        # 3. Build date range (start_date → now UTC)
        start_date = date.fromisoformat(start_date_str)
        today = datetime.now(timezone.utc).date()
        start_str = f"{start_date.isoformat()}T00:00:00Z"
        end_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        user_id = self.user_info["id"]

        # 4. Fetch time entries (all pages)
        entries = await self.api.get_time_entries(
            self._workspace_id, user_id, start_str, end_str
        )

        # 5. Fetch holidays (optional, free plan returns [])
        holidays = await self.api.get_holidays_in_period(
            self._workspace_id, user_id, start_str, end_str
        )
        holiday_dates = _extract_holiday_dates(holidays)

        # 5b. Fetch approved time-off requests (optional, free plan returns [])
        time_off_requests = await self.api.get_time_off_requests(
            self._workspace_id, user_id, start_str, end_str
        )
        time_off_days = _calculate_time_off_days(
            time_off_requests, self._workspace_working_days, holiday_dates
        )

        # 6. Compute hours
        actual_seconds = 0.0
        billable_seconds = 0.0

        for entry in entries:
            # Skip pause/break entries
            if entry.get("type") == "BREAK":
                continue
            duration = _entry_duration_seconds(entry)
            actual_seconds += duration

            # Billable = flagged as billable AND not in the exclusion list
            is_billable = entry.get("billable", False)
            is_excluded = entry.get("projectId") in excluded_ids
            if is_billable and not is_excluded:
                billable_seconds += duration

        actual_hours = round(actual_seconds / 3600, 2)
        billable_hours = round(billable_seconds / 3600, 2)

        # 7. Compute target (Soll-Stunden) minus time-off days
        target_hours = round(
            _calculate_target_hours(
                start_date,
                today,
                hours_per_day,
                self._workspace_working_days,
                holiday_dates,
            )
            - time_off_days * hours_per_day,
            2,
        )

        # 8. Compute balance
        # Base = billable hours when in billable mode, otherwise all actual hours
        base_hours = billable_hours if tracking_mode == TRACKING_MODE_BILLABLE else actual_hours
        balance_hours = round(base_hours - target_hours - correction_hours, 2)

        return {
            "total_hours": actual_hours,
            "billable_hours": billable_hours,
            "target_hours": target_hours,
            "balance_hours": balance_hours,
            "correction_hours": correction_hours,
            "time_off_days": time_off_days,
            "tracking_mode": tracking_mode,
            "start_date": start_date_str,
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }


# ---------------------------------------------------------------------------
# Pure helper functions (no HA / no API dependencies)
# ---------------------------------------------------------------------------


def _opt(entry: ConfigEntry, key: str, default: Any) -> Any:
    """Return options value, falling back to entry.data, then *default*."""
    return entry.options.get(key, entry.data.get(key, default))


def _entry_duration_seconds(entry: dict[str, Any]) -> float:
    """Compute the duration of a time entry in seconds.

    For running timers (no *end*), *now* is used as the end time.
    """
    interval = entry.get("timeInterval", {})
    start_str = interval.get("start")
    if not start_str:
        return 0.0
    start = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
    end_str = interval.get("end")
    end = (
        datetime.fromisoformat(end_str.replace("Z", "+00:00"))
        if end_str
        else datetime.now(timezone.utc)
    )
    return max(0.0, (end - start).total_seconds())


def _calculate_target_hours(
    start: date,
    end: date,
    hours_per_day: float,
    working_days: list[str],
    holiday_dates: set[date],
) -> float:
    """Count working days between *start* and *end* (inclusive) and multiply by *hours_per_day*.

    *working_days* is a list of Clockify day-name strings (e.g. ``["MONDAY", "FRIDAY"]``).
    Days that fall on a holiday are not counted.
    """
    work_day_numbers = {WEEKDAY_MAP[d] for d in working_days if d in WEEKDAY_MAP}
    total_days = 0
    current = start
    while current <= end:
        if current.weekday() in work_day_numbers and current not in holiday_dates:
            total_days += 1
        current += timedelta(days=1)
    return round(total_days * hours_per_day, 2)


def _extract_holiday_dates(holidays: list[dict[str, Any]]) -> set[date]:
    """Flatten holiday date-period objects into a set of individual dates."""
    dates: set[date] = set()
    for h in holidays:
        period = h.get("datePeriod", {})
        start_str = period.get("start")
        if not start_str:
            continue
        start = date.fromisoformat(start_str[:10])
        end_str = period.get("end")
        end = date.fromisoformat(end_str[:10]) if end_str else start
        current = start
        while current <= end:
            dates.add(current)
            current += timedelta(days=1)
    return dates


def _calculate_time_off_days(
    requests: list[dict[str, Any]],
    working_days: list[str],
    holiday_dates: set[date],
) -> float:
    """Return total working days consumed by APPROVED time-off requests.

    For each request the date range is walked day by day, counting only
    days that match the workspace working-day pattern and are not holidays.
    Half-day requests are counted as 0.5 days.
    """
    work_day_numbers = {WEEKDAY_MAP[d] for d in working_days if d in WEEKDAY_MAP}
    total = 0.0
    for req in requests:
        time_off_period = req.get("timeOffPeriod", {})
        period = time_off_period.get("period", {})
        start_str = period.get("start")
        if not start_str:
            continue
        start = date.fromisoformat(start_str[:10])
        end_str = period.get("end")
        end = date.fromisoformat(end_str[:10]) if end_str else start
        is_half_day = time_off_period.get("halfDay", False)

        days = 0
        current = start
        while current <= end:
            if current.weekday() in work_day_numbers and current not in holiday_dates:
                days += 1
            current += timedelta(days=1)

        total += days * 0.5 if is_half_day else days
    return total
