"""Regression tests for filtering and coordinator behavior."""

import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest
from pywaze.route_calculator import WazeRouteCalculator, WRCError

from custom_components.waze_travel_time_distance.const import (
    CONF_DISTANCE_FILTER,
    CONF_EXCL_FILTER,
    CONF_TIME_DELTA,
    DOMAIN,
    SEMAPHORE_KEY,
)
from custom_components.waze_travel_time_distance.coordinator import (
    WazeTravelTimeCoordinator,
    async_get_travel_times,
)
from homeassistant.helpers.update_coordinator import UpdateFailed

from .conftest import ROUTES


async def get_routes(**kwargs):
    """Call the shared filtering helper without network access."""
    client = AsyncMock(spec=WazeRouteCalculator)
    client.calc_routes.return_value = ROUTES
    return await async_get_travel_times(
        client=client,
        origin="40,-74",
        destination="41,-73",
        vehicle_type="car",
        avoid_toll_roads=False,
        avoid_subscription_roads=False,
        avoid_ferries=False,
        realtime=True,
        **kwargs,
    )


@pytest.mark.parametrize(
    ("limit", "names"),
    [
        ("7.9", []),
        ("8", []),
        ("8.01", ["Short second"]),
        ("15", ["Short second"]),
        ("30.1", ["Long first", "Short second", "Medium third"]),
        ("", ["Long first", "Short second", "Medium third"]),
        (None, ["Long first", "Short second", "Medium third"]),
        ("invalid", ["Long first", "Short second", "Medium third"]),
        ("0", []),
        ("-1", []),
    ],
)
async def test_distance_filter(limit, names, caplog):
    """Keep the strict kilometer threshold and invalid-text fallback."""
    routes = await get_routes(distance_filter=limit)
    assert [route.name for route in routes] == names
    assert ("Invalid distance_filter" in caplog.text) == (limit == "invalid")


async def test_imperial_filter_is_still_kilometers():
    """Reject 15 km even though its miles value is below the 10 km limit."""
    routes = await get_routes(distance_filter="10", units="imperial")
    assert len(routes) == 1
    assert routes[0].name == "Short second"
    assert routes[0].distance == pytest.approx(4.9709695)
    assert routes[0].duration == 12.75
    assert ROUTES[1].distance == 8


@pytest.mark.parametrize(
    ("include", "exclude", "limit", "names"),
    [
        (["Main"], ["Toll"], "20", ["Short second"]),
        (["Main", "Bypass"], [], "20", ["Short second", "Medium third"]),
        (["main"], [], "", []),
        ([""], ["Main"], "", ["Medium third"]),
        ([], [], "", ["Long first", "Short second", "Medium third"]),
    ],
)
async def test_street_and_distance_filters(include, exclude, limit, names):
    """Keep exact street matching and the original route order."""
    routes = await get_routes(
        incl_filters=include, excl_filters=exclude, distance_filter=limit
    )
    assert [route.name for route in routes] == names


async def test_routes_without_distance_are_excluded_by_limit():
    """A route without a distance cannot pass a distance threshold."""
    client = AsyncMock(spec=WazeRouteCalculator)
    client.calc_routes.return_value = [
        type(ROUTES[0])(name="Unknown", distance=None, duration=5, street_names=[])
    ]
    assert not await async_get_travel_times(
        client,
        "40,-74",
        "41,-73",
        "car",
        False,
        False,
        False,
        True,
        distance_filter="10",
    )


@pytest.mark.parametrize(
    ("error", "key"),
    [
        (WRCError("bad response"), "update_error"),
        (httpx.ConnectError("offline"), "connection_error"),
    ],
)
async def test_translated_errors(error, key):
    """Wrap expected upstream failures with the custom translation domain."""
    client = AsyncMock(spec=WazeRouteCalculator)
    client.calc_routes.side_effect = error
    with pytest.raises(UpdateFailed) as raised:
        await async_get_travel_times(
            client, "40,-74", "41,-73", "car", False, False, False, True
        )
    assert raised.value.translation_domain == DOMAIN
    assert raised.value.translation_key == key
    assert raised.value.__cause__ is error


async def test_coordinator_options_and_no_routes(hass, entry):
    """Forward all options and clear the result when no routes survive."""
    hass.data[SEMAPHORE_KEY] = asyncio.Semaphore(1)
    hass.config_entries.async_update_entry(
        entry,
        options=dict(entry.options)
        | {
            CONF_DISTANCE_FILTER: "20",
            CONF_EXCL_FILTER: ["Toll"],
            CONF_TIME_DELTA: {"hours": -1, "minutes": -30},
        },
    )
    client = AsyncMock(spec=WazeRouteCalculator)
    client.calc_routes.return_value = ROUTES
    coordinator = WazeTravelTimeCoordinator(hass, entry, client)
    data = await coordinator._async_update_data()
    assert (data.route, data.distance, data.duration) == ("Short second", 8, 12.75)
    assert client.calc_routes.call_args.kwargs["time_delta"] == -90
    assert client.calc_routes.call_args.kwargs["base_coords"] == (40.0, -74.0)

    hass.config_entries.async_update_entry(
        entry, options=dict(entry.options) | {CONF_DISTANCE_FILTER: "8"}
    )
    data = await coordinator._async_update_data()
    assert data.route is data.distance is data.duration is None
    assert data.origin == "40.0,-74.0"
    assert data.destination == "41.0,-73.0"
    assert not hass.data[SEMAPHORE_KEY].locked()


@pytest.mark.parametrize("invalid_origin", [False, True])
async def test_semaphore_released_on_failure(hass, entry, invalid_origin):
    """A failed sensor update must not block every other configured sensor."""
    hass.data[SEMAPHORE_KEY] = asyncio.Semaphore(1)
    client = AsyncMock(spec=WazeRouteCalculator)
    client.calc_routes.side_effect = httpx.ConnectError("offline")
    if invalid_origin:
        hass.states.async_set("device_tracker.missing", "device_tracker.missing")
        hass.config_entries.async_update_entry(
            entry, data=dict(entry.data) | {"origin": "device_tracker.missing"}
        )
    coordinator = WazeTravelTimeCoordinator(hass, entry, client)
    with pytest.raises(UpdateFailed) as raised:
        await coordinator._async_update_data()
    assert raised.value.translation_key == (
        "unknown_origin_or_destination" if invalid_origin else "connection_error"
    )
    assert not hass.data[SEMAPHORE_KEY].locked()
