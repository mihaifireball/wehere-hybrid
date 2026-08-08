# WeHere Hybrid Lock v0.2.0

- Cloud remains the primary lock/unlock transport.
- MQTT/BLE is authoritative for the final physical state.
- If Cloud fails, the integration falls back to the MQTT/BLE command path.
- Lock/unlock waits up to 15 seconds for confirmation.
- Cloud requests retry transient failures.
- Diagnostics are available with sensitive account/crypto data redacted.

Keep the working v0.1.0 ZIP as a rollback.

## v0.2.3 hotfix
- Correctly places `WeHereDevice.async_operate()` inside the class.
- Lock entity uses the unified Cloud + MQTT confirmation path.
- All Python modules validated with py_compile.

## v0.2.4
- Confirmation window increased from 15s to 60s.
- A late MQTT/BLE confirmation no longer causes the Home Assistant lock/unlock service call to fail after Cloud has accepted the command.
- MQTT remains authoritative for the eventual physical state.

## v0.3.0
- Lock exposes `operation_state`: `idle`, `locking`, `unlocking`, or `failed`.
- Operation state changes immediately on command start and returns to idle on physical confirmation.
- No helper entity is required for the UI intermediate state.


## v0.3.1
- Adds a native `Operation` sensor exposing `idle`, `locking`, `unlocking`, and `failed`.
- Physical lock state updates now pass through the device state setter so an observed target state ends the operation lifecycle.
