"""Saved configuration must survive upgrades."""

from copy import deepcopy
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.waze_travel_time_distance import async_migrate_entry
from custom_components.waze_travel_time_distance.const import (
    CONF_BASE_COORDINATES,
    CONF_DISTANCE_FILTER,
    CONF_EXCL_FILTER,
    CONF_INCL_FILTER,
    CONF_TIME_DELTA,
    DEFAULT_OPTIONS,
    DOMAIN,
)
from custom_components.waze_travel_time_distance.helpers import (
    default_base_coordinates_for_region,
)

from .conftest import CONFIG


@pytest.mark.parametrize(("version", "minor"), [(1, 1), (2, 1), (2, 2), (2, 3)])
@pytest.mark.parametrize("region", ["us", "NA", "EU", "IL", "AU"])
async def test_migration_preserves_options_and_identity(hass, version, minor, region):
    """Add defaults without replacing filters, user settings, or config data."""
    options = deepcopy(DEFAULT_OPTIONS)
    options.pop(CONF_TIME_DELTA)
    options.update(
        {
            CONF_DISTANCE_FILTER: "42.5",
            CONF_INCL_FILTER: "Main" if version == 1 else ["Main"],
            CONF_EXCL_FILTER: "Toll" if version == 1 else ["Toll"],
            "units": "imperial",
            "custom_option": "keep me",
        }
    )
    if minor == 3:
        options[CONF_TIME_DELTA] = {"minutes": 0}
        options[CONF_BASE_COORDINATES] = default_base_coordinates_for_region(region)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="My route",
        unique_id="existing",
        data=CONFIG | {"region": region},
        options=options,
        version=version,
        minor_version=minor,
    )
    entry.add_to_hass(hass)
    before = (entry.entry_id, entry.unique_id, entry.title, dict(entry.data))
    assert await async_migrate_entry(hass, entry)
    assert (entry.version, entry.minor_version) == (2, 3)
    assert entry.options[CONF_DISTANCE_FILTER] == "42.5"
    assert entry.options[CONF_INCL_FILTER] == ["Main"]
    assert entry.options[CONF_EXCL_FILTER] == ["Toll"]
    assert entry.options["units"] == "imperial"
    assert entry.options["custom_option"] == "keep me"
    assert entry.options[CONF_TIME_DELTA] == {"minutes": 0}
    assert entry.options[CONF_BASE_COORDINATES] == default_base_coordinates_for_region(
        region
    )
    assert (entry.entry_id, entry.unique_id, entry.title, dict(entry.data)) == before
    with patch.object(hass.config_entries, "async_update_entry") as update:
        assert await async_migrate_entry(hass, entry)
        update.assert_not_called()


@pytest.mark.parametrize("filters", [None, "", ["Main"]])
async def test_legacy_missing_filters_and_distance(hass, filters):
    """Handle blank strings and already-normalized lists without double wrapping."""
    options = deepcopy(DEFAULT_OPTIONS)
    options.pop(CONF_DISTANCE_FILTER)
    options.pop(CONF_TIME_DELTA)
    options[CONF_INCL_FILTER] = options[CONF_EXCL_FILTER] = filters
    entry = MockConfigEntry(domain=DOMAIN, data=CONFIG, options=options, version=1)
    entry.add_to_hass(hass)
    assert await async_migrate_entry(hass, entry)
    assert entry.options[CONF_DISTANCE_FILTER] == ""
    assert entry.options[CONF_INCL_FILTER] == (filters or [""])
    assert entry.options[CONF_EXCL_FILTER] == (filters or [""])


async def test_migration_preserves_newer_options(hass):
    """A partially upgraded entry retains configured departure and base values."""
    options = deepcopy(DEFAULT_OPTIONS) | {
        CONF_TIME_DELTA: {"hours": 2},
        CONF_BASE_COORDINATES: {"latitude": 1.23, "longitude": 4.56},
    }
    entry = MockConfigEntry(
        domain=DOMAIN, data=CONFIG, options=options, version=2, minor_version=1
    )
    entry.add_to_hass(hass)
    assert await async_migrate_entry(hass, entry)
    assert dict(entry.options) == options


async def test_future_major_version_is_not_downgraded(hass):
    """Reject unsupported future schemas without modifying the entry."""
    entry = MockConfigEntry(domain=DOMAIN, data=CONFIG, version=3)
    entry.add_to_hass(hass)
    assert not await async_migrate_entry(hass, entry)
    assert entry.version == 3
