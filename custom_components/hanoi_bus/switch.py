"""Switch platform for the Hanoi Bus (Timbus) integration.

Provides a "Scanning" toggle that can be placed on any dashboard card.
When turned off the coordinator skips API calls and sensors report
"Update paused" instead of stale values.
"""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_ROUTE_ID, CONF_ROUTE_NAME, CONF_STATION_ID, CONF_STATION_NAME, DOMAIN
from .coordinator import HanoiBusCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: HanoiBusCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([HanoiBusScanSwitch(coordinator, entry)])


class HanoiBusScanSwitch(CoordinatorEntity[HanoiBusCoordinator], SwitchEntity):
    """Switch that pauses/resumes polling for a route/station pair."""

    _attr_has_entity_name = True
    _attr_name = "Scanning"
    _attr_icon = "mdi:radar"

    def __init__(self, coordinator: HanoiBusCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = (
            f"{entry.data[CONF_ROUTE_ID]}_{entry.data[CONF_STATION_ID]}_scanning"
        )

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={
                (
                    DOMAIN,
                    f"{self._entry.data[CONF_ROUTE_ID]}_{self._entry.data[CONF_STATION_ID]}",
                )
            },
            name=f"Bus {self._entry.data[CONF_ROUTE_NAME]} @ {self._entry.data[CONF_STATION_NAME]}",
            manufacturer="Transerco (timbus.vn)",
            model="Hanoi Bus Tracker",
        )

    @property
    def is_on(self) -> bool:
        return not self.coordinator.paused

    async def async_turn_on(self, **kwargs) -> None:
        self.coordinator.paused = False
        await self.coordinator.async_request_refresh()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        self.coordinator.paused = True
        await self.coordinator.async_request_refresh()
        self.async_write_ha_state()
