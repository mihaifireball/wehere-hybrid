from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable

from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant, callback

from pyairbnk import (
    AirbnkBleClient,
    BootstrapData,
    decrypt_bootstrap,
    parse_advertisement_data,
)

from .const import CONF_MAC_ADDRESS


_LOGGER = logging.getLogger(__name__)


AIRBNK_MANUFACTURER_ID = 0xBABA

OPERATION_UNLOCK = 1
OPERATION_LOCK = 2

DEFAULT_BLE_COMMAND_TIMEOUT = 15.0

# Cât așteptăm un advertisement proaspăt înainte de comandă.
# Dacă nu apare, nu blocăm comanda; folosim BLEDevice-ul cunoscut.
FRESH_ADVERTISEMENT_TIMEOUT = 3.0


class WeHereBleTransport:
    """Direct Bluetooth transport for an Airbnk / WeHere lock."""

    def __init__(
        self,
        hass: HomeAssistant,
        config: dict[str, Any],
        advertisement_callback: Callable[
            [Any, int | None],
            None,
        ]
        | None = None,
    ) -> None:
        self.hass = hass
        self.config = config

        self.sn = str(
            config["sn"]
        )

        self.name = str(
            config.get(
                "deviceName",
                self.sn,
            )
        )

        self.address = self._format_mac(
            str(
                config[
                    CONF_MAC_ADDRESS
                ]
            )
        )

        self.bootstrap: BootstrapData = (
            decrypt_bootstrap(
                self.sn,
                str(
                    config[
                        "newSninfo"
                    ]
                ),
                str(
                    config[
                        "appKey"
                    ]
                ),
            )
        )

        self._advertisement_callback = (
            advertisement_callback
        )

        self._ble_device = None
        self._last_service_info = None
        self._unsub_bluetooth = None

        self._ble_client = AirbnkBleClient(
            self._ble_device_callback,
            name=self.name,
        )

        _LOGGER.debug(
            "Initialized BLE transport for %s (%s), model=%s",
            self.name,
            self.address,
            self.bootstrap.lock_model,
        )

    @staticmethod
    def _format_mac(
        value: str,
    ) -> str:
        """Normalize stored MAC to AA:BB:CC:DD:EE:FF."""

        mac = (
            value
            .replace(":", "")
            .replace("-", "")
            .strip()
            .upper()
        )

        if len(mac) != 12:
            raise ValueError(
                f"Invalid Bluetooth MAC address: {value}"
            )

        return ":".join(
            mac[i : i + 2]
            for i in range(
                0,
                12,
                2,
            )
        )

    async def async_start(
        self,
    ) -> None:
        """Start native Home Assistant Bluetooth tracking."""

        @callback
        def _async_discovered(
            service_info:
                bluetooth.BluetoothServiceInfoBleak,
            change:
                bluetooth.BluetoothChange,
        ) -> None:
            """Handle Bluetooth advertisements."""

            if (
                service_info.address.upper()
                != self.address
            ):
                return

            #
            # Always keep the newest BLEDevice.
            #
            if (
                service_info.device
                is not None
            ):
                self._ble_device = (
                    service_info.device
                )

            self._last_service_info = (
                service_info
            )

            payload = (
                service_info
                .manufacturer_data
                .get(
                    AIRBNK_MANUFACTURER_ID
                )
            )

            if not payload:
                return

            try:
                parsed = (
                    parse_advertisement_data(
                        bytes(payload),
                        expected_lock_sn=(
                            self.sn
                        ),
                    )
                )

            except Exception as err:
                _LOGGER.debug(
                    "Unable to parse BLE advertisement "
                    "from %s (%s): %s",
                    self.name,
                    self.address,
                    err,
                )
                return

            _LOGGER.debug(
                "BLE advertisement %s (%s): "
                "state=%s raw_state=%s "
                "clockwise=%s events=%s "
                "voltage=%.2f RSSI=%s",
                self.name,
                self.address,
                parsed.lock_state,
                parsed.raw_state_bits,
                parsed.opens_clockwise,
                parsed.lock_events,
                parsed.voltage,
                service_info.rssi,
            )

            if (
                self._advertisement_callback
                is not None
            ):
                self._advertisement_callback(
                    parsed,
                    service_info.rssi,
                )

        #
        # Register with Home Assistant's shared
        # Bluetooth scanner.
        #
        # HA 2026.8 requires scan_interval >= 60 s.
        #
        self._unsub_bluetooth = (
            bluetooth
            .async_register_callback(
                self.hass,
                _async_discovered,
                {
                    "address":
                        self.address,
                    "connectable":
                        True,
                },
                bluetooth
                .BluetoothScanningMode
                .ACTIVE,
                scan_interval=60.0,
                scan_duration=10.0,
                replay=(
                    bluetooth
                    .BluetoothCallbackReplay
                    .NEWEST_FIRST
                ),
            )
        )

        #
        # Seed the connection object from HA's
        # existing Bluetooth cache.
        #
        service_info = (
            bluetooth
            .async_last_service_info(
                self.hass,
                self.address,
                connectable=True,
            )
        )

        if service_info is not None:
            self._last_service_info = (
                service_info
            )

            if (
                service_info.device
                is not None
            ):
                self._ble_device = (
                    service_info.device
                )

        _LOGGER.info(
            "BLE tracking started for %s (%s)",
            self.name,
            self.address,
        )

    async def async_stop(
        self,
    ) -> None:
        """Stop native Bluetooth tracking."""

        if (
            self._unsub_bluetooth
            is not None
        ):
            self._unsub_bluetooth()
            self._unsub_bluetooth = None

        self._ble_device = None
        self._last_service_info = None

    def _ble_device_callback(
        self,
    ):
        """Return the freshest connectable BLEDevice."""

        fresh_device = (
            bluetooth
            .async_ble_device_from_address(
                self.hass,
                self.address,
                connectable=True,
            )
        )

        if fresh_device is not None:
            self._ble_device = (
                fresh_device
            )

        return self._ble_device

    @property
    def available(
        self,
    ) -> bool:
        """Return whether HA currently sees the lock."""

        return (
            bluetooth
            .async_address_present(
                self.hass,
                self.address,
                connectable=True,
            )
        )

    async def _async_get_fresh_device(
        self,
    ):
        """
        Try to receive a fresh advertisement immediately before connecting.

        Airbnk locks appear to connect significantly faster when
        connection begins close to an advertisement.
        """

        _LOGGER.debug(
            "%s (%s): Waiting up to %.1fs "
            "for fresh BLE advertisement",
            self.name,
            self.address,
            FRESH_ADVERTISEMENT_TIMEOUT,
        )

        #
        # Home Assistant normally deduplicates identical
        # advertisements. Clear that cache so the next
        # packet from the lock reaches our callbacks.
        #
        try:
            bluetooth.async_clear_advertisement_history(
                self.hass,
                self.address,
            )
        except Exception as err:
            _LOGGER.debug(
                "%s (%s): Could not clear advertisement "
                "history: %s",
                self.name,
                self.address,
                err,
            )

        def _matches(
            service_info:
                bluetooth.BluetoothServiceInfoBleak,
        ) -> bool:
            return (
                service_info.address.upper()
                == self.address
                and AIRBNK_MANUFACTURER_ID
                in service_info.manufacturer_data
            )

        try:
            service_info = (
                await bluetooth
                .async_process_advertisements(
                    self.hass,
                    _matches,
                    {
                        "address":
                            self.address,
                        "connectable":
                            True,
                    },
                    bluetooth
                    .BluetoothScanningMode
                    .ACTIVE,
                    FRESH_ADVERTISEMENT_TIMEOUT,
                )
            )

        except asyncio.TimeoutError:
            _LOGGER.debug(
                "%s (%s): No fresh advertisement "
                "within %.1fs; using latest known "
                "BLEDevice",
                self.name,
                self.address,
                FRESH_ADVERTISEMENT_TIMEOUT,
            )

            return (
                self._ble_device_callback()
            )

        except Exception as err:
            _LOGGER.debug(
                "%s (%s): Fresh advertisement wait "
                "failed: %s",
                self.name,
                self.address,
                err,
            )

            return (
                self._ble_device_callback()
            )

        #
        # We just received a real packet from the lock.
        #
        self._last_service_info = (
            service_info
        )

        if (
            service_info.device
            is not None
        ):
            self._ble_device = (
                service_info.device
            )

        _LOGGER.debug(
            "%s (%s): Fresh BLE advertisement "
            "received, RSSI=%s",
            self.name,
            self.address,
            service_info.rssi,
        )

        return self._ble_device

    async def async_probe(
        self,
        timeout: float = (
            DEFAULT_BLE_COMMAND_TIMEOUT
        ),
    ) -> bool:
        """
        Test BLE connectivity.

        Kept for diagnostics, but should not normally
        be called during integration startup.
        """

        ble_device = (
            self._ble_device_callback()
        )

        if ble_device is None:
            _LOGGER.warning(
                "No connectable BLEDevice available "
                "for %s (%s)",
                self.name,
                self.address,
            )
            return False

        try:
            await (
                self._ble_client
                .async_probe_connectivity(
                    command_timeout=timeout,
                )
            )

        except Exception as err:
            _LOGGER.warning(
                "BLE probe failed for %s (%s): %s",
                self.name,
                self.address,
                err,
            )
            return False

        _LOGGER.info(
            "BLE probe successful for %s (%s)",
            self.name,
            self.address,
        )

        return True

    async def async_operate(
        self,
        *,
        unlock: bool,
        lock_events: int,
        timeout: float = (
            DEFAULT_BLE_COMMAND_TIMEOUT
        ),
    ):
        """Operate the lock directly via Bluetooth."""

        action = (
            "unlock"
            if unlock
            else "lock"
        )

        #
        # First try to catch the lock while it is
        # actively advertising.
        #
        ble_device = (
            await self
            ._async_get_fresh_device()
        )

        if ble_device is None:
            raise RuntimeError(
                "No connectable BLE device "
                f"available for {self.name}"
            )

        operation = (
            OPERATION_UNLOCK
            if unlock
            else OPERATION_LOCK
        )

        _LOGGER.info(
            "Sending direct BLE %s to %s (%s), "
            "lock_events=%s",
            action,
            self.name,
            self.address,
            lock_events,
        )

        started = (
            time.monotonic()
        )

        result = (
            await self._ble_client
            .async_send_operation(
                operation=operation,
                current_lock_events=(
                    lock_events
                ),
                bootstrap=self.bootstrap,
                command_timeout=timeout,
            )
        )

        elapsed = (
            time.monotonic()
            - started
        )

        _LOGGER.info(
            "Direct BLE %s completed for %s (%s) "
            "in %.2fs",
            action,
            self.name,
            self.address,
            elapsed,
        )

        #
        # pyairbnk disconnects after the GATT command.
        #
        # Clear HA's advertisement deduplication cache so
        # the very next advertisement from the lock is
        # delivered to our callback. This should improve
        # post-command state updates.
        #
        try:
            bluetooth.async_clear_advertisement_history(
                self.hass,
                self.address,
            )
        except Exception as err:
            _LOGGER.debug(
                "%s (%s): Unable to clear advertisement "
                "history after command: %s",
                self.name,
                self.address,
                err,
            )

        return result
