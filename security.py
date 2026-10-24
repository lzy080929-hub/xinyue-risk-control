from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from collections import deque
from functools import wraps
from typing import Any, Callable, TypeVar

from flask import current_app, jsonify, redirect, request, session as web_session, url_for
from werkzeug.security import check_password_hash

from errors import ApiError
from extensions import db
from models import ParticipantSession

F = TypeVar("F", bound=Callable[..., Any])


def new_write_token() -> tuple[str, str]:
    """Return (token shown once to the participant, SHA-256 hash stored in DB)."""
    token = secrets.token_urlsafe(32)
    return token, hashlib.sha256(token.encode("utf-8")).hexdigest()


def _token_from_header() -> str | None:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    token = header[7:].strip()
    if not token or len(token) > 200:
        return None
    return token


def authenticate_participant(
    public_id: str, *, for_update: bool = False
) -> ParticipantSession:
    """Resolve a session using both public code and its secret write token."""
    token = _token_from_header()
    if token is None:
        raise ApiError(401, "unauthorized", "参与会话凭证缺失")

    query = db.select(ParticipantSession).where(
        ParticipantSession.public_id == public_id
    )
    if for_update:
        query = query.with_for_update()
    participant = db.session.execute(query).scalar_one_or_none()
    supplied_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    if participant is None or not hmac.compare_digest(
        participant.token_hash, supplied_hash
    ):
        # Do not reveal whether the public code exists.
        raise ApiError(401, "unauthorized", "参与会话凭证无效，请重新打开原链接")
    return participant


def ensure_csrf_token() -> str:
    token = web_session.get("_csrf")
    if not isinstance(token, str) or len(token) < 20:
        token = secrets.token_urlsafe(32)
        web_session["_csrf"] = token
    return token


def rotate_csrf_token() -> str:
    token = secrets.token_urlsafe(32)
    web_session["_csrf"] = token
    return token


def validate_csrf(form_value: str | None) -> bool:
    expected = web_session.get("_csrf")
    if not isinstance(expected, str) or not isinstance(form_value, str):
        return False
    return hmac.compare_digest(expected, form_value)


def admin_required(view: F) -> F:
    @wraps(view)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        if not web_session.get("admin_username"):
            if request.path.startswith("/admin/api/"):
                return jsonify({"ok": False, "error": {"code": "unauthorized", "message": "请重新登录后台"}}), 401
            return redirect(url_for("admin.login"))
        return view(*args, **kwargs)

    return wrapped  # type: ignore[return-value]


def check_admin_credentials(username: Any, password: Any) -> bool:
    expected_username = current_app.config.get("ADMIN_USERNAME", "")
    password_hash = current_app.config.get("ADMIN_PASSWORD_HASH", "")
    if not expected_username or not password_hash:
        return False
    if not isinstance(username, str) or not isinstance(password, str):
        return False
    username_ok = hmac.compare_digest(username, expected_username)
    try:
        password_ok = check_password_hash(password_hash, password)
    except (ValueError, TypeError):
        password_ok = False
    return username_ok and password_ok


class LoginRateLimiter:
    """Small single-process limiter; the deployment uses one web worker."""

    def __init__(self, max_attempts: int = 8, window_seconds: int = 15 * 60):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._attempts: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> deque[float]:
        bucket = self._attempts.setdefault(key, deque())
        cutoff = now - self.window_seconds
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        return bucket

    def is_limited(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            return len(self._prune(key, now)) >= self.max_attempts

    def record_failure(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            self._prune(key, now).append(now)

    def reset(self, key: str) -> None:
        with self._lock:
            self._attempts.pop(key, None)


def api_error_response(error: ApiError):
    response = jsonify(error.as_payload())
    response.status_code = error.status
    return response
