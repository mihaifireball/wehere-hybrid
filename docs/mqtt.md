# MQTT protocol

The default root topic is `airbnk`.

| Topic | Direction | Purpose |
|---|---|---|
| `airbnk/adv` | ESP32 → HA | BLE advertisement/state data |
| `airbnk/command` | HA → ESP32 | Lock command payload |
| `airbnk/command_result` | ESP32 → HA | BLE operation result/status |
