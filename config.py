from __future__ import annotations

import os
import secrets
from pathlib import Path

from dotenv import load_dotenv

from survey import SCALE_VERSION as SURVEY_SCALE_VERSION

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# These versions are stored on every participant session. Change them only
# together with a documented protocol change; do not silently rename them.
# The questionnaire version is owned by survey.py so the item bank, scoring
# rules, and stored version cannot drift apart.
CONSENT_VERSION = "consent-original-v3"
EXPERIMENT_VERSION = "xinyue-original-v3"
SCALE_VERSION = SURVEY_SCALE_VERSION
BEHAVIOR_METRICS_VERSION = "behavior-original-v2"
FORM_VERSION = "original-eight-page-v1"
# Presentation has its own version; field meanings and study protocol stay stable.
UI_VERSION = "bank-application-v1"


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _normalize_database_url(url: str) -> str:
    url = url.strip()
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


def runtime_environment() -> str:
    explicit = os.environ.get("APP_ENV", "").strip().lower()
    if explicit:
        return explicit
    if os.environ.get("RENDER", "").strip().lower() in {"1", "true", "yes"}:
        return "production"
    return "development"


def build_runtime_config(instance_path: str) -> dict[str, object]:
    """Build config from environment; fail closed for a production deployment."""
    app_env = runtime_environment()
    is_production = app_env == "production"

    database_url = os.environ.get("DATABASE_URL", "").strip()
    if database_url:
        database_url = _normalize_database_url(database_url)
    elif is_production:
        raise RuntimeError(
            "正式环境缺少 DATABASE_URL。请配置持久 PostgreSQL；"
            "程序不会回退到本地 SQLite 或临时文件。"
        )
    else:
        db_path = (Path(instance_path) / "xinyue-dev.sqlite3").resolve()
        database_url = f"sqlite:///{db_path.as_posix()}"

    if is_production and not database_url.startswith("postgresql"):
        raise RuntimeError("正式环境的 DATABASE_URL 必须是 PostgreSQL 连接串。")

    secret_key = os.environ.get("SECRET_KEY", "").strip()
    if is_production:
        if len(secret_key) < 32:
            raise RuntimeError(
                "正式环境缺少足够长的 SECRET_KEY（至少 32 个字符）。"
            )
    elif not secret_key:
        # Development-only fallback. Rotating it merely invalidates local logins.
        secret_key = secrets.token_urlsafe(48)

    admin_username = os.environ.get("ADMIN_USERNAME", "").strip()
    admin_password_hash = os.environ.get("ADMIN_PASSWORD_HASH", "").strip()
    if is_production and (not admin_username or not admin_password_hash):
        raise RuntimeError(
            "正式环境缺少 ADMIN_USERNAME 或 ADMIN_PASSWORD_HASH；"
            "不能启动一个无法进入后台的采集站点。"
        )

    engine_options: dict[str, object] = {"pool_pre_ping": True}
    if database_url.startswith("sqlite"):
        engine_options["connect_args"] = {"timeout": 30}

    return {
        "APP_ENV": app_env,
        "IS_PRODUCTION": is_production,
        "SECRET_KEY": secret_key,
        "SQLALCHEMY_DATABASE_URI": database_url,
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "SQLALCHEMY_ENGINE_OPTIONS": engine_options,
        "MAX_CONTENT_LENGTH": 1_000_000,
        "ADMIN_USERNAME": admin_username,
        "ADMIN_PASSWORD_HASH": admin_password_hash,
        "ALLOW_TEST_MODE": _env_bool("ALLOW_TEST_MODE", default=not is_production),
        "SESSION_COOKIE_NAME": "xinyue_admin",
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": "Lax",
        "SESSION_COOKIE_SECURE": is_production,
        "PERMANENT_SESSION_LIFETIME": 12 * 60 * 60,
        "PREFERRED_URL_SCHEME": "https" if is_production else "http",
        "CONSENT_VERSION": CONSENT_VERSION,
        "EXPERIMENT_VERSION": EXPERIMENT_VERSION,
        "SCALE_VERSION": SCALE_VERSION,
        "BEHAVIOR_METRICS_VERSION": BEHAVIOR_METRICS_VERSION,
        "FORM_VERSION": FORM_VERSION,
        "UI_VERSION": UI_VERSION,
        "LOCAL_SETUP_FILE": str(BASE_DIR / ".env"),
    }
