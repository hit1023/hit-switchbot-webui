import logging
import os

from dotenv import load_dotenv

# Docker Composeの変数展開("$"を含む値、特にbcryptハッシュを誤解釈する)を
# 避けるため、環境変数はenvironment:/env_file:を使わずファイルマウント経由で
# 直接読み込む。他のモジュールが起動時にos.environを参照するため、必ず
# それらをimportするより前に実行すること。
load_dotenv("/secrets/app.env")

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import auth, history, switchbot_client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("hit-switchbot-webui")

app = FastAPI(title="hit-switchbot-webui")


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class CommandRequest(BaseModel):
    command: str
    parameter: str = "default"
    commandType: str = "command"
    deviceName: str = ""


@app.post("/api/login", response_model=LoginResponse)
def login(req: LoginRequest):
    if auth.is_locked_out(req.username):
        raise HTTPException(status_code=429, detail="ログイン試行回数が上限に達しました。5分後に再度お試しください")

    if not auth.verify_credentials(req.username, req.password):
        auth.record_failed_attempt(req.username)
        raise HTTPException(status_code=401, detail="ユーザー名またはパスワードが違います")

    auth.clear_failed_attempts(req.username)
    token = auth.create_access_token(req.username)
    return LoginResponse(access_token=token)


@app.get("/api/devices")
async def list_devices(_user: str = Depends(auth.get_current_user)):
    try:
        return await switchbot_client.get_devices()
    except switchbot_client.SwitchBotAPIError as e:
        raise HTTPException(status_code=502, detail=e.message)


@app.get("/api/devices/{device_id}/status")
async def device_status(device_id: str, _user: str = Depends(auth.get_current_user)):
    try:
        return await switchbot_client.get_status(device_id)
    except switchbot_client.SwitchBotAPIError as e:
        raise HTTPException(status_code=502, detail=e.message)


@app.post("/api/devices/{device_id}/commands")
async def device_command(
    device_id: str, req: CommandRequest, user: str = Depends(auth.get_current_user)
):
    logger.info("command sent: device=%s command=%s parameter=%s", device_id, req.command, req.parameter)
    try:
        result = await switchbot_client.send_command(
            device_id, req.command, req.parameter, req.commandType
        )
        history.record(user, device_id, req.deviceName, req.command, req.parameter, success=True)
        return result
    except switchbot_client.SwitchBotAPIError as e:
        history.record(user, device_id, req.deviceName, req.command, req.parameter, success=False, detail=e.message)
        raise HTTPException(status_code=502, detail=e.message)


@app.get("/api/logs")
def logs(limit: int = 50, _user: str = Depends(auth.get_current_user)):
    return history.list_recent(limit)


# ============================================================
# SwitchBot Webhook — 鍵の物理的な施錠/解錠(アプリ/指紋/キーパッド等、
# 経路を問わない)をリアルタイムに検知してログに記録する。
# URLにWEBHOOK_PATH_TOKENを含めることで、正規のURLを知らない第三者からの
# 書き込みを防ぐ(SwitchBot側はWebhookに署名等の検証手段を提供していないため)。
# ============================================================
@app.post("/api/webhook/switchbot/{token}")
async def switchbot_webhook(token: str, request: Request):
    expected = os.environ.get("WEBHOOK_PATH_TOKEN")
    if not expected or token != expected:
        raise HTTPException(status_code=404)

    body = await request.json()
    events = body if isinstance(body, list) else [body]
    for event in events:
        context = event.get("context", {})
        lock_state = context.get("lockState")
        if lock_state is None:
            continue
        device_mac = context.get("deviceMac", "unknown")
        logger.info("webhook lock event: device=%s lockState=%s", device_mac, lock_state)
        history.record("(device)", device_mac, device_mac, "状態変化", lock_state, success=True)
    return {"result": "ok"}


async def _ensure_webhook_registered() -> None:
    public_base_url = os.environ.get("PUBLIC_BASE_URL")
    webhook_token = os.environ.get("WEBHOOK_PATH_TOKEN")
    if not public_base_url or not webhook_token:
        logger.warning("PUBLIC_BASE_URL/WEBHOOK_PATH_TOKENが未設定のためWebhook登録をスキップします")
        return

    target_url = f"{public_base_url}/api/webhook/switchbot/{webhook_token}"

    # queryWebhookはWebhook未登録の場合statusCode!=100(エラー扱い)を返すため、
    # 「未登録」として扱いsetupWebhookに進む。
    try:
        current = await switchbot_client.query_webhook_url()
        urls = current.get("urls", [])
    except switchbot_client.SwitchBotAPIError:
        urls = []

    try:
        if target_url in urls:
            logger.info("Webhookは登録済みです: %s", target_url)
        elif urls:
            await switchbot_client.update_webhook(target_url)
            logger.info("Webhook URLを更新しました: %s", target_url)
        else:
            await switchbot_client.setup_webhook(target_url)
            logger.info("Webhookを新規登録しました: %s", target_url)
    except switchbot_client.SwitchBotAPIError as e:
        logger.error("Webhook登録に失敗しました: %s", e.message)


@app.on_event("startup")
async def on_startup() -> None:
    await _ensure_webhook_registered()


# ============================================================
# static webui (SPA) — 必ずAPIルートの後に登録すること
# ============================================================
app.mount("/", StaticFiles(directory="/webui", html=True), name="webui")
