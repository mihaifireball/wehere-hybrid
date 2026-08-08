from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.const import PERCENTAGE, SIGNAL_STRENGTH_DECIBELS, UnitOfElectricPotential, UnitOfTime
from .const import DOMAIN, SENSOR_BATTERY, SENSOR_VOLTAGE, SENSOR_LAST_ADVERT, SENSOR_LOCK_EVENTS, SENSOR_RSSI, SENSOR_STATE

async def async_setup_entry(hass, entry, async_add_entities):
    entities = []
    for device in hass.data[DOMAIN][entry.entry_id].values():
        entities.extend([
            WeHereSensor(device, SENSOR_STATE, "Status"),
            WeHereOperationSensor(device),
            WeHereSensor(device, SENSOR_BATTERY, "Battery", SensorDeviceClass.BATTERY, PERCENTAGE),
            WeHereSensor(device, SENSOR_VOLTAGE, "Battery voltage", SensorDeviceClass.VOLTAGE, UnitOfElectricPotential.VOLT),
            WeHereSensor(device, SENSOR_LAST_ADVERT, "Time from last advert", None, UnitOfTime.SECONDS),
            WeHereSensor(device, SENSOR_LOCK_EVENTS, "Lock events counter"),
            WeHereSensor(device, SENSOR_RSSI, "Signal strength", SensorDeviceClass.SIGNAL_STRENGTH, SIGNAL_STRENGTH_DECIBELS),
        ])
    async_add_entities(entities)

class WeHereSensor(SensorEntity):
    _attr_should_poll = False

    def __init__(self, device, key, label, device_class=None, unit=None):
        self._device = device
        self._key = key
        self._attr_unique_id = f"{device.sn}_{key}"
        self._attr_name = f"{device.name} {label}"
        self._attr_device_class = device_class
        self._attr_native_unit_of_measurement = unit

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
    def native_value(self):
        if self._key == SENSOR_STATE:
            return self._device.state
        if self._key == SENSOR_BATTERY:
            return self._device.battery_perc
        if self._key == SENSOR_VOLTAGE:
            return self._device.voltage
        if self._key == SENSOR_LAST_ADVERT:
            return max(0, int(__import__("time").time()) - self._device.last_advert_time) if self._device.last_advert_time else None
        if self._key == SENSOR_LOCK_EVENTS:
            return self._device.lock_events
        if self._key == SENSOR_RSSI:
            return self._device.rssi
        return None


class WeHereOperationSensor(SensorEntity):
    """Native HA sensor exposing the lock operation lifecycle."""

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_name = "Operation"
    _attr_icon = "mdi:lock-clock"

    def __init__(self, device):
        self._device = device
        self._attr_unique_id = f"{device.sn}_operation"

    async def async_added_to_hass(self):
        self._device.add_callback(self.async_write_ha_state)

    async def async_will_remove_from_hass(self):
        self._device.remove_callback(self.async_write_ha_state)

    @property
    def available(self):
        self._device.check_availability()
        return self._device.available

    @property
    def device_info(self):
        return self._device.device_info

    @property
    def native_value(self):
        return self._device.operation_state
