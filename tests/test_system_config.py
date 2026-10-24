from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _base_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["SECRET_KEY"] = "system-test-secret-key-01234567890123456789"
    env["ADMIN_USERNAME"] = "test-admin"
    env["ADMIN_PASSWORD_HASH"] = (
        "scrypt:32768:8:1$test$dummy-hash-not-used-by-these-checks"
    )
    return env


def test_fresh_database_migration_applies(tmp_path):
    database_path = tmp_path / "fresh-migration.sqlite3"
    env = _base_env()
    env["APP_ENV"] = "development"
    env["DATABASE_URL"] = "sqlite:///" + database_path.as_posix()

    result = subprocess.run(
        [sys.executable, "-m", "flask", "--app", "app", "db", "upgrade"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert database_path.is_file()

    connection = sqlite3.connect(database_path)
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "select name from sqlite_master where type='table'"
            )
        }
        assert {
            "participant_sessions",
            "form_drafts",
            "submissions",
            "scale_answers",
            "behavior_batches",
            "behavior_summaries",
            "alembic_version",
        }.issubset(tables)
        version = connection.execute(
            "select version_num from alembic_version"
        ).fetchone()
        assert version and version[0] == "a83c6f2d901e"
        assert (
            connection.execute(
                "select count(*) from participant_sessions"
            ).fetchone()[0]
            == 0
        )
        draft_columns = {
            row[1] for row in connection.execute("pragma table_info(form_drafts)")
        }
        assert "scale_payload" in draft_columns
        submission_columns = {
            row[1] for row in connection.execute("pragma table_info(submissions)")
        }
        assert {"scale_version", "scoring_version", "scale_scores"}.issubset(
            submission_columns
        )
    finally:
        connection.close()


def test_stage_two_migration_preserves_existing_stage_one_record(tmp_path):
    database_path = tmp_path / "stage-one-upgrade.sqlite3"
    env = _base_env()
    env["APP_ENV"] = "development"
    env["DATABASE_URL"] = "sqlite:///" + database_path.as_posix()

    old_upgrade = subprocess.run(
        [
            sys.executable,
            "-m",
            "flask",
            "--app",
            "app",
            "db",
            "upgrade",
            "f864ba4e0a76",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    assert old_upgrade.returncode == 0, old_upgrade.stderr

    connection = sqlite3.connect(database_path)
    try:
        now = "2026-10-20 12:00:00.000000"
        cursor = connection.execute(
            """
            insert into participant_sessions (
                public_id, token_hash, is_test, status, progress,
                consent_version, consented_at, experiment_version,
                scale_version, behavior_metrics_version, created_at,
                updated_at, last_seen_at, submitted_at, submission_key,
                receipt_id
            ) values (?, ?, 0, 'submitted', 100, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "XY-LEGACY000001",
                "0" * 64,
                "consent-stage1-v1",
                now,
                "xinyue-stage1-v1",
                "repayment-29-v1",
                "behavior-schema-v1",
                now,
                now,
                now,
                now,
                "legacy-stage-one-submission-0001",
                "00000000-0000-4000-8000-000000000001",
            ),
        )
        participant_id = cursor.lastrowid
        connection.execute(
            """
            insert into submissions (
                participant_id, submission_key, receipt_id, payload,
                content_hash, form_version, submitted_at
            ) values (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                participant_id,
                "legacy-stage-one-submission-0001",
                "00000000-0000-4000-8000-000000000001",
                '{"grade":"junior"}',
                "0" * 64,
                "application-v1",
                now,
            ),
        )
        connection.commit()
    finally:
        connection.close()

    new_upgrade = subprocess.run(
        [sys.executable, "-m", "flask", "--app", "app", "db", "upgrade"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    assert new_upgrade.returncode == 0, new_upgrade.stderr

    connection = sqlite3.connect(database_path)
    try:
        version = connection.execute(
            "select version_num from alembic_version"
        ).fetchone()
        assert version and version[0] == "a83c6f2d901e"
        submission = connection.execute(
            """
            select submission_key, form_version, scale_version,
                   scoring_version, scale_scores
            from submissions
            """
        ).fetchone()
        assert submission is not None
        assert submission[0] == "legacy-stage-one-submission-0001"
        assert submission[1] == "application-v1"
        assert submission[2] is None
        assert submission[3] is None
        assert submission[4] is None
        assert (
            connection.execute(
                "select count(*) from participant_sessions"
            ).fetchone()[0]
            == 1
        )
        assert (
            connection.execute("select count(*) from scale_answers").fetchone()[0]
            == 0
        )
    finally:
        connection.close()


def test_production_startup_fails_without_database_url():
    env = _base_env()
    env["APP_ENV"] = "production"
    env["DATABASE_URL"] = ""

    result = subprocess.run(
        [sys.executable, "-c", "import app"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        timeout=120,
    )
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert b"DATABASE_URL" in combined


def test_production_startup_rejects_sqlite():
    env = _base_env()
    env["APP_ENV"] = "production"
    env["DATABASE_URL"] = "sqlite:///should-not-be-used-online.sqlite3"

    result = subprocess.run(
        [sys.executable, "-c", "import app"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        timeout=120,
    )
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert b"PostgreSQL" in combined
