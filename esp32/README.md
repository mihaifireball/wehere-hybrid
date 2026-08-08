# ESP32 Airbnk Gateway

This ESPHome component turns an ESP32 into the BLE-to-MQTT gateway used by WeHere Hybrid.

## Setup

1. Copy `airbnk.example.yaml` to your ESPHome configuration directory as `airbnk.yaml`.
2. Create/update your ESPHome `secrets.yaml` with the Wi-Fi, MQTT, OTA and fallback AP secrets.
3. Replace `AA:BB:CC:DD:EE:FF` with the BLE MAC address of your WeHere/Airbnk lock.
4. Keep `mqtt_topic: "airbnk"` if you are using the default Home Assistant configuration.
5. Validate, compile and install from ESPHome.

The external component is loaded locally from `components/airbnk_gateway`.

## MQTT topics

With `mqtt_topic: airbnk` the gateway uses:

- `airbnk/adv`
- `airbnk/command`
- `airbnk/command_result`

## Important

Do not commit your real `secrets.yaml`, Wi-Fi password, MQTT password or OTA password.
