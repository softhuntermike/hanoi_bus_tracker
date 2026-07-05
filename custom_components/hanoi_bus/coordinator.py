"""Data update coordinator for the Hanoi Bus (Timbus) integration."""
from __future__ import annotations

import logging
import time
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import BusmapClient, TimbusApiError, TimbusClient
from .const import (
    CONF_ROUTE_CODE,
    CONF_ROUTE_NAME,
    CONF_STATION_ID,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class HanoiBusCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls timbus.vn for buses approaching a configured station."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.entry = entry
        session = async_get_clientsession(hass)
        self.client = TimbusClient(session)
        self.busmap = BusmapClient(session)
        self.route_name: str = entry.data[CONF_ROUTE_NAME]
        self.route_code: str = entry.data[CONF_ROUTE_CODE]
        self.station_id: str = entry.data[CONF_STATION_ID]
        self.paused: bool = False
        self._previous: dict[str, tuple[float, float]] = {}

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        if self.paused:
            return {"all": [], "matching": [], "paused": True}

        buses = await self.busmap.estimate_bus_to_station(self.station_id)
        _LOGGER.debug("hanoi_bus: Busmap returned %d buses for station %s", len(buses), self.station_id)
        if not buses:
            _LOGGER.debug("hanoi_bus: falling back to timbus")
            try:
                buses = await self.client.part_remained(self.station_id)
            except TimbusApiError as err:
                raise UpdateFailed(str(err)) from err

        now = time.monotonic()
        seen: set[str] = set()
        for bus in buses:
            plate = bus.get("BienKiemSoat")
            try:
                distance = float(bus.get("PartRemained"))
            except (TypeError, ValueError):
                distance = None

            speed_kmh = None
            if plate and distance is not None:
                seen.add(plate)
                prev = self._previous.get(plate)
                if prev is not None:
                    prev_time, prev_distance = prev
                    delta_time = now - prev_time
                    delta_distance = prev_distance - distance
                    # Ignore stale samples or distance jumps (bus passed the
                    # stop / route reset) which would give a meaningless speed.
                    if 0 < delta_time <= 120 and 0 <= delta_distance <= 2000:
                        speed_kmh = (delta_distance / delta_time) * 3.6
                self._previous[plate] = (now, distance)

            bus["SpeedKmh"] = round(speed_kmh, 1) if speed_kmh is not None else None

        # Drop plates we haven't seen this round so stale entries don't
        # accumulate forever.
        for plate in list(self._previous):
            if plate not in seen:
                del self._previous[plate]

        matching = [bus for bus in buses if self._matches_route(bus)]

        return {"all": buses, "matching": matching}

    def _matches_route(self, bus: dict[str, Any]) -> bool:
        """Check whether a bus entry belongs to the configured route."""
        code = str(self.route_code or "").strip().lower()
        if not code:
            return True

        # "Fleet" is the clean route number (e.g. "49") and is the most
        # reliable match. "FleetCode" additionally includes a direction
        # label (e.g. "49 (Ve Tran Khanh Du)"), so fall back to a prefix
        # check there.
        fleet = bus.get("Fleet")
        if fleet is not None and str(fleet).strip().lower() == code:
            return True

        for key in ("FleetCode", "Xe", "ChieuXe"):
            value = bus.get(key)
            if value is None:
                continue
            value = str(value).strip().lower()
            if value == code or value.startswith(code):
                return True
        return False
