# Troubleshooting

## Lock/unlock command times out

Check that:

- the ESP32 is online;
- MQTT is connected;
- the configured BLE MAC matches the lock;
- the `airbnk/command` and `airbnk/command_result` topics are reachable;
- the lock is within BLE range of the ESP32.

The integration uses MQTT/BLE physical state confirmation for the final state.

## ESPHome build fails in NimBLE

Use the supplied ESPHome example as-is, including the Arduino framework and the Bluetooth/NimBLE `sdkconfig_options`. Do not add a separate top-level `libraries:` component to the YAML.
