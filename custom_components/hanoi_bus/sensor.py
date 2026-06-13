"""Sensor platform for the Hanoi Bus (Timbus) integration."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfLength, UnitOfSpeed, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_BUSES,
    ATTR_DISTANCE,
    ATTR_ETA,
    ATTR_FLEET_CODE,
    ATTR_PLATE,
    ATTR_ROUTE_NAME,
    ATTR_SPEED,
    ATTR_STATION_NAME,
    CONF_ROUTE_ID,
    CONF_ROUTE_NAME,
    CONF_STATION_ID,
    CONF_STATION_NAME,
    DOMAIN,
)
from .coordinator import HanoiBusCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Hanoi Bus sensors from a config entry."""
    coordinator: HanoiBusCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        [
            HanoiBusEtaSensor(coordinator, entry),
            HanoiBusDistanceSensor(coordinator, entry),
            HanoiBusPlateSensor(coordinator, entry),
            HanoiBusSpeedSensor(coordinator, entry),
            HanoiBusCountSensor(coordinator, entry),
        ]
    )


def _buses_attr(buses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for bus in buses:
        result.append(
            {
                ATTR_PLATE: bus.get("BienKiemSoat"),
                ATTR_FLEET_CODE: bus.get("FleetCode") or bus.get("Fleet"),
                ATTR_DISTANCE: bus.get("PartRemained"),
                ATTR_ETA: bus.get("TimeRemained"),
                ATTR_SPEED: bus.get("SpeedKmh"),
            }
        )
    return result


def _nearest(buses: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not buses:
        return None

    def _key(bus: dict[str, Any]) -> float:
        try:
            return float(bus.get("TimeRemained"))
        except (TypeError, ValueError):
            try:
                return float(bus.get("PartRemained"))
            except (TypeError, ValueError):
                return float("inf")

    return min(buses, key=_key)


class HanoiBusEntity(CoordinatorEntity[HanoiBusCoordinator]):
    """Base entity sharing device info for a route/station pair."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: HanoiBusCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._route_name = entry.data[CONF_ROUTE_NAME]
        self._station_name = entry.data[CONF_STATION_NAME]

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={
                (
                    DOMAIN,
                    f"{self._entry.data[CONF_ROUTE_ID]}_{self._entry.data[CONF_STATION_ID]}",
                )
            },
            name=f"Bus {self._route_name} @ {self._station_name}",
            manufacturer="Transerco (timbus.vn)",
            model="Hanoi Bus Tracker",
        )

    @property
    def _matching(self) -> list[dict[str, Any]]:
        data = self.coordinator.data or {}
        return data.get("matching") or []

    def _extra_attrs(self) -> dict[str, Any]:
        return {
            ATTR_ROUTE_NAME: self._route_name,
            ATTR_STATION_NAME: self._station_name,
            ATTR_BUSES: _buses_attr(self._matching),
        }


class HanoiBusEtaSensor(HanoiBusEntity, SensorEntity):
    """ETA (seconds) of the nearest matching bus to the station."""

    _attr_name = "ETA"
    _attr_icon = "mdi:bus-clock"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS

    def __init__(self, coordinator: HanoiBusCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = (
            f"{entry.data[CONF_ROUTE_ID]}_{entry.data[CONF_STATION_ID]}_eta"
        )

    @property
    def native_value(self) -> float | None:
        bus = _nearest(self._matching)
        if not bus:
            return None
        try:
            return float(bus.get("TimeRemained"))
        except (TypeError, ValueError):
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs = self._extra_attrs()
        bus = _nearest(self._matching)
        if bus:
            attrs[ATTR_PLATE] = bus.get("BienKiemSoat")
        return attrs


class HanoiBusDistanceSensor(HanoiBusEntity, SensorEntity):
    """Remaining distance (meters) of the nearest matching bus to the station."""

    _attr_name = "Distance"
    _attr_icon = "mdi:map-marker-distance"
    _attr_device_class = SensorDeviceClass.DISTANCE
    _attr_native_unit_of_measurement = UnitOfLength.METERS

    def __init__(self, coordinator: HanoiBusCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = (
            f"{entry.data[CONF_ROUTE_ID]}_{entry.data[CONF_STATION_ID]}_distance"
        )

    @property
    def native_value(self) -> float | None:
        bus = _nearest(self._matching)
        if not bus:
            return None
        try:
            return float(bus.get("PartRemained"))
        except (TypeError, ValueError):
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs = self._extra_attrs()
        bus = _nearest(self._matching)
        if bus:
            attrs[ATTR_PLATE] = bus.get("BienKiemSoat")
        return attrs


class HanoiBusPlateSensor(HanoiBusEntity, SensorEntity):
    """License plate of the nearest matching bus."""

    _attr_name = "Plate"
    _attr_icon = "mdi:card-text"

    def __init__(self, coordinator: HanoiBusCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = (
            f"{entry.data[CONF_ROUTE_ID]}_{entry.data[CONF_STATION_ID]}_plate"
        )

    @property
    def native_value(self) -> str | None:
        bus = _nearest(self._matching)
        if not bus:
            return None
        return bus.get("BienKiemSoat")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self._extra_attrs()


class HanoiBusSpeedSensor(HanoiBusEntity, SensorEntity):
    """Estimated speed (km/h) of the nearest matching bus.

    timbus.vn's API does not populate a usable speed field, so this is
    derived from the change in PartRemained (distance to the stop) between
    consecutive polls.
    """

    _attr_name = "Speed"
    _attr_icon = "mdi:speedometer"
    _attr_device_class = SensorDeviceClass.SPEED
    _attr_native_unit_of_measurement = UnitOfSpeed.KILOMETERS_PER_HOUR

    def __init__(self, coordinator: HanoiBusCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = (
            f"{entry.data[CONF_ROUTE_ID]}_{entry.data[CONF_STATION_ID]}_speed"
        )

    @property
    def native_value(self) -> float | None:
        bus = _nearest(self._matching)
        if not bus:
            return None
        return bus.get("SpeedKmh")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs = self._extra_attrs()
        bus = _nearest(self._matching)
        if bus:
            attrs[ATTR_PLATE] = bus.get("BienKiemSoat")
        return attrs


class HanoiBusCountSensor(HanoiBusEntity, SensorEntity):
    """Number of buses on the configured route currently tracked towards the station."""

    _attr_name = "Buses approaching"
    _attr_icon = "mdi:bus-multiple"
    _attr_native_unit_of_measurement = "buses"

    def __init__(self, coordinator: HanoiBusCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = (
            f"{entry.data[CONF_ROUTE_ID]}_{entry.data[CONF_STATION_ID]}_count"
        )

    @property
    def native_value(self) -> int:
        return len(self._matching)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self._extra_attrs()
