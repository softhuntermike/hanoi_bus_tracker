# Hanoi Bus (Timbus) – Home Assistant Integration

A custom Home Assistant integration that tracks Hanoi public buses
(Transerco) using the **unofficial JSON API behind [timbus.vn](http://timbus.vn)**,
and reports how far away / how soon a bus on a given line is from a chosen
bus stop.

> ⚠️ This uses an **unofficial, reverse-engineered API**. timbus.vn may
> change or block it at any time without notice. There is no official
> public API for Hanoi buses, and **the API does not expose raw vehicle
> GPS coordinates** — only distance, ETA and speed relative to a stop (see
> "Notes & caveats" below).

## How it works

timbus.vn (the public bus-tracking site run by Transerco) exposes a couple
of POST/JSON endpoints under `/Engine/Business/...` that power its website.
**Note: the site only responds correctly over plain `http://`, not
`https://`.**

| Purpose | Endpoint | Key params |
|---|---|---|
| Search bus lines | `Search/action.ashx` | `act=searchfull&typ=1&key=<query>` |
| Route detail (incl. station lists) | `Search/action.ashx` | `act=fleetdetail&fid=<route id>` |
| **Live ETA/distance for a stop** | `Vehicle/action.ashx` | `act=partremained&State=true&StationID=<stop id>&FleetOver=` |

The `partremained` response returns **every** bus approaching the stop
(all lines that serve it). This integration filters the list down to the
line you configured by matching the `Fleet` field (e.g. `"49"`).

Field meanings:

- `Fleet` – clean route number (used for matching, e.g. `"49"`)
- `FleetCode` – route + direction label (e.g. `"49 (Về Trần Khánh Dư)"`)
- `BienKiemSoat` – license plate
- `PartRemained` – remaining distance to the stop, **in meters**
- `TimeRemained` – estimated time remaining, **in seconds**
- `Speed` – always `0` in observed responses across multiple stations/lines;
  timbus.vn does not appear to populate this field via this endpoint (the
  official app shows a speed, presumably computed client-side or from a
  different endpoint). This integration estimates speed itself from the
  change in `PartRemained` between consecutive polls (see "Speed" sensor
  below).

This integration polls the `partremained` endpoint every 30 seconds for the
stop you configure.

## Installation

### HACS (custom repository)

1. In HACS, add this repository as a custom repository (Integrations).
2. Install "Hanoi Bus (Timbus)".
3. Restart Home Assistant.

### Manual

1. Copy the `custom_components/hanoi_bus` folder into your Home Assistant
   `config/custom_components/` directory.
2. Restart Home Assistant.

## Configuration

Configuration is done entirely through the UI:

1. Go to **Settings → Devices & Services → Add Integration** and search for
   **Hanoi Bus (Timbus)**.
2. Enter the bus line number/name you want to track (e.g. `09`, `32`, `49`)
   and pick the matching line/direction from the search results.
3. Pick the bus stop along that line from the list (stops are labelled
   `[Go]` for the outbound direction or `[Return]` for the inbound
   direction).

This creates one device with the following entities:

- **ETA** (`sensor.*_eta`) – seconds until the nearest matching bus reaches
  the stop (device class: duration). Also exposes an `eta_mm_ss` attribute
  with the same value formatted as `m:ss` (e.g. `3:41`).
- **Distance** (`sensor.*_distance`) – remaining distance, in meters, of the
  nearest matching bus (device class: distance)
- **Plate** (`sensor.*_plate`) – license plate of the nearest matching bus
- **Speed** (`sensor.*_speed`) – estimated speed (km/h) of the nearest
  matching bus, derived from the change in distance-to-stop between polls
  (30s apart). May be `unknown` for the first update after startup, and is
  only an approximation.
- **Buses approaching** (`sensor.*_buses_approaching`) – how many buses on
  that line are currently inbound to the stop

All sensors expose a `buses` attribute with the full list of matching buses
(plate, fleet code, distance, ETA, speed) in case more than one bus is
inbound.

You can add as many bus-line/bus-stop combinations as you like by repeating
the "Add Integration" flow.

## Testing the API directly

`scripts/test_api.py` is a standalone script (run on a machine with
internet access) that exercises the same API client used by the
integration — useful for finding route/station IDs and checking live
responses before configuring Home Assistant:

```bash
cd scripts
python test_api.py "32" "dai hoc su pham"
```

## Notes & caveats

- **No raw GPS coordinates**: timbus.vn's public endpoints only return
  distance/time/speed relative to a stop, not the vehicle's lat/lon. There
  is no `device_tracker` entity for this reason — "GPS location" is
  expressed as distance + ETA + speed relative to your chosen stop.
- **Route matching**: a stop is often served by several lines (e.g. stop
  1893 above is served by lines 49, 50 and 97). This integration filters
  `partremained` results by the `Fleet` field matching your configured
  line's code.
- **Directions**: each route has a "Go" and "Return" station list with
  different stops/IDs. Make sure to pick the stop for the direction you
  care about — add a second config entry if you want both directions.
- **HTTP only**: timbus.vn's API endpoints must be called over `http://`,
  not `https://`.
- If searches stop returning results, check the Home Assistant logs for
  `hanoi_bus` — the integration logs raw errors from the API, and
  timbus.vn may have changed its API.

## Pausing scanning on a schedule

Each bus device includes a **Scanning** switch entity. You can add it to
any dashboard card and also drive it from automations.

Example: scan only on weekday mornings (07:00–09:00):

```yaml
- alias: "Hanoi Bus: start scanning on weekday mornings"
  trigger:
    - platform: time
      at: "07:00:00"
  condition:
    - condition: time
      weekday: [mon, tue, wed, thu, fri]
  action:
    - service: switch.turn_on
      target:
        entity_id: switch.YOUR_BUS_SCANNING_SWITCH

- alias: "Hanoi Bus: stop scanning on weekday mornings"
  trigger:
    - platform: time
      at: "09:00:00"
  condition:
    - condition: time
      weekday: [mon, tue, wed, thu, fri]
  action:
    - service: switch.turn_off
      target:
        entity_id: switch.YOUR_BUS_SCANNING_SWITCH
```

Replace `switch.YOUR_BUS_SCANNING_SWITCH` with the actual entity ID of your
Scanning switch (find it under **Settings → Devices & Services → Hanoi Bus
→ your device → Scanning**). A ready-to-paste copy is in
[`examples/bus_scanning_schedule.yaml`](examples/bus_scanning_schedule.yaml).

When scanning is off, all sensors on that device display `Update paused`
and no API calls are made until scanning is turned back on.

## Example automation

```yaml
automation:
  - alias: "Leave for the bus stop"
    trigger:
      - platform: numeric_state
        entity_id: sensor.49_doi_dien_nha_c6_kdt_my_dinh_i_duong_tran_huu_duc_eta
        below: 300  # 5 minutes, in seconds
    action:
      - service: notify.mobile_app_your_phone
        data:
          message: >
            Bus {{ state_attr(trigger.entity_id, 'buses')[0].plate }}
            arrives in {{ (states(trigger.entity_id) | int / 60) | round(1) }} minutes.
```
