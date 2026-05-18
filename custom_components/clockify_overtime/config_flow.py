"""Config flow for Clockify Overtime Tracker — 2-step wizard + OptionsFlow."""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    DateSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

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
    DOMAIN,
    TRACKING_MODE_ALL,
    TRACKING_MODE_BILLABLE,
)

_LOGGER = logging.getLogger(__name__)

_TRACKING_MODE_OPTIONS = [
    {"value": TRACKING_MODE_ALL, "label": "All booked hours"},
    {"value": TRACKING_MODE_BILLABLE, "label": "Billable / project hours only"},
]


# ---------------------------------------------------------------------------
# Config flow
# ---------------------------------------------------------------------------


class ClockifyOvertimeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Two-step config flow: (1) API key → (2) tracking options."""

    VERSION = 1

    def __init__(self) -> None:
        self._api_key: str = ""
        self._user_info: dict[str, Any] = {}
        self._projects: list[dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Step 1 — API key
    # ------------------------------------------------------------------

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            api_key = user_input[CONF_API_KEY].strip()
            try:
                session = async_get_clientsession(self.hass)
                api = ClockifyApi(api_key, session)
                self._user_info = await api.get_user_info()
                workspace_id = self._user_info.get("defaultWorkspace", "")

                # Pre-load projects so the user can pick exclusions in step 2
                try:
                    self._projects = await api.get_projects(workspace_id)
                except ClockifyApiError:
                    self._projects = []

                await self.async_set_unique_id(self._user_info["id"])
                self._abort_if_unique_id_configured()

                self._api_key = api_key
                return await self.async_step_tracking()

            except ClockifyApiError as err:
                _LOGGER.warning("Clockify connection failed: %s", err)
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error in config flow step 1")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_KEY): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                }
            ),
            errors=errors,
            description_placeholders={
                "settings_url": "https://app.clockify.me/user/settings"
            },
        )

    # ------------------------------------------------------------------
    # Step 2 — Tracking options
    # ------------------------------------------------------------------

    async def async_step_tracking(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            excluded = _normalise_excluded(user_input.get(CONF_EXCLUDED_PROJECT_IDS, []))
            return self.async_create_entry(
                title=f"Clockify ({self._user_info['name']})",
                data={
                    CONF_API_KEY: self._api_key,
                    CONF_TRACKING_MODE: user_input[CONF_TRACKING_MODE],
                    CONF_EXCLUDED_PROJECT_IDS: excluded,
                    CONF_HOURS_PER_DAY: float(user_input[CONF_HOURS_PER_DAY]),
                    CONF_START_DATE: user_input[CONF_START_DATE],
                    CONF_CORRECTION_HOURS: float(
                        user_input.get(CONF_CORRECTION_HOURS, DEFAULT_CORRECTION_HOURS)
                    ),
                    CONF_SCAN_INTERVAL: int(
                        user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
                    ),
                },
            )

        return self.async_show_form(
            step_id="tracking",
            data_schema=_build_tracking_schema(
                projects=self._projects,
                defaults={
                    CONF_TRACKING_MODE: DEFAULT_TRACKING_MODE,
                    CONF_HOURS_PER_DAY: DEFAULT_HOURS_PER_DAY,
                    CONF_START_DATE: date.today().isoformat(),
                    CONF_CORRECTION_HOURS: DEFAULT_CORRECTION_HOURS,
                    CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
                    CONF_EXCLUDED_PROJECT_IDS: [],
                },
            ),
            errors=errors,
            description_placeholders={"user": self._user_info.get("name", "")},
        )

    # ------------------------------------------------------------------
    # Options flow entry point
    # ------------------------------------------------------------------

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> ClockifyOvertimeOptionsFlow:
        return ClockifyOvertimeOptionsFlow(config_entry)


# ---------------------------------------------------------------------------
# Options flow  (Settings → Integrations → Configure)
# ---------------------------------------------------------------------------


class ClockifyOvertimeOptionsFlow(config_entries.OptionsFlow):
    """Allows updating all tracking settings and overtime corrections at any time."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._entry = config_entry
        self._projects: list[dict[str, Any]] = []

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        # Re-fetch project list so the selector stays up-to-date
        if not self._projects:
            try:
                session = async_get_clientsession(self.hass)
                api = ClockifyApi(self._entry.data[CONF_API_KEY], session)
                user_info = await api.get_user_info()
                workspace_id = user_info.get("defaultWorkspace", "")
                self._projects = await api.get_projects(workspace_id)
            except Exception:
                _LOGGER.debug("Could not load projects for options flow")
                self._projects = []

        # Merge data + options so the form shows current values
        current: dict[str, Any] = {**self._entry.data, **self._entry.options}
        errors: dict[str, str] = {}

        if user_input is not None:
            excluded = _normalise_excluded(user_input.get(CONF_EXCLUDED_PROJECT_IDS, []))
            user_input[CONF_EXCLUDED_PROJECT_IDS] = excluded
            user_input[CONF_HOURS_PER_DAY] = float(user_input[CONF_HOURS_PER_DAY])
            user_input[CONF_CORRECTION_HOURS] = float(user_input[CONF_CORRECTION_HOURS])
            user_input[CONF_SCAN_INTERVAL] = int(user_input[CONF_SCAN_INTERVAL])
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=_build_tracking_schema(
                projects=self._projects,
                defaults={
                    CONF_TRACKING_MODE: current.get(CONF_TRACKING_MODE, DEFAULT_TRACKING_MODE),
                    CONF_HOURS_PER_DAY: float(current.get(CONF_HOURS_PER_DAY, DEFAULT_HOURS_PER_DAY)),
                    CONF_START_DATE: current.get(CONF_START_DATE, date.today().isoformat()),
                    CONF_CORRECTION_HOURS: float(
                        current.get(CONF_CORRECTION_HOURS, DEFAULT_CORRECTION_HOURS)
                    ),
                    CONF_SCAN_INTERVAL: int(current.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
                    CONF_EXCLUDED_PROJECT_IDS: current.get(CONF_EXCLUDED_PROJECT_IDS, []),
                },
            ),
            errors=errors,
        )


