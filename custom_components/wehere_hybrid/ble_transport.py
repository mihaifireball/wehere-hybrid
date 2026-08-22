from __future__ import annotations

import logging
from typing import Any, Callable
from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant, callback
from pyairbnk import AirbnkBleClient, BootstrapData, decrypt_bootstrap, parse_advertisement_data
from .const import CONF_MAC_ADDRESS

_LOGGER = logging.getLogger(__name__)
AIRBNK_MANUFACTURER_ID = 0xBABA
OPERATION_UNLOCK = 1
OPERATION_LOCK = 2
DEFAULT_BLE_COMMAND_TIMEOUT = 15.0

class WeHereBleTransport:
    def __init__(self, hass: HomeAssistant, config: dict[str, Any], advertisement_callback: Callable[[Any, int | None], None] | None = None) -> None:
        self.hass = hass
        self.config = config
        self.sn = str(config["sn"])
        self.name = str(config.get("deviceName", self.sn))
        self.address = self._format_mac(str(config[CONF_MAC_ADDRESS]))
        self.bootstrap: BootstrapData = decrypt_bootstrap(self.sn, str(config["newSninfo"]), str(config["appKey"]))
        self._advertisement_callback = advertisement_callback
        self._ble_device = None
        self._last_service_info = None
        self._unsub_bluetooth = None
        self._ble_client = AirbnkBleClient(self._ble_device_callback, name=self.name)

    @staticmethod
    def _format_mac(value: str) -> str:
        mac = value.replace(":", "").replace("-", "").strip().upper()
        if len(mac) != 12:
            raise ValueError(f"Invalid Bluetooth MAC address: {value}")
        return ":".join(mac[i:i+2] for i in range(0, 12, 2))

    async def async_start(self) -> None:
        @callback
        def _async_discovered(service_info: bluetooth.BluetoothServiceInfoBleak, change: bluetooth.BluetoothChange) -> None:
            if service_info.address.upper() != self.address:
                return
            if service_info.device is not None:
                self._ble_device = service_info.device
            self._last_service_info = service_info
            payload = service_info.manufacturer_data.get(AIRBNK_MANUFACTURER_ID)
            if not payload:
                return
            try:
                parsed = parse_advertisement_data(bytes(payload), expected_lock_sn=self.sn)
            except Exception as err:
                _LOGGER.debug("Unable to parse BLE advertisement from %s (%s): %s", self.name, self.address, err)
                return
            if self._advertisement_callback is not None:
                self._advertisement_callback(parsed, service_info.rssi)

        self._unsub_bluetooth = bluetooth.async_register_callback(
            self.hass,
            _async_discovered,
            {"address": self.address, "connectable": True},
            bluetooth.BluetoothScanningMode.ACTIVE,
            scan_interval=60.0,
            scan_duration=10.0,
            replay=bluetooth.BluetoothCallbackReplay.NEWEST_FIRST,
        )

        service_info = bluetooth.async_last_service_info(self.hass, self.address, connectable=True)
        if service_info is not None:
            self._last_service_info = service_info
            if service_info.device is not None:
                self._ble_device = service_info.device
        _LOGGER.info("BLE tracking started for %s (%s)", self.name, self.address)

    async def async_stop(self) -> None:
        if self._unsub_bluetooth is not None:
            self._unsub_bluetooth()
            self._unsub_bluetooth = None
        self._ble_device = None
        self._last_service_info = None

    def _ble_device_callback(self):
        fresh_device = bluetooth.async_ble_device_from_address(self.hass, self.address, connectable=True)
        if fresh_device is not None:
            self._ble_device = fresh_device
        return self._ble_device

    @property
    def available(self) -> bool:
        return bluetooth.async_address_present(self.hass, self.address, connectable=True)

    async def async_probe(self, timeout: float = DEFAULT_BLE_COMMAND_TIMEOUT) -> bool:
        if self._ble_device_callback() is None:
            return False
        try:
            await self._ble_client.async_probe_connectivity(command_timeout=timeout)
        except Exception as err:
            _LOGGER.warning("BLE probe failed for %s (%s): %s", self.name, self.address, err)
            return False
        return True

    async def async_operate(self, *, unlock: bool, lock_events: int, timeout: float = DEFAULT_BLE_COMMAND_TIMEOUT):
        if self._ble_device_callback() is None:
            raise RuntimeError(f"No connectable BLE device available for {self.name}")
        operation = OPERATION_UNLOCK if unlock else OPERATION_LOCK
        return await self._ble_client.async_send_operation(
            operation=operation, current_lock_events=lock_events, bootstrap=self.bootstrap, command_timeout=timeout
        )
