"""Configuration UI, options, reconfiguration, and translated labels."""

import json
from pathlib import Path

import pytest
from pywaze.route_calculator import WRCError

from custom_components.waze_travel_time_distance.config_flow import default_options
from custom_components.waze_travel_time_distance.const import (
    CONF_BASE_COORDINATES,
    CONF_DISTANCE_FILTER,
    CONF_EXCL_FILTER,
    CONF_INCL_FILTER,
    CONF_REALTIME,
    CONF_TIME_DELTA,
    DOMAIN,
)
from homeassistant.config_entries import SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.translation import async_get_translations
from homeassistant.setup import async_setup_component
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM

from .conftest import CONFIG


async def test_new_entry_defaults(hass, mock_routes):
    """Use home coordinates for new entries without changing existing defaults."""
    hass.config.latitude = 12.34
    hass.config.longitude = 56.78
    hass.config.units = US_CUSTOMARY_SYSTEM
    form = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert form["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        form["flow_id"], CONFIG | {"region": "us"}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Commute"
    assert result["data"] == CONFIG
    entry = result["result"]
    assert (entry.version, entry.minor_version) == (2, 3)
    assert entry.options[CONF_TIME_DELTA] == {"minutes": 0}
    assert entry.options[CONF_DISTANCE_FILTER] == ""
    assert entry.options[CONF_REALTIME] is True
    assert entry.options["units"] == "imperial"
    assert entry.options[CONF_BASE_COORDINATES] == {
        "latitude": 12.34,
        "longitude": 56.78,
    }


def test_defaults_are_not_shared(hass):
    """Editing an entry's nested options must not change other entries."""
    first = default_options(hass)
    first[CONF_TIME_DELTA]["minutes"] = 90
    first[CONF_INCL_FILTER].append("Main")
    assert default_options(hass)[CONF_TIME_DELTA] == {"minutes": 0}
    assert default_options(hass)[CONF_INCL_FILTER] == [""]


async def test_invalid_config_can_be_retried(hass, mock_routes):
    """Return to the form on expected errors, preserving entered values."""
    mock_routes.side_effect = WRCError("cannot resolve")
    form = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        form["flow_id"], CONFIG | {"region": "us"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_options_forward_new_and_preserved_fields(hass, entry, mock_routes):
    """Accept new options alongside the custom filter and existing toggles."""
    assert await hass.config_entries.async_setup(entry.entry_id)
    form = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        form["flow_id"],
        {
            "vehicle_type": "taxi",
            "units": "imperial",
            CONF_DISTANCE_FILTER: "10",
            CONF_INCL_FILTER: ["Main"],
            CONF_EXCL_FILTER: ["Toll"],
            CONF_TIME_DELTA: {"minutes": -15},
            CONF_BASE_COORDINATES: {"latitude": 1.23, "longitude": 4.56},
            CONF_REALTIME: False,
            "avoid_ferries": True,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await entry.runtime_data.async_refresh()
    assert entry.runtime_data.data.route == "Short second"
    assert entry.runtime_data.data.distance == pytest.approx(4.9709695)
    args = mock_routes.call_args.kwargs
    assert args["time_delta"] == -15
    assert args["base_coords"] == (1.23, 4.56)
    assert args["vehicle_type"] == "TAXI"
    assert args["real_time"] is False
    assert args["avoid_ferries"] is True


async def test_options_clearing_optional_values(hass, entry, mock_routes):
    """Clearing optional fields resets filters and offset without missing keys."""
    assert await hass.config_entries.async_setup(entry.entry_id)
    form = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        form["flow_id"], {"vehicle_type": "car", "units": "metric"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_TIME_DELTA] == {"minutes": 0}
    assert entry.options[CONF_DISTANCE_FILTER] == ""
    assert entry.options[CONF_INCL_FILTER] == [""]
    assert entry.options[CONF_EXCL_FILTER] == [""]
    assert CONF_BASE_COORDINATES not in entry.options
    await entry.runtime_data.async_refresh()
    assert mock_routes.call_args.kwargs["base_coords"] is None


async def test_reconfigure_keeps_options_and_entity(hass, entry, mock_routes):
    """Changing endpoints or the name preserves the entity ID and options."""
    hass.config_entries.async_update_entry(
        entry, options=dict(entry.options) | {CONF_DISTANCE_FILTER: "10"}
    )
    options = dict(entry.options)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("sensor", DOMAIN, entry.entry_id)
    form = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        form["flow_id"],
        CONFIG | {"name": "New commute", "origin": "42,-72", "region": "us"},
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.title == "New commute"
    assert entry.data["origin"] == "42,-72"
    assert dict(entry.options) == options
    assert registry.async_get_entity_id("sensor", DOMAIN, entry.entry_id) == entity_id
    assert hass.states.get(entity_id).state == "12.75"


async def test_translations_are_readable(hass):
    """Exercise HA's translation loader for configuration, action, and errors."""
    assert await async_setup_component(hass, DOMAIN, {})
    prefix = f"component.{DOMAIN}."
    for category, suffix in [
        ("config", "step.user.data.origin"),
        ("options", "step.init.data.distance_filter"),
        ("services", "get_travel_times.fields.distance_filter.name"),
        ("exceptions", "connection_error.message"),
    ]:
        translations = await async_get_translations(hass, "en", category, {DOMAIN})
        assert translations[prefix + category + "." + suffix]
        assert all("[%key:" not in value for value in translations.values())
    root = Path(__file__).resolve().parents[1] / "custom_components" / DOMAIN
    assert json.loads((root / "strings.json").read_text()) == json.loads(
        (root / "translations/en.json").read_text()
    )
