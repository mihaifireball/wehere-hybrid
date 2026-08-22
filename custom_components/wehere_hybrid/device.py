from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Callable
from homeassistant.components import mqtt
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC
from .ble_transport import WeHereBleTransport
from .codes import AirbnkCodesGenerator
from .const import (
    ADVERT_TOPIC, COMMAND_RESULT_TOPIC, TELEMETRY_TOPIC, LOCKED, UNLOCKED, JAMMED,
    OPERATING, FAILED, STATE_STRINGS, MAX_NORECEIVE_TIME, CONF_MAC_ADDRESS, CONF_MQTT_TOPIC,
    COMMAND_MODE_AUTO, COMMAND_MODE_BLE, COMMAND_MODE_CLOUD, COMMAND_MODE_MQTT,
)

_LOGGER = logging.getLogger(__name__)
STATE_CONFIRM_TIMEOUT = 60

class WeHereDevice:
    def __init__(self, hass: HomeAssistant, cloud, config, retries=3, command_mode=COMMAND_MODE_AUTO):
        self.hass = hass
        self.cloud = cloud
        self.config = config
        self.sn = config["sn"]
        self.retries = retries
        self.command_mode = command_mode
        self.generator = AirbnkCodesGenerator()
        self.generator.decrypt_keys(config["newSninfo"], config["appKey"])
        self.ble = WeHereBleTransport(hass=hass, config=config, advertisement_callback=self._handle_ble_advertisement)
        self.ble_probe_successful = None
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

    def add_callback(self, cb): self._callbacks.add(cb)
    def remove_callback(self, cb): self._callbacks.discard(cb)
    def _notify(self):
        for cb in tuple(self._callbacks): cb()

    async def async_start(self):
        async def adv(msg): self.parse_adv(msg.payload)
        async def telemetry(msg):
            self.last_telemetry_time = int(time.time()); self.available = True; self._notify()
        async def result(msg): self.parse_command_result(msg.payload)
        topic = self.config[CONF_MQTT_TOPIC]
        self._unsub.append(await mqtt.async_subscribe(self.hass, ADVERT_TOPIC.format(topic=topic), adv))
        self._unsub.append(await mqtt.async_subscribe(self.hass, TELEMETRY_TOPIC.format(topic=topic), telemetry))
        self._unsub.append(await mqtt.async_subscribe(self.hass, COMMAND_RESULT_TOPIC.format(topic=topic), result))
        await self.ble.async_start()
        try:
            self.ble_probe_successful = await self.ble.async_probe()
            _LOGGER.warning(
                "DIRECT BLE TEST %s for %s (%s)",
                "SUCCESSFUL" if self.ble_probe_successful else "FAILED", self.name, self.ble.address
            )
        except Exception as err:
            self.ble_probe_successful = False
            _LOGGER.exception("Unexpected direct BLE probe error for %s (%s): %s", self.name, self.ble.address, err)

    async def async_stop(self):
        await self.ble.async_stop()
        for unsub in self._unsub: unsub()
        self._unsub.clear()

    def _set_state(self, state):
        changed = state != self.curr_state
        self.curr_state = state
        self.available = True
        if changed: self._state_event.set()
        if self.operation_state in ("locking", "unlocking"):
            desired = LOCKED if self.operation_state == "locking" else UNLOCKED
            if state == desired:
                self.operation_state = "idle"
                self.last_command_error = None
        self._notify()

    def _handle_ble_advertisement(self, parsed, rssi):
        self.lock_events = max(self.lock_events, parsed.lock_events)
        self.voltage = parsed.voltage
        self.is_low_battery = parsed.is_low_battery
        self.battery_perc = self._battery_percentage(self.voltage)
        self.rssi = rssi
        self.last_advert_time = int(time.time())
        self.available = True
        self._set_state(parsed.lock_state)

    def parse_adv(self, payload):
        data = json.loads(payload)
        mac = data.get("mac", "").replace(":", "").upper()
        if mac != self.config[CONF_MAC_ADDRESS].upper(): return
        raw = data.get("data", "").upper()
        b = bytearray.fromhex(raw)
        if len(b) < 24 or b[0] != 0xBA or b[1] != 0xBA: return
        self.voltage = ((b[16] << 8) | b[17]) * 0.01
        self.lock_events = max(self.lock_events, (b[18] << 24) | (b[19] << 16) | (b[20] << 8) | b[21])
        new_state = (b[22] >> 4) & 3
        clockwise = bool(b[22] & 0x80)
        if new_state != JAMMED and clockwise: new_state = 1 - new_state
        self._set_state(new_state)
        self.is_low_battery = bool(b[23] & 0x10)
        self.battery_perc = self._battery_percentage(self.voltage)
        self.rssi = data.get("rssi")
        self.last_advert_time = int(time.time())
        self.available = True
        self._notify()

    def parse_command_result(self, payload):
        data = json.loads(payload)
        mac = data.get("mac", "").replace(":", "").upper()
        if mac != self.config[CONF_MAC_ADDRESS].upper(): return
        if not self.last_command or data.get("sign") != self.last_command["sign"]: return
        if not data.get("success", False):
            self.last_command = None; self._set_state(FAILED); return
        lock_status = data.get("lockStatus")
        if lock_status: self._parse_lock_status(lock_status)
        self.last_command = None
        self._notify()

    def _parse_lock_status(self, lock_status):
        b = bytearray.fromhex(lock_status)
        if len(b) < 17 or b[0] != 0xAA or b[3] != 0x02 or b[4] != 0x04: return
        self.lock_events = max(self.lock_events, (b[10] << 24) | (b[11] << 16) | (b[12] << 8) | b[13])
        self.voltage = ((b[14] << 8) | b[15]) * 0.01
        self._set_state((b[16] >> 4) & 3)
        self.battery_perc = self._battery_percentage(self.voltage)
        self._notify()

    def _battery_percentage(self, voltage):
        thresholds = self.config.get("voltage_thresholds") or []
        if len(thresholds) < 3: return None
        if voltage >= thresholds[2]: return 100
        if voltage >= thresholds[1]:
            return round(66.6 + 33.3 * (voltage-thresholds[1])/(thresholds[2]-thresholds[1]), 1)
        return max(0, round(33.3 + 33.3 * (voltage-thresholds[0])/(thresholds[1]-thresholds[0]), 1))

    def check_availability(self):
        if self.ble.available:
            self.available = True
            return
        now = int(time.time())
        self.available = bool(self.last_advert_time and now - self.last_advert_time < MAX_NORECEIVE_TIME)

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
        await mqtt.async_publish(self.hass, f"{self.config[CONF_MQTT_TOPIC]}/command", json.dumps(self.last_command))

    def _apply_ble_operation_result(self, result):
        status = getattr(result, "status", None)
        if status is None: return
        result_events = getattr(status, "lock_events", None)
        if result_events is not None: self.lock_events = max(self.lock_events, result_events)
        result_voltage = getattr(status, "voltage", None)
        if result_voltage is not None:
            self.voltage = result_voltage
            self.battery_perc = self._battery_percentage(self.voltage)
        result_low_battery = getattr(status, "is_low_battery", None)
        if result_low_battery is not None: self.is_low_battery = result_low_battery
        result_state = getattr(status, "lock_state", None)
        if result_state is not None: self._set_state(result_state)

    async def async_operate(self, unlock: bool):
        desired = UNLOCKED if unlock else LOCKED
        action = "unlock" if unlock else "lock"
        self._state_event.clear()
        self.last_command_error = None
        self.last_command_time = int(time.time())
        self.operation_state = "unlocking" if unlock else "locking"
        self._notify()

        if self.command_mode in (COMMAND_MODE_AUTO, COMMAND_MODE_BLE):
            try:
                result = await self.ble.async_operate(unlock=unlock, lock_events=self.lock_events)
                self.last_command_transport = "ble"
                self.last_command_error = None
                self._apply_ble_operation_result(result)
                self.available = True
                self.operation_state = "idle"
                self._notify()
                return
            except Exception as ble_err:
                self.last_command_error = f"BLE: {ble_err}"
                self.last_command_transport = "ble_failed"
                if self.command_mode == COMMAND_MODE_BLE:
                    self.operation_state = "failed"
                    self._notify()
                    raise RuntimeError(self.last_command_error) from ble_err

        if self.command_mode in (COMMAND_MODE_AUTO, COMMAND_MODE_CLOUD):
            try:
                await self.cloud.operate_lock(self, unlock=unlock)
                self.last_command_transport = "cloud"
                self.last_command_error = None
            except Exception as cloud_err:
                previous = self.last_command_error
                self.last_command_error = f"{previous}; Cloud: {cloud_err}" if previous else f"Cloud: {cloud_err}"
                self.last_command_transport = "cloud_failed"
                self.operation_state = "failed"
                self._notify()
                raise RuntimeError(self.last_command_error) from cloud_err
            if self.curr_state == desired:
                self.operation_state = "idle"
                self._notify()
                return
            try:
                await asyncio.wait_for(self._wait_for_state(desired), STATE_CONFIRM_TIMEOUT)
            except asyncio.TimeoutError:
                self.last_command_error = f"Cloud command accepted, but physical BLE confirmation was not received within {STATE_CONFIRM_TIMEOUT}s"
                self.operation_state = "idle"
                self._notify()
                return
            self.operation_state = "idle"
            self.last_command_error = None
            self._notify()
            return

        if self.command_mode == COMMAND_MODE_MQTT:
            try:
                await self.async_command_mqtt(1 if unlock else 0)
            except Exception as mqtt_err:
                self.last_command_error = f"MQTT: {mqtt_err}"
                self.operation_state = "failed"
                self._notify()
                raise RuntimeError(self.last_command_error) from mqtt_err
            if self.curr_state == desired:
                self.operation_state = "idle"
                self._notify()
                return
            try:
                await asyncio.wait_for(self._wait_for_state(desired), STATE_CONFIRM_TIMEOUT)
            except asyncio.TimeoutError:
                self.last_command_error = f"MQTT command sent, but physical state confirmation was not received within {STATE_CONFIRM_TIMEOUT}s"
                self.operation_state = "idle"
                self._notify()
                return
            self.operation_state = "idle"
            self.last_command_error = None
            self._notify()
            return

        raise RuntimeError(f"Unsupported command mode: {self.command_mode}")

    async def _wait_for_state(self, desired):
        while self.curr_state != desired:
            self._state_event.clear()
            await self._state_event.wait()
