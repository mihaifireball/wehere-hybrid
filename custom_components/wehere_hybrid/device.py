from __future__ import annotations

import asyncio

import json
import time
from typing import Callable

from homeassistant.components import mqtt
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC

from .codes import AirbnkCodesGenerator
STATE_CONFIRM_TIMEOUT = 60

from .const import (
    ADVERT_TOPIC, COMMAND_RESULT_TOPIC, TELEMETRY_TOPIC,
    LOCKED, UNLOCKED, JAMMED, OPERATING, FAILED, STATE_STRINGS,
    SENSOR_STATE, SENSOR_BATTERY, SENSOR_VOLTAGE, SENSOR_LAST_ADVERT,
    SENSOR_LOCK_EVENTS, SENSOR_RSSI, SENSOR_BATTERY_LOW,
    MAX_NORECEIVE_TIME, CONF_MAC_ADDRESS, CONF_MQTT_TOPIC,
)

class WeHereDevice:
    def __init__(self, hass: HomeAssistant, cloud, config, retries=3):
        self.hass = hass
        self.cloud = cloud
        self.config = config
        self.sn = config["sn"]
        self.retries = retries
        self.generator = AirbnkCodesGenerator()
        self.generator.decrypt_keys(config["newSninfo"], config["appKey"])

        self.curr_state = UNLOCKED
        self.voltage = None
        self.battery_perc = None
        self.is_low_battery = None
        self.lock_events = 0
        self.rssi = None
        self.last_advert_time = 0
        self.last_telemetry_time = 0
        self.available = False
        self.last_command = None
        self.last_command_transport = None
        self.last_command_error = None
        self.last_command_time = None
        self.operation_state = "idle"
        self._state_event = asyncio.Event()
        self._callbacks: set[Callable] = set()
        self._unsub = []

    @property
    def name(self):
        return self.config.get("deviceName", self.sn)

    @property
    def state(self):
        return STATE_STRINGS[self.curr_state]

    @property
    def device_info(self):
        return {
            "identifiers": {("wehere_hybrid", self.sn)},
            "manufacturer": "WeHere",
            "model": self.config.get("deviceType", "Airbnk"),
            "name": self.name,
            "sw_version": self.config.get("firmwareVersion"),
            "connections": {(CONNECTION_NETWORK_MAC, self.config[CONF_MAC_ADDRESS])},
        }

    def add_callback(self, cb):
        self._callbacks.add(cb)

    def remove_callback(self, cb):
        self._callbacks.discard(cb)

    def _notify(self):
        for cb in tuple(self._callbacks):
            cb()

    async def async_start(self):
        if "mqtt" not in self.hass.data:
            raise RuntimeError("Home Assistant MQTT integration is not configured")

        async def adv(msg):
            self.parse_adv(msg.payload)

        async def telemetry(msg):
            self.last_telemetry_time = int(time.time())
            self.available = True
            self._notify()

        async def result(msg):
            self.parse_command_result(msg.payload)

        topic = self.config[CONF_MQTT_TOPIC]
        self._unsub.append(await mqtt.async_subscribe(self.hass, ADVERT_TOPIC.format(topic=topic), adv))
        self._unsub.append(await mqtt.async_subscribe(self.hass, TELEMETRY_TOPIC.format(topic=topic), telemetry))
        self._unsub.append(await mqtt.async_subscribe(self.hass, COMMAND_RESULT_TOPIC.format(topic=topic), result))

    async def async_stop(self):
        for unsub in self._unsub:
            unsub()
        self._unsub.clear()

    def _set_state(self, state):
        changed = state != self.curr_state
        self.curr_state = state
        self.available = True
        if changed:
            self._state_event.set()

        if self.operation_state in ("locking", "unlocking"):
            desired = LOCKED if self.operation_state == "locking" else UNLOCKED
            if state == desired:
                self.operation_state = "idle"
                self.last_command_error = None

        self._notify()

    def parse_adv(self, payload):
        data = json.loads(payload)
        mac = data.get("mac", "").replace(":", "").upper()
        if mac != self.config[CONF_MAC_ADDRESS].upper():
            return
        raw = data.get("data", "").upper()
        b = bytearray.fromhex(raw)
        if len(b) < 24 or b[0] != 0xBA or b[1] != 0xBA:
            return

        self.voltage = ((b[16] << 8) | b[17]) * 0.01
        if len(b) >= 24:
            self.lock_events = max(self.lock_events, (b[18] << 24) | (b[19] << 16) | (b[20] << 8) | b[21])
            new_state = (b[22] >> 4) & 3
            clockwise = bool(b[22] & 0x80)
            if new_state != JAMMED:
                if clockwise:
                    new_state = 1 - new_state
            self._set_state(new_state)
            self.is_low_battery = bool(b[23] & 0x10)

        self.battery_perc = self._battery_percentage(self.voltage)
        self.rssi = data.get("rssi")
        now = int(time.time())
        self.last_advert_time = now
        self.available = True
        self._notify()

    def parse_command_result(self, payload):
        data = json.loads(payload)
        mac = data.get("mac", "").replace(":", "").upper()
        if mac != self.config[CONF_MAC_ADDRESS].upper():
            return
        if not self.last_command or data.get("sign") != self.last_command["sign"]:
            return
        if not data.get("success", False):
            self.last_command = None
            self._set_state(FAILED)
            return
        lock_status = data.get("lockStatus")
        if lock_status:
            self._parse_lock_status(lock_status)
        self.last_command = None
        self._notify()

    def _parse_lock_status(self, lock_status):
        b = bytearray.fromhex(lock_status)
        if len(b) < 17 or b[0] != 0xAA or b[3] != 0x02 or b[4] != 0x04:
            return
        self.lock_events = max(self.lock_events, (b[10] << 24) | (b[11] << 16) | (b[12] << 8) | b[13])
        self.voltage = ((b[14] << 8) | b[15]) * 0.01
        self._set_state((b[16] >> 4) & 3)
        self.battery_perc = self._battery_percentage(self.voltage)
        self._notify()

    def _battery_percentage(self, voltage):
        thresholds = self.config.get("voltage_thresholds") or []
        if len(thresholds) < 3:
            return None
        if voltage >= thresholds[2]:
            return 100
        if voltage >= thresholds[1]:
            return round(66.6 + 33.3 * (voltage-thresholds[1])/(thresholds[2]-thresholds[1]), 1)
        return max(0, round(33.3 + 33.3 * (voltage-thresholds[0])/(thresholds[1]-thresholds[0]), 1))

    def check_availability(self):
        now = int(time.time())
        if self.last_advert_time and now - self.last_advert_time >= MAX_NORECEIVE_TIME:
            self.available = False

    async def async_command_mqtt(self, lock_dir):
        self._set_state(OPERATING)
        op = self.generator.operation_code(lock_dir, self.lock_events)
        self.last_command = {
            "command1": "FF00" + op[:36].decode(),
            "command2": "FF01" + op[36:].decode(),
            "sign": self.generator.system_time,
        }
        self.last_command_transport = "mqtt"
        self.last_command_error = None
        self.last_command_time = int(time.time())
        await mqtt.async_publish(
            self.hass,
            f"{self.config[CONF_MQTT_TOPIC]}/command",
            json.dumps(self.last_command),
        )


    async def async_operate(self, unlock: bool):
        """Operate via Cloud and wait for MQTT/BLE physical confirmation."""
        desired = UNLOCKED if unlock else LOCKED
        self._state_event.clear()
        self.last_command_error = None
        self.last_command_time = int(time.time())
        self.operation_state = "unlocking" if unlock else "locking"
        self._notify()

        try:
            await self.cloud.operate_lock(self, unlock=unlock)
            self.last_command_transport = "cloud"
        except Exception as err:
            self.last_command_error = str(err)
            self.last_command_transport = "cloud_failed"
            try:
                await self.async_command_mqtt(1 if unlock else 0)
            except Exception as mqtt_err:
                self.last_command_error = f"Cloud: {err}; MQTT: {mqtt_err}"
                self.operation_state = "failed"
                self._set_state(FAILED)
                self._notify()
                raise RuntimeError(self.last_command_error) from mqtt_err

        if self.curr_state == desired:
            self.operation_state = "idle"
            self._notify()
            return

        try:
            await asyncio.wait_for(
                self._wait_for_state(desired), STATE_CONFIRM_TIMEOUT
            )
        except asyncio.TimeoutError:
            self.last_command_error = (
                f"Cloud accepted command; MQTT confirmation not received "
                f"within {STATE_CONFIRM_TIMEOUT}s"
            )
            self._notify()
            return

        self.operation_state = "idle"
        self.last_command_error = None
        self._notify()

    async def _wait_for_state(self, desired):
        while self.curr_state != desired:
            self._state_event.clear()
            await self._state_event.wait()

