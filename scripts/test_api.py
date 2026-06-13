"""Standalone test script for the timbus.vn API client.

Run this on a machine with internet access (e.g. your Home Assistant host)
to verify search results and live ETA/distance for a given line + stop
before configuring the integration.

Usage:
    python test_api.py "49" "Tran Huu Duc"
"""
from __future__ import annotations

import asyncio
import json
import sys

import aiohttp

sys.path.insert(0, "../custom_components/hanoi_bus")
from api import TimbusClient  # noqa: E402


async def main(route_query: str, station_query: str) -> None:
    async with aiohttp.ClientSession() as session:
        client = TimbusClient(session)

        print(f"\n=== Searching routes for '{route_query}' ===")
        routes = await client.search_routes(route_query)
        print(json.dumps(routes, indent=2, ensure_ascii=False))
        if not routes:
            return
        route = routes[0]

        print(f"\n=== fleet_detail for route ObjectID={route.get('ObjectID')} ===")
        detail = await client.fleet_detail(str(route.get("ObjectID")))
        print("Route:", detail.get("Name"))

        print(f"\n=== Stations matching '{station_query}' ===")
        matches = []
        for direction in ("Go", "Re"):
            for station in (detail.get(direction) or {}).get("Station") or []:
                if station_query.lower() in (station.get("Name") or "").lower():
                    matches.append((direction, station))
                    print(direction, station.get("ObjectID"), station.get("Name"))

        for direction, station in matches:
            station_id = str(station.get("ObjectID"))
            print(f"\n=== part_remained for {direction} StationID={station_id} ===")
            buses = await client.part_remained(station_id)
            print(json.dumps(buses, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    route_q = sys.argv[1] if len(sys.argv) > 1 else "49"
    station_q = sys.argv[2] if len(sys.argv) > 2 else "Tran Huu Duc"
    asyncio.run(main(route_q, station_q))
