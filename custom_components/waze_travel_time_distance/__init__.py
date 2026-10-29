"""The waze_travel_time_distance component."""

import asyncio
from copy import deepcopy
import logging

from pywaze.route_calculator import WazeRouteCalculator

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_REGION, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.httpx_client import get_async_client
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_BASE_COORDINATES,
    CONF_DISTANCE_FILTER,
    CONF_EXCL_FILTER,
    CONF_INCL_FILTER,
    CONF_TIME_DELTA,
    DEFAULT_DISTANCE_FILTER,
    DEFAULT_FILTER,
    DEFAULT_TIME_DELTA,
    DOMAIN,
    SEMAPHORE_KEY,
)
from .coordinator import WazeTravelTimeCoordinator
from .helpers import default_base_coordinates_for_region
from .services import async_setup_services

PLATFORMS = [Platform.SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up Waze."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Load the saved entities."""
    if SEMAPHORE_KEY not in hass.data:
        hass.data[SEMAPHORE_KEY] = asyncio.Semaphore(1)

    httpx_client = get_async_client(hass)
    client = WazeRouteCalculator(
        region=config_entry.data[CONF_REGION].upper(), client=httpx_client
    )
    config_entry.async_on_unload(client.close)

    coordinator = WazeTravelTimeCoordinator(hass, config_entry, client)
    config_entry.runtime_data = coordinator

    await coordinator.async_config_entry_first_refresh()

    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(config_entry, PLATFORMS)


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate saved entries without replacing user options or entity identities."""
    if config_entry.version > 2:
        _LOGGER.error(
            "Cannot migrate config entry from version %s", config_entry.version
        )
        return False

    if config_entry.version == 2 and config_entry.minor_version >= 3:
        return True

    options = deepcopy(dict(config_entry.options))
    if config_entry.version == 1:
        for key in (CONF_INCL_FILTER, CONF_EXCL_FILTER):
            filters = options.get(key)
            if filters is None or filters == "":
                options[key] = DEFAULT_FILTER.copy()
            elif isinstance(filters, str):
                options[key] = [filters]

    options.setdefault(CONF_DISTANCE_FILTER, DEFAULT_DISTANCE_FILTER)
    options.setdefault(CONF_TIME_DELTA, DEFAULT_TIME_DELTA.copy())
    options.setdefault(
        CONF_BASE_COORDINATES,
        default_base_coordinates_for_region(config_entry.data[CONF_REGION]),
    )
    hass.config_entries.async_update_entry(
        config_entry, options=options, version=2, minor_version=3
    )
    _LOGGER.debug("Migrated config entry to version 2.3")
    return True
