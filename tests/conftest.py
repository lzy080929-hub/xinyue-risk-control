from __future__ import annotations

from pathlib import Path

import pytest
from werkzeug.security import generate_password_hash

from app import create_app
from config import (
    BEHAVIOR_METRICS_VERSION,
    CONSENT_VERSION,
    EXPERIMENT_VERSION,
    FORM_VERSION,
    SCALE_VERSION,
)
from extensions import db

TEST_ADMIN_USERNAME = "researcher"
TEST_ADMIN_PASSWORD = "Stage1-test-only-password-42"


def make_test_config(database_path: Path) -> dict:
    return {
        "TESTING": True,
        "IS_PRODUCTION": False,
        "SECRET_KEY": "test-secret-key-not-for-production-0123456789",
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path.as_posix()}",
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "SQLALCHEMY_ENGINE_OPTIONS": {"connect_args": {"timeout": 30}},
        "MAX_CONTENT_LENGTH": 1_000_000,
        "ADMIN_USERNAME": TEST_ADMIN_USERNAME,
        "ADMIN_PASSWORD_HASH": generate_password_hash(TEST_ADMIN_PASSWORD),
        "ALLOW_TEST_MODE": True,
        "SESSION_COOKIE_SECURE": False,
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": "Lax",
        "PERMANENT_SESSION_LIFETIME": 12 * 60 * 60,
        "CONSENT_VERSION": CONSENT_VERSION,
        "EXPERIMENT_VERSION": EXPERIMENT_VERSION,
        "SCALE_VERSION": SCALE_VERSION,
        "BEHAVIOR_METRICS_VERSION": BEHAVIOR_METRICS_VERSION,
        "FORM_VERSION": FORM_VERSION,
    }


@pytest.fixture
def app(tmp_path):
    database_path = tmp_path / "stage1-test.sqlite3"
    application = create_app(make_test_config(database_path))
    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def database_path(tmp_path):
    return tmp_path / "stage1-test.sqlite3"
