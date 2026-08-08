DOMAIN = "wehere_hybrid"
CONF_USERID = "userId"
CONF_EMAIL = "email"
CONF_TOKEN = "token"
CONF_DEVICE_CONFIGS = "device_configs"
CONF_MQTT_TOPIC = "mqtt_topic"
CONF_MAC_ADDRESS = "mac_address"
CONF_VOLTAGE_THRESHOLDS = "voltage_thresholds"
CONF_RETRIES_NUM = "retries_num"

DEFAULT_RETRIES_NUM = 3
MAX_NORECEIVE_TIME = 30

LOCKED = 0
UNLOCKED = 1
JAMMED = 2
OPERATING = 3
FAILED = 4

STATE_STRINGS = {
    LOCKED: "Locked",
    UNLOCKED: "Unlocked",
    JAMMED: "Jammed",
    OPERATING: "Operating",
    FAILED: "Failed",
}

TELEMETRY_TOPIC = "{topic}/tele"
ADVERT_TOPIC = "{topic}/adv"
COMMAND_RESULT_TOPIC = "{topic}/command_result"

SENSOR_STATE = "state"
SENSOR_BATTERY = "battery"
SENSOR_VOLTAGE = "voltage"
SENSOR_LAST_ADVERT = "last_advert"
SENSOR_LOCK_EVENTS = "lock_events"
SENSOR_RSSI = "signal_strength"
SENSOR_BATTERY_LOW = "battery_low"

SENSORS = (
    SENSOR_STATE,
    SENSOR_BATTERY,
    SENSOR_VOLTAGE,
    SENSOR_LAST_ADVERT,
    SENSOR_LOCK_EVENTS,
    SENSOR_RSSI,
)
