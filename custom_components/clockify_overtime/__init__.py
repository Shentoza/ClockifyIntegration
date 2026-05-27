"""Clockify Overtime Tracker — integration setup and DataUpdateCoordinator."""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ClockifyApi, ClockifyApiError
from .const import (
    CONF_API_KEY,
    CONF_CORRECTION_HOURS,
    CONF_ENABLE_LAST_WEEK_SENSORS,
    CONF_ENABLE_THIS_WEEK_SENSORS,
    CONF_EXCLUDED_PROJECT_IDS,
    CONF_HOURS_PER_WEEK,
    CONF_PROJECT_SENSOR_IDS,
    CONF_SCAN_INTERVAL,
    CONF_START_DATE,
    CONF_TRACKING_MODE,
    CONF_WORKING_DAYS,
    DEFAULT_CORRECTION_HOURS,
    DEFAULT_ENABLE_LAST_WEEK_SENSORS,
    DEFAULT_ENABLE_THIS_WEEK_SENSORS,
    DEFAULT_HOURS_PER_WEEK,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TRACKING_MODE,
    DEFAULT_WORKING_DAYS,
    DOMAIN,
    PLATFORMS,
    TRACKING_MODE_BILLABLE,
    WEEKDAY_MAP,
)
from .calculations import (
    calculate_period_hours,
    calculate_target_hours,
    calculate_time_off_days,
    entry_duration_seconds,
    extract_holiday_dates,
)

_LOGGER = logging.getLogger(__name__)

# Required by Hassfest: integrations that implement async_setup must declare
# CONFIG_SCHEMA. Since this integration is config-entry-only, we use the
# appropriate helper so HA knows no YAML configuration is accepted.
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

SERVICE_ADJUST_CORRECTION = "adjust_correction_hours"
SERVICE_RESET_CORRECTION = "reset_correction_hours"

_SCHEMA_ADJUST = vol.Schema({
    vol.Required("config_entry_id"): str,
    vol.Required("hours"): vol.Coerce(float),
})
_SCHEMA_RESET = vol.Schema({
    vol.Required("config_entry_id"): str,
})


