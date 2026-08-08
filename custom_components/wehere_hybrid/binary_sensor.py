from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass
from .const import DOMAIN

async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([
        WeHereLowBattery(device)
        for device in hass.data[DOMAIN][entry.entry_id].values()
    ])

class WeHereLowBattery(BinarySensorEntity):
    _attr_should_poll = False
    _attr_device_class = BinarySensorDeviceClass.BATTERY

    def __init__(self, device):
        self._device = device
        self._attr_unique_id = f"{device.sn}_battery_low"
        self._attr_name = f"{device.name} Battery low"

    async def async_added_to_hass(self):
        self._device.add_callback(self.async_write_ha_state)

    @property
    def available(self):
        self._device.check_availability()
        return self._device.available

    @property
    def device_info(self):
        return self._device.device_info

    @property
    def is_on(self):
        return self._device.is_low_battery
