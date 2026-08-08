from __future__ import annotations

import functools
import logging
import uuid
import asyncio

import requests

from .const import CONF_TOKEN, CONF_USERID

_LOGGER = logging.getLogger(__name__)

BASE_URL = "https://wehereapi.seamooncloud.com"
LANGUAGE = "2"
VERSION = "A_FD_1.8.0"
HEADERS = {"user-agent": "okhttp/3.12.0", "Accept-Encoding": "gzip, deflate"}

class WeHereCloud:
    def __init__(self, hass, entry):
        self.hass = hass
        self.entry = entry

    @staticmethod
    async def request_verification_code(hass, email):
        url = (
            f"{BASE_URL}/api/lock/sms?loginAcct={email}"
            f"&language={LANGUAGE}&version={VERSION}&mark=10&userId="
        )
        try:
            res = await hass.async_add_executor_job(
                functools.partial(requests.post, url, headers=HEADERS, timeout=20)
            )
            return res.status_code == 200
        except Exception:
            _LOGGER.exception("WeHere verification-code request failed")
            return False

    @staticmethod
    async def retrieve_access_token(hass, email, code):
        url = (
            f"{BASE_URL}/api/lock/loginByAuthcode?loginAcct={email}"
            f"&authCode={code}&systemCode=Android&language={LANGUAGE}"
            f"&version={VERSION}&deviceID=123456789012345&mark=1"
        )
        try:
            res = await hass.async_add_executor_job(
                functools.partial(requests.get, url, headers=HEADERS, timeout=20)
            )
            if res.status_code != 200:
                return None
            data = res.json()
            return data if data.get("code") == 200 else None
        except Exception:
            _LOGGER.exception("WeHere token retrieval failed")
            return None

    async def get_devices(self, user_id=None, token=None):
        user_id = user_id or self.entry.data[CONF_USERID]
        token = token or self.entry.data[CONF_TOKEN]
        url = (
            f"{BASE_URL}/api/v2/lock/getAllDevicesNew?language={LANGUAGE}"
            f"&userId={user_id}&version={VERSION}&token={token}"
        )
        try:
            res = await self.hass.async_add_executor_job(
                functools.partial(requests.get, url, headers=HEADERS, timeout=20)
            )
            if res.status_code != 200:
                return {}
            data = res.json()
            if data.get("code") != 200:
                return {}
            result = {}
            for dev in data.get("data") or []:
                dtype = dev.get("deviceType", "")
                if dtype and dtype[0] in ("W", "F"):
                    continue
                result[dev["sn"]] = dev
            return result
        except Exception:
            _LOGGER.exception("WeHere get devices failed")
            return {}

    async def get_voltage_config(self, lock_model, hw_version):
        user_id = self.entry.data[CONF_USERID]
        token = self.entry.data[CONF_TOKEN]
        url = (
            f"{BASE_URL}/api/lock/getAllInfo1?language={LANGUAGE}"
            f"&userId={user_id}&version={VERSION}&token={token}"
        )
        try:
            res = await self.hass.async_add_executor_job(
                functools.partial(requests.get, url, headers=HEADERS, timeout=20)
            )
            if res.status_code != 200:
                return None
            data = res.json()
            if data.get("code") != 200:
                return None
            for cfg in data.get("data", {}).get("voltageCfg", []):
                if (
                    cfg.get("fdeviceType") == lock_model
                    and cfg.get("fhardwareVersion") == hw_version
                ):
                    return cfg
        except Exception:
            _LOGGER.exception("WeHere voltage configuration lookup failed")
        return None

    async def _request(self, method, url, retries=3):
        last = None
        for attempt in range(max(1, retries)):
            try:
                fn = functools.partial(
                    requests.request, method, url, headers=HEADERS, timeout=15
                )
                response = await self.hass.async_add_executor_job(fn)
                if response.status_code >= 500 and attempt + 1 < retries:
                    await asyncio.sleep(0.75 * (attempt + 1))
                    continue
                return response
            except (requests.RequestException, OSError) as err:
                last = err
                if attempt + 1 < retries:
                    await asyncio.sleep(0.75 * (attempt + 1))
        raise RuntimeError(str(last) if last else "WeHere cloud request failed")

    async def operate_lock(self, device, unlock: bool):
        sn = device.sn
        gateway = device.config.get("gateway")
        if not gateway:
            raise RuntimeError(f"No gateway found for lock {sn}")

        mark = "1" if unlock else "2"
        url = (
            f"{BASE_URL}/api/lock/lockOrUnlockChildDevice?language={LANGUAGE}"
            f"&sn={gateway}&userId={self.entry.data[CONF_USERID]}"
            f"&uuid={uuid.uuid4()}&version={VERSION}&mark={mark}"
            f"&childDeviceSn={sn}&token={self.entry.data[CONF_TOKEN]}"
        )
        res = await self._request("POST", url, retries=3)
        if res.status_code != 200:
            raise RuntimeError(f"Cloud HTTP error {res.status_code}")

        data = res.json()
        if data.get("code") != 200:
            raise RuntimeError(
                f"Cloud command failed: {data.get('info', data.get('code'))}"
            )
        return True
