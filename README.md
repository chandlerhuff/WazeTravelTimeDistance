# Waze Travel Time with Distance Filter

A custom Home Assistant integration that calculates travel time with an optional maximum route distance. Version **0.9.0** is based on Home Assistant **2026.10.4** and uses the same `pywaze==1.2.4` dependency as its built-in Waze integration.

## Installation and upgrading

Requires **Home Assistant 2026.10.4 or newer**. This release is tested against 2026.10.4; development-only Home Assistant APIs are not required.

Add this repository as a custom **Integration** repository in HACS, install **Waze Travel Time Distance Filtered**, and restart Home Assistant. Alternatively, copy `custom_components/waze_travel_time_distance` into your Home Assistant `custom_components` directory and restart. Add the integration through **Settings → Devices & services**.

When upgrading, keep existing integration entries. Their settings migrate automatically to configuration schema 2.3. Names, entity unique IDs, device identifiers, and the `waze_travel_time_distance` domain are preserved, so existing automations can keep using them. Back up your configuration before upgrading; restoring the backup also restores the previous entry schema if you need to roll back.

## Route options

| Option | Behavior |
| --- | --- |
| Maximum distance | Selects routes **strictly shorter** than the limit, always in **kilometers**, even with imperial output. Blank disables it. Invalid text logs a warning and skips this filter. |
| Streets to include/exclude | Matches exact street names. Inclusion matches any listed street; exclusion rejects a route containing any excluded street. |
| Units | Controls the returned distance: kilometers for metric, miles for imperial. Travel time remains in minutes. |
| Time delta | Calculates travel time at an offset from now. Positive durations are in the future; negative durations are in the past. Defaults to zero. |
| Base coordinates | Biases ambiguous address searches toward this location. New entries default to Home Assistant's home coordinates; migrated entries retain Waze's regional defaults. Clearing the option lets Waze choose its default. |

After filtering, the first surviving Waze route is selected. If no routes survive, the sensor's duration, distance, and route are unknown. Polling remains every five minutes, with requests serialized across this integration's sensors and spaced by half a second.

## Get travel times action

The response-only action `waze_travel_time_distance.get_travel_times` returns `{"routes": [...]}`. Each route contains `name`, `distance`, `duration`, and `street_names`. Existing action inputs remain supported; `time_delta` and `base_coordinates` are optional.

```yaml
action: waze_travel_time_distance.get_travel_times
data:
  origin: zone.home
  destination: "40.7128,-74.0060"
  region: us
  units: imperial
  distance_filter: "50"
  time_delta:
    hours: 1
    minutes: 30
  base_coordinates:
    latitude: 40.7128
    longitude: -74.0060
response_variable: waze_routes
```

The 50 km limit applies before distances are converted to miles. The action defaults to statistical travel times (`realtime: false`); sensors default to realtime travel times. Region choices remain `us`, `na`, `eu`, `il`, and `au`.

## Development and verification

Use Python **3.14.2 or newer** with the pinned Home Assistant test dependencies:

```sh
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements_test.txt
.venv/bin/python -m pytest
.venv/bin/ruff check custom_components tests
.venv/bin/ruff format --check custom_components tests
```

Tests mock Waze requests and block network sockets. They cover filter boundaries, options and actions, migrations, entity identity, client cleanup, failures, and coexistence with built-in Waze. GitHub Actions also runs hassfest and HACS validation.

Validation exceptions: hassfest's requirements plugin requires minimum versions for shared dependencies, so it is excluded to retain the requested exact `pywaze==1.2.4` baseline pin. A packaging test checks that this pin matches built-in Waze and the installed library. Future Home Assistant releases may require updating this pin together with upstream. HACS validation excludes existing repository-listing metadata (brand assets, description, license, and topics); it still validates the integration package.

For a manual upgrade smoke test on a Home Assistant installation: record an existing entity ID and distance limit, install the update, restart, confirm the same entity and options, change the new route options, and call the action with and without a distance limit. Verify configuration labels display normally and the logs contain no migration or resource-cleanup errors.

## Credits

Based on the [Home Assistant Waze Travel Time integration](https://github.com/home-assistant/core/tree/2026.10.4/homeassistant/components/waze_travel_time). The custom maximum-distance filter is retained in both sensor updates and action responses.
