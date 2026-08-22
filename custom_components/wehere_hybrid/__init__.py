from __future__ import annotations

import asyncio
import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import config_validation as cv
from .cloud import WeHereCloud
from .device import WeHereDevice
from .const import (
    DOMAIN, CONF_DEVICE_CONFIGS, CONF_RETRIES_NUM, DEFAULT_RETRIES_NUM,
    CONF_COMMAND_MODE, DEFAULT_COMMAND_MODE,
)

_LOGGER = logging.getLogger(__name__)
PLATFORMS = ["lock", "sensor", "binary_sensor"]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    return True

async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    cloud = WeHereCloud(hass, entry)
    try:
        await cloud.get_devices()
    except ConfigEntryAuthFailed:
        raise

    command_mode = entry.options.get(CONF_COMMAND_MODE, DEFAULT_COMMAND_MODE)
    retries = entry.options.get(CONF_RETRIES_NUM, DEFAULT_RETRIES_NUM)
    devices = {}
    for sn, cfg in entry.data[CONF_DEVICE_CONFIGS].items():
        dev = WeHereDevice(
            hass=hass, cloud=cloud, config=cfg, retries=retries, command_mode=command_mode
        )
        await dev.async_start()
        devices[sn] = dev

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = devices
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False
    data = hass.data.get(DOMAIN, {}).pop(entry.entry_id, {})
    await asyncio.gather(*(device.async_stop() for device in data.values()))
    if not hass.data.get(DOMAIN):
        hass.data.pop(DOMAIN, None)
    return True

async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return True
