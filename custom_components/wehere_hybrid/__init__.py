from __future__ import annotations

import asyncio
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from .cloud import WeHereCloud
from .device import WeHereDevice
from .const import (
    DOMAIN,
    CONF_DEVICE_CONFIGS,
    CONF_RETRIES_NUM,
    DEFAULT_RETRIES_NUM,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["lock", "sensor", "binary_sensor"]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    return True


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry
) -> bool:
    cloud = WeHereCloud(hass, entry)
    devices = {}

    for sn, cfg in entry.data[CONF_DEVICE_CONFIGS].items():
        dev = WeHereDevice(
            hass=hass,
            cloud=cloud,
            config=cfg,
            retries=entry.options.get(
                CONF_RETRIES_NUM,
                DEFAULT_RETRIES_NUM,
            ),
        )
        await dev.async_start()
        devices[sn] = dev

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = devices

    for platform in PLATFORMS:
        await hass.config_entries.async_forward_entry_setups(
            entry, [platform]
        )

    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: ConfigEntry
) -> bool:
    data = hass.data.get(DOMAIN, {}).pop(entry.entry_id, {})

    await asyncio.gather(*(d.async_stop() for d in data.values()))

    if not hass.data.get(DOMAIN):
        hass.data.pop(DOMAIN, None)

    return True


async def async_migrate_entry(
    hass: HomeAssistant, entry: ConfigEntry
) -> bool:
    return True
