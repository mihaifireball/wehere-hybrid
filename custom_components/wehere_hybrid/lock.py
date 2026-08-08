from homeassistant.components.lock import LockEntity, LockState
from homeassistant.helpers.entity import EntityCategory
from .const import DOMAIN, LOCKED, UNLOCKED, OPERATING, FAILED

async def async_setup_entry(hass, entry, async_add_entities):
    entities = []
    for device in hass.data[DOMAIN][entry.entry_id].values():
        entities.append(WeHereLock(device))
    async_add_entities(entities)

class WeHereLock(LockEntity):
    _attr_should_poll = False

    def __init__(self, device):
        self._device = device
        self._attr_unique_id = f"{device.sn}_lock"
        self._attr_name = device.name

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
    def is_locked(self):
        return self._device.curr_state == LOCKED

    @property
    def state(self):
        if self._device.curr_state == LOCKED:
            return LockState.LOCKED
        if self._device.curr_state == UNLOCKED:
            return LockState.UNLOCKED
        return LockState.JAMMED if self._device.curr_state in (OPERATING, FAILED) else None

    @property
    def extra_state_attributes(self):
        return {
            "operation_state": self._device.operation_state,
            "last_command_transport": self._device.last_command_transport,
            "last_command_error": self._device.last_command_error,
        }

    @property
    def icon(self):
        return {
            LOCKED: "mdi:lock",
            UNLOCKED: "mdi:lock-open-variant",
            OPERATING: "mdi:lock-reset",
            FAILED: "mdi:lock-alert",
        }.get(self._device.curr_state, "mdi:lock-alert")

    async def async_lock(self, **kwargs):
        await self._device.async_operate(unlock=False)

    async def async_unlock(self, **kwargs):
        await self._device.async_operate(unlock=True)
