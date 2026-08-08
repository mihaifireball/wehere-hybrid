import esphome.codegen as cg
import esphome.config_validation as cv
from esphome.const import CONF_ID

DEPENDENCIES = ["mqtt"]
AUTO_LOAD = ["mqtt"]

airbnk_gateway_ns = cg.esphome_ns.namespace("airbnk_gateway")
AirbnkGateway = airbnk_gateway_ns.class_("AirbnkGateway", cg.Component)

CONF_MAC_ADDRESS = "mac_address"
CONF_MQTT_TOPIC = "mqtt_topic"

CONFIG_SCHEMA = cv.Schema({
    cv.GenerateID(): cv.declare_id(AirbnkGateway),
    cv.Required(CONF_MAC_ADDRESS): cv.mac_address,
    cv.Required(CONF_MQTT_TOPIC): cv.string_strict,
}).extend(cv.COMPONENT_SCHEMA)

async def to_code(config):
    cg.add_library("h2zero/NimBLE-Arduino", None)
    var = cg.new_Pvariable(
        config[CONF_ID],
        cg.std_string(str(config[CONF_MAC_ADDRESS])),
        cg.std_string(config[CONF_MQTT_TOPIC]),
    )
    await cg.register_component(var, config)
