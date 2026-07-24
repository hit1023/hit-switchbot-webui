import datetime
import os

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", "24"))

MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_MINUTES = 5

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
_bearer_scheme = HTTPBearer()

# プロセス内メモリでのログイン失敗回数管理(username -> 失敗時刻のリスト)
_failed_attempts: dict[str, list[datetime.datetime]] = {}


def _secret_key() -> str:
    key = os.environ.get("APP_SECRET_KEY")
    if not key:
        raise RuntimeError("APP_SECRET_KEYが設定されていません。.envを確認してください")
    return key


def verify_credentials(username: str, password: str) -> bool:
    admin_username = os.environ.get("ADMIN_USERNAME", "admin")
    admin_password_hash = os.environ.get("ADMIN_PASSWORD_HASH")
    if not admin_password_hash:
        raise RuntimeError("ADMIN_PASSWORD_HASHが設定されていません。.envを確認してください")
    if username != admin_username:
        return False
    return pwd_context.verify(password, admin_password_hash)


def create_access_token(username: str) -> str:
    expire = datetime.datetime.utcnow() + datetime.timedelta(hours=JWT_EXPIRE_HOURS)
    payload = {"sub": username, "exp": expire}
    return jwt.encode(payload, _secret_key(), algorithm=ALGORITHM)


def is_locked_out(username: str) -> bool:
    now = datetime.datetime.utcnow()
    attempts = [
        t for t in _failed_attempts.get(username, [])
        if (now - t).total_seconds() < LOCKOUT_MINUTES * 60
    ]
    _failed_attempts[username] = attempts
    return len(attempts) >= MAX_LOGIN_ATTEMPTS


def record_failed_attempt(username: str) -> None:
    _failed_attempts.setdefault(username, []).append(datetime.datetime.utcnow())


def clear_failed_attempts(username: str) -> None:
    _failed_attempts.pop(username, None)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
) -> str:
    try:
        payload = jwt.decode(credentials.credentials, _secret_key(), algorithms=[ALGORITHM])
        username = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=401, detail="無効なトークンです")
    except JWTError:
        raise HTTPException(status_code=401, detail="無効なトークンです")
    return username
