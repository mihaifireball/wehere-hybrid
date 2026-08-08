from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_CODE, CONF_EMAIL

from .cloud import WeHereCloud
from .const import (
    DOMAIN, CONF_USERID, CONF_TOKEN, CONF_DEVICE_CONFIGS,
    CONF_MQTT_TOPIC, CONF_MAC_ADDRESS, CONF_VOLTAGE_THRESHOLDS,
    CONF_RETRIES_NUM, DEFAULT_RETRIES_NUM,
)

STEP_USER = vol.Schema({vol.Required(CONF_EMAIL): str})
STEP_VERIFY = vol.Schema({vol.Required(CONF_EMAIL): str, vol.Required(CONF_CODE): str})
STEP_DEVICE = vol.Schema({
    vol.Required(CONF_MQTT_TOPIC): str,
    vol.Required(CONF_MAC_ADDRESS): str,
    vol.Required("skip_device", default=False): bool,
})

@config_entries.HANDLERS.register(DOMAIN)
class WeHereConfigFlow(config_entries.ConfigFlow):
    VERSION = 1

    def __init__(self):
        self.email = None
        self.entry_data = {}
        self.devices = {}
        self.index = 0

    @staticmethod
    def async_get_options_flow(config_entry):
        return WeHereOptionsFlow(config_entry)

    async def async_step_user(self, user_input=None):
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=STEP_USER)
        self.email = user_input[CONF_EMAIL]
        ok = await WeHereCloud.request_verification_code(self.hass, self.email)
        if not ok:
            return self.async_abort(reason="code_request_failed")
        return self.async_show_form(
            step_id="verify",
            data_schema=vol.Schema({
                vol.Required(CONF_EMAIL, default=self.email): str,
                vol.Required(CONF_CODE): str,
            }),
        )

    async def async_step_verify(self, user_input=None):
        if user_input is None:
            return self.async_show_form(step_id="verify", data_schema=STEP_VERIFY)
        result = await WeHereCloud.retrieve_access_token(
            self.hass, user_input[CONF_EMAIL], user_input[CONF_CODE]
        )
        if not result:
            return self.async_abort(reason="token_retrieval_failed")

        data = result["data"]
        self.entry_data = {
            CONF_EMAIL: data.get(CONF_EMAIL, user_input[CONF_EMAIL]),
            CONF_USERID: data[CONF_USERID],
            CONF_TOKEN: data[CONF_TOKEN],
            CONF_DEVICE_CONFIGS: {},
        }
        self.devices = await WeHereCloud(self.hass, type("E", (), {"data": self.entry_data})()).get_devices()
        if not self.devices:
            return self.async_create_entry(title="WeHere", data=self.entry_data)
        self.index = 0
        return await self.async_step_device()

    async def async_step_device(self, user_input=None):
        sn = list(self.devices)[self.index]
        dev = self.devices[sn]
        if user_input is None:
            return self.async_show_form(
                step_id="device",
                data_schema=STEP_DEVICE,
                description_placeholders={
                    "name": dev.get("deviceName", sn),
                    "model": dev.get("deviceType", ""),
                    "sn": sn,
                },
            )

        if not user_input.get("skip_device"):
            cfg = dict(dev)
            cfg[CONF_MQTT_TOPIC] = user_input[CONF_MQTT_TOPIC]
            cfg[CONF_MAC_ADDRESS] = user_input[CONF_MAC_ADDRESS].replace(":", "").upper()

            temp_entry = type("E", (), {"data": self.entry_data})()
            voltage = await WeHereCloud(self.hass, temp_entry).get_voltage_config(
                cfg.get("deviceType"), cfg.get("hardwareVersion")
            )
            cfg[CONF_VOLTAGE_THRESHOLDS] = (
                [float(voltage[f"fvoltage{i}"]) for i in range(1, 5)]
                if voltage else [0, 0, 0, 0]
            )
            self.entry_data[CONF_DEVICE_CONFIGS][sn] = cfg

        self.index += 1
        if self.index < len(self.devices):
            return await self.async_step_device()
        return self.async_create_entry(title="WeHere Hybrid", data=self.entry_data)

class WeHereOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional(
                    CONF_RETRIES_NUM,
                    default=self.config_entry.options.get(CONF_RETRIES_NUM, DEFAULT_RETRIES_NUM),
                ): vol.All(vol.Coerce(int), vol.Range(min=0, max=10))
            }),
        )
