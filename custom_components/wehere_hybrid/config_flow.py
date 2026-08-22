from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_CODE, CONF_EMAIL
from .cloud import WeHereCloud
from .const import (
    DOMAIN, CONF_USERID, CONF_TOKEN, CONF_DEVICE_CONFIGS, CONF_MQTT_TOPIC,
    CONF_MAC_ADDRESS, CONF_VOLTAGE_THRESHOLDS, CONF_RETRIES_NUM, DEFAULT_RETRIES_NUM,
    CONF_COMMAND_MODE, DEFAULT_COMMAND_MODE, COMMAND_MODES,
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
        self._reauth_entry = None

    @staticmethod
    def async_get_options_flow(config_entry):
        return WeHereOptionsFlow()

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
        result = await WeHereCloud.retrieve_access_token(self.hass, user_input[CONF_EMAIL], user_input[CONF_CODE])
        if not result:
            return self.async_abort(reason="token_retrieval_failed")
        data = result["data"]
        self.entry_data = {
            CONF_EMAIL: data.get(CONF_EMAIL, user_input[CONF_EMAIL]),
            CONF_USERID: data[CONF_USERID],
            CONF_TOKEN: data[CONF_TOKEN],
            CONF_DEVICE_CONFIGS: {},
        }
        temp_entry = type("E", (), {"data": self.entry_data})()
        self.devices = await WeHereCloud(self.hass, temp_entry).get_devices()
        if not self.devices:
            return self.async_create_entry(title="WeHere", data=self.entry_data)
        self.index = 0
        return await self.async_step_device()

    async def async_step_device(self, user_input=None):
        sn = list(self.devices)[self.index]
        dev = self.devices[sn]
        if user_input is None:
            return self.async_show_form(
                step_id="device", data_schema=STEP_DEVICE,
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

    async def async_step_reauth(self, entry_data):
        self._reauth_entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        if self._reauth_entry is None:
            return self.async_abort(reason="reauth_entry_missing")
        self.email = self._reauth_entry.data.get(CONF_EMAIL)
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        errors = {}
        if user_input is None:
            return self.async_show_form(
                step_id="reauth_confirm",
                data_schema=vol.Schema({vol.Required(CONF_EMAIL, default=self.email or ""): str}),
            )
        email = user_input[CONF_EMAIL]
        ok = await WeHereCloud.request_verification_code(self.hass, email)
        if not ok:
            errors["base"] = "code_request_failed"
            return self.async_show_form(
                step_id="reauth_confirm",
                data_schema=vol.Schema({vol.Required(CONF_EMAIL, default=email): str}),
                errors=errors,
            )
        self.email = email
        return self.async_show_form(
            step_id="reauth_verify",
            data_schema=vol.Schema({vol.Required(CONF_CODE): str}),
        )

    async def async_step_reauth_verify(self, user_input=None):
        if user_input is None:
            return self.async_show_form(
                step_id="reauth_verify", data_schema=vol.Schema({vol.Required(CONF_CODE): str})
            )
        result = await WeHereCloud.retrieve_access_token(self.hass, self.email, user_input[CONF_CODE])
        if not result:
            return self.async_show_form(
                step_id="reauth_verify",
                data_schema=vol.Schema({vol.Required(CONF_CODE): str}),
                errors={"base": "invalid_auth"},
            )
        data = result["data"]
        new_data = dict(self._reauth_entry.data)
        new_data[CONF_EMAIL] = data.get(CONF_EMAIL, self.email)
        new_data[CONF_USERID] = data[CONF_USERID]
        new_data[CONF_TOKEN] = data[CONF_TOKEN]
        return self.async_update_reload_and_abort(self._reauth_entry, data=new_data)

class WeHereOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional(
                    CONF_COMMAND_MODE,
                    default=self.config_entry.options.get(CONF_COMMAND_MODE, DEFAULT_COMMAND_MODE),
                ): vol.In(COMMAND_MODES),
                vol.Optional(
                    CONF_RETRIES_NUM,
                    default=self.config_entry.options.get(CONF_RETRIES_NUM, DEFAULT_RETRIES_NUM),
                ): vol.All(vol.Coerce(int), vol.Range(min=0, max=10)),
            }),
        )
