from homeassistant.components.diagnostics import async_redact_data
from .const import DOMAIN

TO_REDACT = {"appKey", "newSninfo", "token", "userId", "email", "gateway"}

async def async_get_config_entry_diagnostics(hass, entry):
    result = {}
    for sn, d in hass.data[DOMAIN][entry.entry_id].items():
        result[sn] = {
            "name": d.name,
            "model": d.config.get("deviceType"),
            "firmware": d.config.get("firmwareVersion"),
            "state": d.state,
            "available": d.available,
            "battery": d.battery_perc,
            "voltage": d.voltage,
            "rssi": d.rssi,
            "lock_events": d.lock_events,
            "last_advert_time": d.last_advert_time,
            "last_command_transport": d.last_command_transport,
            "last_command_error": d.last_command_error,
            "last_command_time": d.last_command_time,
        }
    return async_redact_data(result, TO_REDACT)
