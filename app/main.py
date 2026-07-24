import logging

from dotenv import load_dotenv

# Docker Composeの変数展開("$"を含む値、特にbcryptハッシュを誤解釈する)を
# 避けるため、環境変数はenvironment:/env_file:を使わずファイルマウント経由で
# 直接読み込む。他のモジュールが起動時にos.environを参照するため、必ず
# それらをimportするより前に実行すること。
load_dotenv("/secrets/app.env")

from fastapi import Depends, FastAPI, HTTPException
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
# static webui (SPA) — 必ずAPIルートの後に登録すること
# ============================================================
app.mount("/", StaticFiles(directory="/webui", html=True), name="webui")