# ---------------------------------------------------------------------------
# Shared schema builder
# ---------------------------------------------------------------------------


def _build_tracking_schema(
    projects: list[dict[str, Any]],
    defaults: dict[str, Any],
) -> vol.Schema:
    """Build the voluptuous schema for step 2 / options, with optional project selector."""
    schema: dict[Any, Any] = {
        vol.Required(
            CONF_TRACKING_MODE, default=defaults[CONF_TRACKING_MODE]
        ): SelectSelector(
            SelectSelectorConfig(
                options=_TRACKING_MODE_OPTIONS,
                mode=SelectSelectorMode.LIST,
            )
        ),
        vol.Required(
            CONF_HOURS_PER_DAY, default=defaults[CONF_HOURS_PER_DAY]
        ): NumberSelector(
            NumberSelectorConfig(min=0.5, max=24.0, step=0.5, mode=NumberSelectorMode.BOX)
        ),
        vol.Required(
            CONF_START_DATE, default=defaults[CONF_START_DATE]
        ): DateSelector(),
        vol.Optional(
            CONF_CORRECTION_HOURS, default=defaults[CONF_CORRECTION_HOURS]
        ): NumberSelector(
            NumberSelectorConfig(
                min=-9999.0, max=9999.0, step=0.25, mode=NumberSelectorMode.BOX
            )
        ),
        vol.Optional(
            CONF_SCAN_INTERVAL, default=defaults[CONF_SCAN_INTERVAL]
        ): NumberSelector(
            NumberSelectorConfig(min=5, max=1440, step=5, mode=NumberSelectorMode.BOX)
        ),
    }

    # Only show project multi-select when we have projects to choose from
    if projects:
        project_options = [{"value": p["id"], "label": p["name"]} for p in projects]
        schema[
            vol.Optional(
                CONF_EXCLUDED_PROJECT_IDS,
                default=defaults.get(CONF_EXCLUDED_PROJECT_IDS, []),
            )
        ] = SelectSelector(
            SelectSelectorConfig(
                options=project_options,
                multiple=True,
                mode=SelectSelectorMode.DROPDOWN,
            )
        )

    return vol.Schema(schema)


def _normalise_excluded(value: Any) -> list[str]:
    """Accept either a list or a comma-separated string of project IDs."""
    if isinstance(value, list):
        return [str(v).strip() for v in value if v]
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()]
    return []
