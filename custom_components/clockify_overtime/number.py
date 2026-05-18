"""Number platform — settable correction_hours entity for Clockify Overtime Tracker.

Lets the user adjust the payout/correction offset directly from the Home Assistant
UI without having to open the integration's options dialog.  The value is persisted
in the config-entry options so it survives restarts.

Because ``correction_hours`` is not a *structural* setting, changing it via this
entity only triggers a coordinator refresh (not a full integration reload).
"""
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import ClockifyOvertimeCoordinator
from .const import CONF_CORRECTION_HOURS, DEFAULT_CORRECTION_HOURS, DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Clockify Overtime number entities from a config entry."""
    domain_data = hass.data[DOMAIN][entry.entry_id]
    coordinator: ClockifyOvertimeCoordinator = domain_data["coordinator"]
    user_name: str = domain_data["user_info"].get("name", "Clockify")
    async_add_entities([ClockifyCorrectionHoursNumber(coordinator, entry, user_name)])


class ClockifyCorrectionHoursNumber(
    CoordinatorEntity[ClockifyOvertimeCoordinator], NumberEntity
):
    """Settable number entity for the overtime payout/correction offset.

    Positive values represent hours that have been paid out (subtracted from
    the overtime balance).  Negative values add hours to the balance.
    """

    _attr_icon = "mdi:cash-clock"
    _attr_has_entity_name = True
    _attr_name = "Correction Hours"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = -9999.0
    _attr_native_max_value = 9999.0
    _attr_native_step = 0.25
    _attr_native_unit_of_measurement = "h"
    _attr_mode = NumberMode.BOX

    def __init__(
        self,
        coordinator: ClockifyOvertimeCoordinator,
        entry: ConfigEntry,
        user_name: str,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"clockify_overtime_{entry.entry_id}_correction_hours"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": f"Clockify Overtime ({user_name})",
            "manufacturer": "Clockify",
            "model": "Overtime Tracker",
            "entry_type": "service",
        }

    @property
    def native_value(self) -> float:
        """Return the current correction hours from coordinator data."""
        if self.coordinator.data:
            return float(
                self.coordinator.data.get("correction_hours", DEFAULT_CORRECTION_HOURS)
            )
        return DEFAULT_CORRECTION_HOURS

    async def async_set_native_value(self, value: float) -> None:
        """Persist the new correction value and refresh the coordinator.

        Saves the value to config-entry options.  The ``_async_options_updated``
        listener detects that only a non-structural setting changed and performs
        a coordinator refresh instead of a full integration reload.
        """
        new_options = {**self._entry.options, CONF_CORRECTION_HOURS: value}
        self.hass.config_entries.async_update_entry(self._entry, options=new_options)
