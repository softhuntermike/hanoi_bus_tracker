"""Lightweight client for the (unofficial) timbus.vn JSON API.

timbus.vn is the real-time bus tracking site operated by Transerco for
Hanoi public buses. It exposes a couple of POST-only JSON endpoints under
``/Engine/Business/...`` that are used by the public website. These are not
officially documented/supported, so this client is intentionally defensive
about the shape of the responses.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import aiohttp
import async_timeout

_LOGGER = logging.getLogger(__name__)

# timbus.vn's API only responds correctly over plain HTTP - https:// on
# this host returns 404 for these endpoints.
BASE_URL = "http://timbus.vn/Engine/Business"
SEARCH_URL = f"{BASE_URL}/Search/action.ashx"
VEHICLE_URL = f"{BASE_URL}/Vehicle/action.ashx"

HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Referer": "http://timbus.vn/",
    "Origin": "http://timbus.vn",
}

REQUEST_TIMEOUT = 15


class TimbusApiError(Exception):
    """Raised when the timbus.vn API returns an unexpected response."""


class TimbusClient:
    """Small async wrapper around the timbus.vn JSON endpoints."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session

    async def _post(self, url: str, data: dict[str, Any]) -> Any:
        try:
            async with async_timeout.timeout(REQUEST_TIMEOUT):
                async with self._session.post(
                    url, data=data, headers=HEADERS, ssl=False
                ) as resp:
                    resp.raise_for_status()
                    text = await resp.text()
        except aiohttp.ClientError as err:
            raise TimbusApiError(f"Error communicating with timbus.vn: {err}") from err
        except TimeoutError as err:
            raise TimbusApiError("Timeout communicating with timbus.vn") from err

        if not text:
            return {}

        try:
            return json.loads(text)
        except ValueError as err:
            raise TimbusApiError(f"Invalid JSON from timbus.vn: {text[:200]}") from err

    async def search_routes(self, query: str) -> list[dict[str, Any]]:
        """Search bus routes/lines by name or number (e.g. "09", "32")."""
        data = {"act": "searchfull", "typ": "1", "key": query}
        res = await self._post(SEARCH_URL, data)
        return (res.get("dt") or {}).get("Data") or []

    async def fleet_detail(self, fleet_id: str) -> dict[str, Any]:
        """Get details (including the Go/Return station lists) for a route.

        The returned ``dt["Go"]["Station"]`` / ``dt["Re"]["Station"]`` lists
        contain the stops for each direction, each with an ``ObjectID`` that
        matches the ``StationID`` expected by :meth:`part_remained`. The
        generic stop search (typ=2) does not reliably index these
        route-specific stops, so route detail is the correct source for
        building a station picker for a given line.
        """
        data = {"act": "fleetdetail", "fid": fleet_id}
        res = await self._post(SEARCH_URL, data)
        return res.get("dt") or {}

    async def part_remained(self, station_id: str) -> list[dict[str, Any]]:
        """Get the list of buses currently approaching a given station.

        Each item looks like::

            {
                "BienKiemSoat": "29E78612",            # license plate
                "FleetCode": "49 (Ve Tran Khanh Du)",  # route + direction label
                "Fleet": "49",                         # route number (use for matching)
                "PartRemained": 1536,                  # remaining distance, in METERS
                "TimeRemained": 221,                   # remaining time, in SECONDS
                "Speed": 0                             # current speed, km/h
            }

        Note: timbus.vn does not expose the vehicle's raw GPS lat/lon through
        this endpoint - only distance/time/speed relative to the station.
        """
        data = {
            "act": "partremained",
            "State": "true",
            "StationID": station_id,
            "FleetOver": "",
        }
        res = await self._post(VEHICLE_URL, data)
        dt = res.get("dt")
        if dt is None:
            return []
        if isinstance(dt, dict):
            dt = dt.get("Data") or []
        if not isinstance(dt, list):
            return []
        return dt
