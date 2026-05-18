"""Sensor platform for Clockify Overtime Tracker."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import ClockifyOvertimeCoordinator
from .const import CONF_TRACKING_MODE, DOMAIN, TRACKING_MODE_BILLABLE


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Clockify Overtime sensors from a config entry."""
    domain_data = hass.data[DOMAIN][entry.entry_id]
    coordinator: ClockifyOvertimeCoordinator = domain_data["coordinator"]
    user_name: str = domain_data["user_info"].get("name", "Clockify")

    entities: list[SensorEntity] = [
        ClockifyActualHoursSensor(coordinator, entry, user_name),
        ClockifyTargetHoursSensor(coordinator, entry, user_name),
        ClockifyOvertimeBalanceSensor(coordinator, entry, user_name),
    ]

    # Add the billable-hours sensor only when the user selected billable mode
    tracking_mode = entry.data.get(CONF_TRACKING_MODE, entry.options.get(CONF_TRACKING_MODE, "all"))
    if tracking_mode == TRACKING_MODE_BILLABLE:
        entities.append(ClockifyBillableHoursSensor(coordinator, entry, user_name))

    async_add_entities(entities)


# ---------------------------------------------------------------------------
# Base sensor
# ---------------------------------------------------------------------------


class _ClockifyBaseSensor(CoordinatorEntity[ClockifyOvertimeCoordinator], SensorEntity):
    """Shared base for all Clockify Overtime sensors."""

    _attr_native_unit_of_measurement = "h"
    _attr_state_class = SensorStateClass.TOTAL
    _attr_icon = "mdi:clock-outline"
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ClockifyOvertimeCoordinator,
        entry: ConfigEntry,
        user_name: str,
        data_key: str,
        label: str,
    ) -> None:
        super().__init__(coordinator)
        self._data_key = data_key
        self._attr_name = label
        self._attr_unique_id = f"clockify_overtime_{entry.entry_id}_{data_key}"
        # Group all sensors under one logical device per user
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": f"Clockify Overtime ({user_name})",
            "manufacturer": "Clockify",
            "model": "Overtime Tracker",
            "entry_type": "service",
        }

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data:
            return self.coordinator.data.get(self._data_key)
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if not self.coordinator.data:
            return {}
        return {
            "start_date": self.coordinator.data.get("start_date"),
            "tracking_mode": self.coordinator.data.get("tracking_mode"),
            "last_updated": self.coordinator.data.get("last_updated"),
        }


# ---------------------------------------------------------------------------
# Concrete sensors
# ---------------------------------------------------------------------------


class ClockifyActualHoursSensor(_ClockifyBaseSensor):
    """Total hours worked (all REGULAR entries, excluding BREAKs)."""

    _attr_icon = "mdi:clock-check-outline"

    def __init__(self, coordinator, entry, user_name) -> None:
        super().__init__(coordinator, entry, user_name, "total_hours", "Total Hours")


class ClockifyBillableHoursSensor(_ClockifyBaseSensor):
    """Billable / project hours only (excludes non-billable and excluded projects)."""

    _attr_icon = "mdi:briefcase-clock-outline"

    def __init__(self, coordinator, entry, user_name) -> None:
        super().__init__(
            coordinator, entry, user_name, "billable_hours", "Billable Hours"
        )


class ClockifyTargetHoursSensor(_ClockifyBaseSensor):
    """Expected (target) hours since the tracking start date."""

    _attr_icon = "mdi:calendar-clock-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry, user_name) -> None:
        super().__init__(coordinator, entry, user_name, "target_hours", "Target Hours")


class ClockifyOvertimeBalanceSensor(_ClockifyBaseSensor):
    """Overtime balance = base hours − target hours − correction hours.

    *base hours* is either actual_hours (mode=all) or billable_hours (mode=billable).
    This sensor uses MEASUREMENT state class because the value can be negative.
    """

    _attr_icon = "mdi:clock-plus-outline"
    _attr_state_class = SensorStateClass.MEASUREMENT  # allows negative values

    def __init__(self, coordinator, entry, user_name) -> None:
        super().__init__(
            coordinator, entry, user_name, "balance_hours", "Overtime Balance"
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs = super().extra_state_attributes
        if self.coordinator.data:
            attrs.update(
                {
                    "total_hours": self.coordinator.data.get("total_hours"),
                    "billable_hours": self.coordinator.data.get("billable_hours"),
                    "target_hours": self.coordinator.data.get("target_hours"),
                    "correction_hours": self.coordinator.data.get("correction_hours"),
                    "time_off_days": self.coordinator.data.get("time_off_days"),
                }
            )
        return attrs