# ---------------------------------------------------------------------------
# HA integration lifecycle
# ---------------------------------------------------------------------------


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Clockify Overtime domain and register service actions."""
    hass.data.setdefault(DOMAIN, {})

    async def _handle_adjust_correction(call: ServiceCall) -> None:
        """Add or subtract hours from the overtime correction balance."""
        config_entry_id: str = call.data["config_entry_id"]
        hours: float = call.data["hours"]
        entry = hass.config_entries.async_get_entry(config_entry_id)
        if not entry or entry.domain != DOMAIN:
            raise HomeAssistantError(
                f"Config entry '{config_entry_id}' not found for {DOMAIN}"
            )
        current = float(entry.options.get(CONF_CORRECTION_HOURS, DEFAULT_CORRECTION_HOURS))
        new_value = round(current + hours, 2)
        hass.config_entries.async_update_entry(
            entry, options={**entry.options, CONF_CORRECTION_HOURS: new_value}
        )

    async def _handle_reset_correction(call: ServiceCall) -> None:
        """Reset the overtime correction balance to zero."""
        config_entry_id: str = call.data["config_entry_id"]
        entry = hass.config_entries.async_get_entry(config_entry_id)
        if not entry or entry.domain != DOMAIN:
            raise HomeAssistantError(
                f"Config entry '{config_entry_id}' not found for {DOMAIN}"
            )
        hass.config_entries.async_update_entry(
            entry, options={**entry.options, CONF_CORRECTION_HOURS: 0.0}
        )

    hass.services.async_register(
        DOMAIN, SERVICE_ADJUST_CORRECTION, _handle_adjust_correction,
        schema=_SCHEMA_ADJUST,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_RESET_CORRECTION, _handle_reset_correction,
        schema=_SCHEMA_RESET,
    )
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
        "_structural_snapshot": _structural_snapshot(entry),
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Reload integration when user saves new options
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload for structural changes; refresh only for correction_hours changes.

    Structural settings (scan interval, tracking mode, working days, etc.) require
    the integration to be fully reloaded.  A correction_hours-only change can be
    satisfied by a coordinator refresh, which avoids a disruptive restart.
    """
    stored = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    prev_snapshot = stored.get("_structural_snapshot", {})
    new_snapshot = _structural_snapshot(entry)

    # Update snapshot so it reflects current state for the next change
    if DOMAIN in hass.data and entry.entry_id in hass.data[DOMAIN]:
        hass.data[DOMAIN][entry.entry_id]["_structural_snapshot"] = new_snapshot

    if prev_snapshot == new_snapshot:
        # Only non-structural settings changed (e.g. correction_hours via number entity)
        coordinator = stored.get("coordinator")
        if coordinator:
            await coordinator.async_request_refresh()
        return

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
        self._project_name_cache: dict[str, str] = {}  # project_id -> project_name

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
        tracking_mode: str = _opt(self.entry, CONF_TRACKING_MODE, DEFAULT_TRACKING_MODE)
        excluded_ids: list[str] = _opt(self.entry, CONF_EXCLUDED_PROJECT_IDS, [])
        enable_last_week_sensors: bool = bool(
            _opt(
                self.entry,
                CONF_ENABLE_LAST_WEEK_SENSORS,
                DEFAULT_ENABLE_LAST_WEEK_SENSORS,
            )
        )
        enable_this_week_sensors: bool = bool(
            _opt(
                self.entry,
                CONF_ENABLE_THIS_WEEK_SENSORS,
                DEFAULT_ENABLE_THIS_WEEK_SENSORS,
            )
        )
        correction_hours: float = float(
            _opt(self.entry, CONF_CORRECTION_HOURS, DEFAULT_CORRECTION_HOURS)
        )
        hours_per_week: float = float(
            _opt(self.entry, CONF_HOURS_PER_WEEK, DEFAULT_HOURS_PER_WEEK)
        )
        # working_days: prefer config value, fall back to workspace setting
        working_days: list[str] = list(
            _opt(self.entry, CONF_WORKING_DAYS, self._workspace_working_days)
        ) or list(DEFAULT_WORKING_DAYS)

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
        holiday_dates = extract_holiday_dates(holidays)

        # 5b. Fetch approved time-off requests (optional, free plan returns [])
        time_off_requests = await self.api.get_time_off_requests(
            self._workspace_id, user_id, start_str, end_str
        )
        time_off_days = calculate_time_off_days(
            time_off_requests, working_days, holiday_dates,
            period_start=start_date, period_end=today,
        )

        # 6. Compute hours
        project_sensor_ids: list[str] = list(_opt(self.entry, CONF_PROJECT_SENSOR_IDS, []))

        # Populate project name cache if any sensor IDs are not yet cached
        if project_sensor_ids and any(pid not in self._project_name_cache for pid in project_sensor_ids):
            projects = await self.api.get_projects(self._workspace_id)
            for project in projects:
                self._project_name_cache[project["id"]] = project["name"]

        actual_seconds = 0.0
        billable_seconds = 0.0
        project_seconds: dict[str, float] = {pid: 0.0 for pid in project_sensor_ids}

        for entry in entries:
            # Skip pause/break entries
            if entry.get("type") == "BREAK":
                continue
            duration = entry_duration_seconds(entry)
            actual_seconds += duration

            # Billable = flagged as billable AND not in the exclusion list
            is_billable = entry.get("billable", False)
            is_excluded = entry.get("projectId") in excluded_ids
            if is_billable and not is_excluded:
                billable_seconds += duration

            # Per-project accumulation for sensor projects
            pid = entry.get("projectId")
            if pid and pid in project_seconds:
                project_seconds[pid] += duration

        actual_hours = round(actual_seconds / 3600, 2)
        billable_hours = round(billable_seconds / 3600, 2)

        # 6b. Compute optional weekly aggregates
        this_week_total_hours = 0.0
        this_week_billable_hours = 0.0
        last_week_total_hours = 0.0
        last_week_billable_hours = 0.0

        this_week_start = today - timedelta(days=today.weekday())
        this_week_end = this_week_start + timedelta(days=6)
        if enable_this_week_sensors:
            this_week_total_hours, this_week_billable_hours = calculate_period_hours(
                entries,
                period_start=this_week_start,
                period_end=this_week_end,
                excluded_project_ids=excluded_ids,
            )

        if enable_last_week_sensors:
            last_week_start = this_week_start - timedelta(days=7)
            last_week_end = this_week_start - timedelta(days=1)
            last_week_total_hours, last_week_billable_hours = calculate_period_hours(
                entries,
                period_start=last_week_start,
                period_end=last_week_end,
                excluded_project_ids=excluded_ids,
            )

        # 7. Compute target (Soll-Stunden) minus time-off days
        num_working_days_per_week = len(
            [d for d in working_days if d in WEEKDAY_MAP]
        ) or 5
        hours_per_day_avg = hours_per_week / num_working_days_per_week
        target_hours = round(
            calculate_target_hours(
                start_date,
                today,
                hours_per_week,
                working_days,
                holiday_dates,
            )
            - time_off_days * hours_per_day_avg,
            2,
        )

        # 8. Compute balance
        # Base = billable hours when in billable mode, otherwise all actual hours
        base_hours = billable_hours if tracking_mode == TRACKING_MODE_BILLABLE else actual_hours
        balance_hours = round(base_hours - target_hours + correction_hours, 2)

        project_hours = {pid: round(secs / 3600, 2) for pid, secs in project_seconds.items()}
        project_names = {
            pid: self._project_name_cache.get(pid, pid) for pid in project_sensor_ids
        }

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
            "project_hours": project_hours,
            "project_names": project_names,
            "this_week_total_hours": this_week_total_hours,
            "this_week_billable_hours": this_week_billable_hours,
            "last_week_total_hours": last_week_total_hours,
            "last_week_billable_hours": last_week_billable_hours,
        }


# ---------------------------------------------------------------------------
# Pure helper functions (no HA / no API dependencies)
# ---------------------------------------------------------------------------


def _opt(entry: ConfigEntry, key: str, default: Any) -> Any:
    """Return options value, falling back to entry.data, then *default*."""
    return entry.options.get(key, entry.data.get(key, default))


def _structural_snapshot(entry: ConfigEntry) -> dict:
    """Return a snapshot of settings that require a full reload when changed.

    Settings that only affect the computed result (like correction_hours) are
    intentionally excluded so that a number-entity update avoids a reload.
    """
    keys = {
        CONF_SCAN_INTERVAL,
        CONF_TRACKING_MODE,
        CONF_START_DATE,
        CONF_WORKING_DAYS,
        CONF_HOURS_PER_WEEK,
        CONF_EXCLUDED_PROJECT_IDS,
        CONF_PROJECT_SENSOR_IDS,
        CONF_ENABLE_LAST_WEEK_SENSORS,
        CONF_ENABLE_THIS_WEEK_SENSORS,
    }
    return {k: _opt(entry, k, None) for k in keys}
