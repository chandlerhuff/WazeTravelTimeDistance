"""Exercise Home Assistant setup, service registration, and resource cleanup."""

from copy import deepcopy
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pywaze.route_calculator import WazeRouteCalculator, WRCError

from custom_components.waze_travel_time_distance.const import (
    CONF_BASE_COORDINATES,
    CONF_DISTANCE_FILTER,
    CONF_TIME_DELTA,
    DEFAULT_OPTIONS,
    DOMAIN,
    SEMAPHORE_KEY,
)
from custom_components.waze_travel_time_distance.helpers import is_valid_config_entry
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.httpx_client import get_async_client
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.setup import async_setup_component

from .conftest import CONFIG


async def test_sensor_upgrade_reload_and_identity(hass, mock_routes):
    """Upgrade a saved sensor and keep its registry identity across reloads."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Commute",
        data=CONFIG,
        options=deepcopy(DEFAULT_OPTIONS) | {CONF_DISTANCE_FILTER: "10"},
        version=2,
        minor_version=1,
    )
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    registered = registry.async_get_or_create(
        "sensor",
        DOMAIN,
        entry.entry_id,
        suggested_object_id="my_existing_commute",
        config_entry=entry,
    )
    with patch.object(WazeRouteCalculator, "close", new_callable=AsyncMock) as close:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.LOADED
        assert (entry.version, entry.minor_version) == (2, 3)
        state = hass.states.get(registered.entity_id)
        assert state.state == "12.75"
        assert state.attributes["distance"] == 8
        assert state.attributes["duration"] == 12.75
        assert state.attributes["route"] == "Short second"
        assert state.attributes["origin"] == CONFIG["origin"]
        assert state.attributes["destination"] == CONFIG["destination"]
        assert state.attributes["unit_of_measurement"] == "min"
        assert registry.async_get(registered.entity_id).unique_id == entry.entry_id
        device = dr.async_get(hass).async_get_device_by_identifier(
            (DOMAIN, DOMAIN), entry.entry_id
        )
        assert device is not None
        assert entry.runtime_data.update_interval.total_seconds() == 300

        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        close.assert_awaited_once()
        assert hass.states.get(registered.entity_id).state == "12.75"
        assert entry.options[CONF_DISTANCE_FILTER] == "10"
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert close.await_count == 2


async def test_service_registered_without_entries(hass, mock_routes):
    """The response-only action exists independently of successful sensor setup."""
    assert await async_setup_component(hass, DOMAIN, {})
    assert hass.services.has_service(DOMAIN, "get_travel_times")
    with patch.object(WazeRouteCalculator, "close", new_callable=AsyncMock) as close:
        response = await hass.services.async_call(
            DOMAIN,
            "get_travel_times",
            {
                "origin": "zone.home",
                "destination": "An address",
                "region": "us",
                "units": "imperial",
                CONF_DISTANCE_FILTER: "10",
                CONF_TIME_DELTA: {"hours": 1, "minutes": 30},
                CONF_BASE_COORDINATES: {"latitude": 40.5, "longitude": -73.5},
            },
            blocking=True,
            return_response=True,
        )
        close.assert_awaited_once()
    assert response == {
        "routes": [
            {
                "name": "Short second",
                "distance": pytest.approx(4.9709695),
                "duration": 12.75,
                "street_names": ["Main", "Park"],
            }
        ]
    }
    assert mock_routes.call_args.args[1] == "An address"
    assert mock_routes.call_args.kwargs["time_delta"] == 90
    assert mock_routes.call_args.kwargs["base_coords"] == (40.5, -73.5)
    assert mock_routes.call_args.kwargs["real_time"] is False


@pytest.mark.parametrize("distance", ["", "bad", "8"])
async def test_legacy_service_inputs(hass, mock_routes, distance):
    """Old service payloads still work when the new fields are omitted."""
    assert await async_setup_component(hass, DOMAIN, {})
    response = await hass.services.async_call(
        DOMAIN,
        "get_travel_times",
        {
            "origin": CONFIG["origin"],
            "destination": CONFIG["destination"],
            "region": "us",
            CONF_DISTANCE_FILTER: distance,
        },
        blocking=True,
        return_response=True,
    )
    assert len(response["routes"]) == (0 if distance == "8" else 3)
    assert mock_routes.call_args.kwargs["time_delta"] == 0
    assert mock_routes.call_args.kwargs["base_coords"] is None


@pytest.mark.parametrize(
    "error", [WRCError("bad response"), httpx.ConnectError("offline")]
)
async def test_service_closes_calculator_after_failure(hass, mock_routes, error):
    """Exceptions do not leak temporary calculators."""
    assert await async_setup_component(hass, DOMAIN, {})
    mock_routes.side_effect = error
    with (
        patch.object(WazeRouteCalculator, "close", new_callable=AsyncMock) as close,
        pytest.raises(UpdateFailed) as raised,
    ):
        await hass.services.async_call(
            DOMAIN,
            "get_travel_times",
            {
                "origin": CONFIG["origin"],
                "destination": CONFIG["destination"],
                "region": "us",
            },
            blocking=True,
            return_response=True,
        )
    assert raised.value.translation_domain == DOMAIN
    close.assert_awaited_once()


async def test_initial_refresh_failure_closes_calculator(hass, entry, mock_routes):
    """Home Assistant runs unload callbacks after a failed initial refresh."""
    mock_routes.side_effect = httpx.ConnectError("offline")
    with patch.object(WazeRouteCalculator, "close", new_callable=AsyncMock) as close:
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.SETUP_RETRY
        close.assert_awaited_once()
        assert not hass.data[SEMAPHORE_KEY].locked()


@pytest.mark.parametrize(
    "error", [None, WRCError("bad route"), httpx.ConnectError("offline")]
)
async def test_config_validation_cleanup(hass, mock_routes, error):
    """Validation closes its temporary calculator on success and failure."""
    mock_routes.side_effect = error
    with patch.object(WazeRouteCalculator, "close", new_callable=AsyncMock) as close:
        assert await is_valid_config_entry(
            hass, CONFIG["origin"], CONFIG["destination"], "US"
        ) is (error is None)
        close.assert_awaited_once()


async def test_real_cleanup_keeps_shared_http_client_open(hass):
    """Use the actual pywaze cleanup implementation with HA's pooled client."""
    shared_client = get_async_client(hass)
    async with WazeRouteCalculator(region="US", client=shared_client) as calculator:
        assert calculator.client is shared_client
    assert not shared_client.is_closed


async def test_builtin_coexistence(hass, entry, mock_routes):
    """Load both integrations with independent identities, services, and locks."""
    builtin = MockConfigEntry(
        domain="waze_travel_time",
        title="Built-in commute",
        data=CONFIG,
        options=deepcopy(DEFAULT_OPTIONS),
        version=2,
        minor_version=3,
    )
    builtin.add_to_hass(hass)
    assert await hass.config_entries.async_setup(builtin.entry_id)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    from homeassistant.components.waze_travel_time.const import (
        SEMAPHORE_KEY as BUILTIN_KEY,
    )

    assert hass.data[SEMAPHORE_KEY] is not hass.data[BUILTIN_KEY]
    assert hass.services.has_service(DOMAIN, "get_travel_times")
    assert hass.services.has_service("waze_travel_time", "get_travel_times")
    registry = er.async_get(hass)
    assert registry.async_get_entity_id("sensor", DOMAIN, entry.entry_id)
    assert registry.async_get_entity_id("sensor", "waze_travel_time", builtin.entry_id)
