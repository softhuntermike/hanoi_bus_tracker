"""API clients for Hanoi bus tracking.

Two sources, tried in order:
1. Busmap (api-web.busmap.vn) — richer data, AES-256-CBC encrypted responses.
2. timbus.vn — fallback, plain JSON, always available.
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


# ---------------------------------------------------------------------------
# Busmap client  (api-web.busmap.vn)
# ---------------------------------------------------------------------------

BUSMAP_BASE = "https://api-web.busmap.vn"
BUSMAP_KEY_URL = f"{BUSMAP_BASE}/web/public/auth/decrypt_key"
BUSMAP_ETA_URL = f"{BUSMAP_BASE}/web/public/station/estimate_bus_to_station"


def _busmap_decrypt(key: bytes, hex_payload: str) -> Any:
    """AES-256-CBC decrypt a Busmap response (first 16 bytes = IV)."""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives import padding

    raw = bytes.fromhex(hex_payload)
    iv, ct = raw[:16], raw[16:]
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    dec = cipher.decryptor()
    pt = dec.update(ct) + dec.finalize()
    # strip PKCS7 padding
    unpadder = padding.PKCS7(128).unpadder()
    pt = unpadder.update(pt) + unpadder.finalize()
    return json.loads(pt.decode())


def _normalize_busmap(raw: dict) -> dict | None:
    """Convert a Busmap bus item to timbus-compatible format.

    Field names are best-effort — Busmap's API is undocumented and fields
    were reverse-engineered. If this returns None the item is skipped and
    the DEBUG log will show the raw payload for diagnosis.

    # ponytail: update field candidates once a live response is observed
    """
    plate = (
        raw.get("licensePlate") or raw.get("bienKiemSoat") or
        raw.get("vehicleNo") or raw.get("busNo") or raw.get("plate")
    )
    route = raw.get("routeNo") or raw.get("routeId") or raw.get("route")
    distance = (
        raw.get("distanceRemaining") or raw.get("distance") or
        raw.get("partRemained") or raw.get("khoangCach")
    )
    eta_sec = (
        raw.get("timeRemaining") or raw.get("timeRemained") or raw.get("eta")
    )
    eta_min = raw.get("minuteRemaining") or raw.get("minuteRemain") or raw.get("minute")
    if eta_sec is None and eta_min is not None:
        try:
            eta_sec = float(eta_min) * 60
        except (TypeError, ValueError):
            pass

    try:
        distance = float(distance) if distance is not None else None
        eta_sec = float(eta_sec) if eta_sec is not None else None
    except (TypeError, ValueError):
        distance = eta_sec = None

    if distance is None and eta_sec is None:
        return None

    return {
        "BienKiemSoat": plate,
        "FleetCode": str(route) if route else "",
        "Fleet": str(route) if route else "",
        "PartRemained": distance or 0.0,
        "TimeRemained": eta_sec or 0.0,
        "Speed": raw.get("speed") or raw.get("Speed") or 0,
        "_source": "busmap",
    }


class BusmapClient:
    """Async client for api-web.busmap.vn (AES-256-CBC encrypted responses)."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session
        self._key: bytes | None = None

    async def _fetch_key(self) -> bytes:
        async with async_timeout.timeout(REQUEST_TIMEOUT):
            async with self._session.get(BUSMAP_KEY_URL) as resp:
                resp.raise_for_status()
                raw = await resp.json(content_type=None)
                return raw.encode() if isinstance(raw, str) else raw

    async def _get(self, url: str, params: dict) -> Any:
        if self._key is None:
            self._key = await self._fetch_key()
        async with async_timeout.timeout(REQUEST_TIMEOUT):
            async with self._session.get(url, params=params) as resp:
                resp.raise_for_status()
                hex_payload = await resp.json(content_type=None)
        return _busmap_decrypt(self._key, hex_payload)

    async def estimate_bus_to_station(self, station_id: str) -> list[dict[str, Any]]:
        """Return approaching buses in timbus-compatible format, or [] on failure."""
        try:
            raw_list = await self._get(
                BUSMAP_ETA_URL,
                {"regionCode": "hn", "stationId": station_id, "group": 1},
            )
        except Exception as err:
            _LOGGER.debug("Busmap request failed: %s", err)
            return []

        if not isinstance(raw_list, list) or not raw_list:
            return []

        _LOGGER.warning("hanoi_bus Busmap raw response for station %s: %s", station_id, raw_list)

        result = []
        for item in raw_list:
            normalized = _normalize_busmap(item)
            if normalized:
                result.append(normalized)
            else:
                _LOGGER.warning(
                    "Could not normalize Busmap item — raw fields: %s",
                    list(item.keys()),
                )
        return result


# ---------------------------------------------------------------------------
# timbus.vn client  (fallback)
# ---------------------------------------------------------------------------

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
