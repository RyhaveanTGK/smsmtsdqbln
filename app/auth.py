import hashlib
import hmac
import secrets
import time
from collections import defaultdict
from threading import Lock

from fastapi import Depends, HTTPException, Request, status

from .config import get_settings
from .database import get_db

settings = get_settings()
_failed_logins: dict[str, list[float]] = defaultdict(list)
_login_lock = Lock()
MAX_LOGIN_FAILURES = 8
FAILURE_WINDOW_SECONDS = 15 * 60


def _prune_failures(key: str, now: float) -> list[float]:
    recent = [t for t in _failed_logins[key] if now - t < FAILURE_WINDOW_SECONDS]
    _failed_logins[key] = recent
    return recent


def login_allowed(key: str) -> bool:
    with _login_lock:
        return len(_prune_failures(key, time.time())) < MAX_LOGIN_FAILURES


def record_failed_login(key: str) -> None:
    with _login_lock:
        _prune_failures(key, time.time()).append(time.time())


def clear_failed_logins(key: str) -> None:
    with _login_lock:
        _failed_logins.pop(key, None)


def verify_admin(username: str, password: str) -> bool:
    if not settings.admin_password:
        return False
    return hmac.compare_digest(username, settings.admin_username) and hmac.compare_digest(
        password, settings.admin_password
    )


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


async def require_admin(request: Request) -> None:
    if not request.session.get("admin_authenticated"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sessiya bitib.")


async def require_csrf(request: Request, _: None = Depends(require_admin)) -> None:
    expected = request.session.get("csrf_token")
    supplied = request.headers.get("X-CSRF-Token")
    if not expected or not supplied or not hmac.compare_digest(expected, supplied):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF token etibarsızdır.")
