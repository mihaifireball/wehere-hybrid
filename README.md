# WeHere Hybrid Lock

Home Assistant custom integration for WeHere / Airbnk smart locks, combining the cloud transport with the ESP32 BLE/MQTT gateway.

## What it does

- Native Home Assistant `lock` entity.
- Cloud-first lock/unlock commands.
- MQTT/BLE physical-state confirmation.
- Fallback to the MQTT/BLE command path when cloud operation fails.
- Battery level and low-battery status.
- Signal/RSSI information.
- Lock status and operation state (`idle`, `locking`, `unlocking`, `failed`).
- Configurable confirmation window.
- Diagnostics with sensitive account data redacted.

## Architecture

```text
WeHere / Airbnk M541
        │ BLE
        ▼
ESP32 Airbnk Gateway
        │ MQTT
        ▼
Home Assistant
        │
        ▼
WeHere Hybrid integration
```

The MQTT topic used by the current ESP32 configuration is `airbnk`.

## Home Assistant installation

### HACS

This repository is designed for HACS. Until it is accepted into the default HACS store, add it as a **Custom repository** of type **Integration** using the GitHub repository URL.

After installation, restart Home Assistant and add **WeHere Hybrid Lock** from **Settings → Devices & services → Add Integration**.

### Manual

Copy `custom_components/wehere_hybrid` into your Home Assistant `config/custom_components/` directory and restart Home Assistant.

## ESP32 gateway

The companion ESPHome external component is in `esp32/components/airbnk_gateway/`.

Start from `esp32/airbnk.example.yaml`, copy it to your ESPHome configuration directory as `airbnk.yaml`, then set:

- Wi-Fi credentials via ESPHome secrets.
- MQTT broker/user/password.
- The lock BLE MAC address.
- The MQTT root topic (default: `airbnk`).

The ESP32 uses the Arduino framework and NimBLE-Arduino. The supplied example also enables the Bluetooth/NimBLE ESP-IDF settings required by the current ESPHome build used during development.

## MQTT contract

The gateway uses these topics relative to the configured root topic:

- `<topic>/adv` — BLE advertisement/state information.
- `<topic>/command` — commands sent from Home Assistant to the gateway.
- `<topic>/command_result` — gateway command results and BLE status.

## Current status

Version `0.3.1` is the working development release used with the WeHere M541 setup.

## License and attribution

This project is GPL-3.0-or-later. It is a hybrid implementation derived from concepts/code in the GPL-3.0 `airbnk_mqtt` and `airbnk_cloud` projects by rospogrigio. See `custom_components/wehere_hybrid/NOTICE` for attribution.

## Disclaimer

This is a community-developed Home Assistant custom integration. It is not an official WeHere/Airbnk product.
