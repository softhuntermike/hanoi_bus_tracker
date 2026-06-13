"""Config flow for the Hanoi Bus (Timbus) integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import TimbusApiError, TimbusClient
from .const import (
    CONF_ROUTE_CODE,
    CONF_ROUTE_ID,
    CONF_ROUTE_NAME,
    CONF_STATION_ID,
    CONF_STATION_LAT,
    CONF_STATION_LON,
    CONF_STATION_NAME,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


def _route_label(route: dict[str, Any]) -> str:
    name = route.get("Name") or "?"
    code = route.get("FleedCode") or route.get("FleetCode") or ""
    return f"{name} ({code})" if code else str(name)


def _station_label(station: dict[str, Any], direction: str) -> str:
    name = station.get("Name") or "?"
    return f"[{direction}] {name}"


class HanoiBusConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Hanoi Bus (Timbus)."""

    VERSION = 1

    def __init__(self) -> None:
        self._routes: list[dict[str, Any]] = []
        self._selected_route: dict[str, Any] | None = None
        self._stations: list[tuple[dict[str, Any], str]] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Ask for a bus line/route to search for (e.g. "09", "32")."""
        errors: dict[str, str] = {}

        if user_input is not None:
            client = TimbusClient(async_get_clientsession(self.hass))
            try:
                routes = await client.search_routes(user_input["route_query"])
            except TimbusApiError:
                errors["base"] = "cannot_connect"
            else:
                if not routes:
                    errors["base"] = "no_results"
                else:
                    self._routes = routes
                    return await self.async_step_route()

        schema = vol.Schema({vol.Required("route_query"): str})
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_route(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Let the user pick the exact route/direction from the search results."""
        errors: dict[str, str] = {}
        options = {str(i): _route_label(r) for i, r in enumerate(self._routes)}

        if user_input is not None:
            self._selected_route = self._routes[int(user_input["route"])]
            client = TimbusClient(async_get_clientsession(self.hass))
            try:
                detail = await client.fleet_detail(
                    str(self._selected_route.get("ObjectID"))
                )
            except TimbusApiError:
                errors["base"] = "cannot_connect"
            else:
                stations: list[tuple[dict[str, Any], str]] = []
                for direction, label in (("Go", "Go"), ("Re", "Return")):
                    for station in (detail.get(direction) or {}).get("Station") or []:
                        stations.append((station, label))
                if not stations:
                    errors["base"] = "no_results"
                else:
                    self._stations = stations
                    return await self.async_step_station()

        schema = vol.Schema({vol.Required("route"): vol.In(options)})
        return self.async_show_form(step_id="route", data_schema=schema, errors=errors)

    async def async_step_station(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Let the user pick the exact bus stop along the selected route."""
        errors: dict[str, str] = {}
        options = {
            str(i): _station_label(station, direction)
            for i, (station, direction) in enumerate(self._stations)
        }

        if user_input is not None:
            station, _direction = self._stations[int(user_input["station"])]
            route = self._selected_route or {}

            route_id = str(route.get("ObjectID") or "")
            route_name = str(route.get("Name") or "")
            route_code = str(route.get("FleedCode") or route.get("FleetCode") or "")
            station_id = str(station.get("ObjectID") or "")
            station_name = str(station.get("Name") or "")

            geo = station.get("Geo") or {}

            await self.async_set_unique_id(f"{route_id}_{station_id}")
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title=f"{route_name} @ {station_name}",
                data={
                    CONF_ROUTE_ID: route_id,
                    CONF_ROUTE_NAME: route_name,
                    CONF_ROUTE_CODE: route_code,
                    CONF_STATION_ID: station_id,
                    CONF_STATION_NAME: station_name,
                    CONF_STATION_LAT: geo.get("Lat"),
                    CONF_STATION_LON: geo.get("Lng"),
                },
            )

        schema = vol.Schema({vol.Required("station"): vol.In(options)})
        return self.async_show_form(step_id="station", data_schema=schema, errors=errors)
