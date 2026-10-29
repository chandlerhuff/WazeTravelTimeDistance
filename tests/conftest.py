"""Shared fixtures using Home Assistant 2026.10.4."""

from copy import deepcopy
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pywaze.route_calculator import CalcRoutesResponse

from custom_components.waze_travel_time_distance import coordinator
from custom_components.waze_travel_time_distance.const import (
    CONF_BASE_COORDINATES,
    DEFAULT_OPTIONS,
    DOMAIN,
)

CONFIG = {
    "name": "Commute",
    "origin": "40.0,-74.0",
    "destination": "41.0,-73.0",
    "region": "US",
}
ROUTES = [
    CalcRoutesResponse(
        name="Long first", distance=30, duration=18.5, street_names=["Main", "Toll"]
    ),
    CalcRoutesResponse(
        name="Short second", distance=8, duration=12.75, street_names=["Main", "Park"]
    ),
    CalcRoutesResponse(
        name="Medium third", distance=15, duration=14.5, street_names=["Bypass"]
    ),
]


@pytest.fixture(autouse=True)
def custom_integration(enable_custom_integrations, monkeypatch):
    """Load custom components and avoid real rate-limit delays in tests."""
    monkeypatch.setattr(coordinator, "SECONDS_BETWEEN_API_CALLS", 0)


@pytest.fixture
def mock_routes():
    """Mock Waze, leaving Home Assistant setup and registries real."""
    with patch(
        "pywaze.route_calculator.WazeRouteCalculator.calc_routes",
        new_callable=AsyncMock,
        return_value=deepcopy(ROUTES),
    ) as mock:
        yield mock


@pytest.fixture
def entry(hass):
    """A saved entry with the current schema."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Commute",
        data=CONFIG,
        options=deepcopy(DEFAULT_OPTIONS)
        | {CONF_BASE_COORDINATES: {"latitude": 40.0, "longitude": -74.0}},
        version=2,
        minor_version=3,
    )
    entry.add_to_hass(hass)
    return entry
