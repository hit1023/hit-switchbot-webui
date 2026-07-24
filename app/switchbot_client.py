import base64
import hashlib
import hmac
import os
import time
import uuid

import httpx

BASE_URL = "https://api.switch-bot.com/v1.1"


class SwitchBotAPIError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"SwitchBot API error {status_code}: {message}")


def _auth_headers() -> dict[str, str]:
    token = os.environ.get("SWITCHBOT_TOKEN")
    secret = os.environ.get("SWITCHBOT_SECRET")
    if not token or not secret:
        raise RuntimeError("SWITCHBOT_TOKEN / SWITCHBOT_SECRETが設定されていません。.envを確認してください")

    nonce = str(uuid.uuid4())
    t = str(round(time.time() * 1000))
    string_to_sign = f"{token}{t}{nonce}".encode("utf-8")
    sign = base64.b64encode(
        hmac.new(secret.encode("utf-8"), string_to_sign, hashlib.sha256).digest()
    ).decode("utf-8").upper()

    return {
        "Authorization": token,
        "sign": sign,
        "t": t,
        "nonce": nonce,
        "Content-Type": "application/json; charset=utf8",
    }


async def _request(method: str, path: str, json: dict | None = None) -> dict:
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=10.0) as client:
        resp = await client.request(method, path, headers=_auth_headers(), json=json)
        resp.raise_for_status()
        body = resp.json()

    if body.get("statusCode") != 100:
        raise SwitchBotAPIError(body.get("statusCode", -1), body.get("message", "unknown error"))
    return body.get("body", {})


async def get_devices() -> dict:
    return await _request("GET", "/devices")


async def get_status(device_id: str) -> dict:
    return await _request("GET", f"/devices/{device_id}/status")


async def send_command(
    device_id: str,
    command: str,
    parameter: str = "default",
    command_type: str = "command",
) -> dict:
    return await _request(
        "POST",
        f"/devices/{device_id}/commands",
        json={"command": command, "parameter": parameter, "commandType": command_type},
    )


async def query_webhook_url() -> dict:
    return await _request("POST", "/webhook/queryWebhook", json={"action": "queryUrl"})


async def setup_webhook(url: str) -> dict:
    return await _request(
        "POST",
        "/webhook/setupWebhook",
        json={"action": "setupWebhook", "url": url, "deviceList": "ALL"},
    )


async def update_webhook(url: str) -> dict:
    return await _request(
        "POST",
        "/webhook/updateWebhook",
        json={"action": "updateWebhook", "config": {"url": url, "enable": True}},
    )
