from __future__ import annotations

import hashlib
import re
import sqlite3
from unittest.mock import patch

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from app import create_app
from config import CONSENT_VERSION
from extensions import db
from models import (
    BehaviorBatch,
    BehaviorSummary,
    FormDraft,
    ParticipantSession,
    ScaleAnswer,
    Submission,
)
from survey import ITEM_COUNT, REVERSE_ITEM_NUMBERS
from tests.conftest import TEST_ADMIN_PASSWORD, TEST_ADMIN_USERNAME, make_test_config

VALID_FORM = {
    "grade": "junior",
    "monthly_income": 2000,
    "monthly_debt": None,
    "loan_amount": 12000,
    "loan_term_months": 12,
    "loan_purpose": "training",
}
VALID_SCALE = {
    f"rs_q{number:02d}": (number % 7) + 1
    for number in range(1, ITEM_COUNT + 1)
}


def create_session(client, *, is_test: bool = True, consent: bool = True):
    response = client.post(
        "/api/sessions",
        json={
            "consent": consent,
            "consent_version": CONSENT_VERSION,
            "is_test": is_test,
        },
    )
    return response


def assert_api_error(response, status: int, code: str | None = None):
    assert response.status_code == status
    body = response.get_json()
    assert body is not None
    assert body["ok"] is False
    if code:
        assert body["error"]["code"] == code


def session_credentials(client):
    response = create_session(client)
    assert response.status_code == 201
    data = response.get_json()["data"]
    return data["participant_id"], data["write_token"]


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def draft_payload(
    seq: int, form: dict | None = None, scale_answers: dict | None = None
) -> dict:
    payload = {"client_seq": seq, "form": dict(form or VALID_FORM)}
    if scale_answers is not None:
        payload["scale_answers"] = dict(scale_answers)
    return payload


def final_payload(
    key: str, form: dict | None = None, scale_answers: dict | None = None
) -> dict:
    return {
        "submission_key": key,
        "form": dict(form or VALID_FORM),
        "scale_answers": dict(scale_answers or VALID_SCALE),
        "final_confirmed": True,
    }


def submit(client, participant_id, token, key="stage1-test-submission-key-0001"):
    return client.post(
        f"/api/sessions/{participant_id}/submit",
        json=final_payload(key),
        headers=auth(token),
    )


def get_csrf(client) -> str:
    page = client.get("/admin/login")
    assert page.status_code == 200
    match = re.search(rb'name="csrf_token" value="([^"]+)"', page.data)
    assert match, "login page should contain a CSRF token"
    return match.group(1).decode("utf-8")


def login_admin(client) -> None:
    csrf = get_csrf(client)
    response = client.post(
        "/admin/login",
        data={
            "username": TEST_ADMIN_USERNAME,
            "password": TEST_ADMIN_PASSWORD,
            "csrf_token": csrf,
        },
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/admin/")


def test_consent_is_required_and_credentials_are_server_generated(app, client):
    missing = client.post("/api/sessions", json={"consent_version": CONSENT_VERSION})
    assert_api_error(missing, 400, "invalid_payload")

    refused = create_session(client, consent=False)
    assert_api_error(refused, 400, "consent_required")

    stale = client.post(
        "/api/sessions",
        json={"consent": True, "consent_version": "old-consent-version"},
    )
    assert_api_error(stale, 409, "consent_version_mismatch")

    response = create_session(client, is_test=True)
    assert response.status_code == 201
    data = response.get_json()["data"]
    assert data["participant_id"].startswith("TEST-")
    assert data["status"] == "in_progress"
    assert data["consent_version"] == CONSENT_VERSION
    assert len(data["write_token"]) >= 32

    with app.app_context():
        participant = db.session.execute(select(ParticipantSession)).scalar_one()
        assert participant.public_id != data["write_token"]
        assert participant.token_hash == hashlib.sha256(
            data["write_token"].encode("utf-8")
        ).hexdigest()
        assert participant.consent_version == CONSENT_VERSION
        assert participant.consented_at is not None
        assert participant.submitted_at is None


def test_test_mode_can_be_disabled(app, client):
    app.config["ALLOW_TEST_MODE"] = False
    response = create_session(client, is_test=True)
    assert_api_error(response, 403, "test_mode_disabled")


def test_public_id_or_a_foreign_token_cannot_write_another_session(app, client):
    public_a, token_a = session_credentials(client)
    public_b, token_b = session_credentials(client)

    assert_api_error(
        client.put(
            f"/api/sessions/{public_a}/draft",
            json=draft_payload(1),
            headers=auth(token_b),
        ),
        401,
        "unauthorized",
    )
    assert_api_error(
        client.put(
            f"/api/sessions/{public_b}/draft",
            json=draft_payload(1),
            headers=auth(token_a),
        ),
        401,
        "unauthorized",
    )
    assert_api_error(
        client.put(
            f"/api/sessions/{public_a}/draft",
            json=draft_payload(1),
            headers=auth("forged-token-value"),
        ),
        401,
        "unauthorized",
    )
    assert_api_error(
        client.put(
            f"/api/sessions/{public_a}/draft",
            json=draft_payload(1),
        ),
        401,
        "unauthorized",
    )

    with app.app_context():
        assert db.session.scalar(select(func.count(FormDraft.id))) == 0


def test_draft_validation_preserves_null_and_zero_and_rejects_stale_seq(app, client):
    public_id, token = session_credentials(client)
    partial = dict(VALID_FORM, monthly_income=0, monthly_debt=None, loan_amount=None)
    complete_with_explicit_zero = dict(
        VALID_FORM, monthly_income=0, monthly_debt=None
    )

    first = client.put(
        f"/api/sessions/{public_id}/draft",
        json=draft_payload(1, partial),
        headers=auth(token),
    )
    assert first.status_code == 200
    assert first.get_json()["data"]["revision"] == 1
    assert first.get_json()["data"]["progress"] == 9
    assert first.get_json()["data"]["saved_at"].endswith("Z")

    second = client.put(
        f"/api/sessions/{public_id}/draft",
        json=draft_payload(2, complete_with_explicit_zero),
        headers=auth(token),
    )
    assert second.status_code == 200
    assert second.get_json()["data"]["revision"] == 2
    assert second.get_json()["data"]["progress"] == 12

    duplicate = client.put(
        f"/api/sessions/{public_id}/draft",
        json=draft_payload(2, complete_with_explicit_zero),
        headers=auth(token),
    )
    assert duplicate.status_code == 200
    assert duplicate.get_json()["data"]["duplicate"] is True
    assert duplicate.get_json()["data"]["revision"] == 2

    stale = client.put(
        f"/api/sessions/{public_id}/draft",
        json=draft_payload(1, dict(VALID_FORM, grade="freshman")),
        headers=auth(token),
    )
    assert_api_error(stale, 409, "stale_draft")

    with app.app_context():
        participant = db.session.execute(select(ParticipantSession)).scalar_one()
        assert participant.progress == 12
        draft = participant.draft
        assert draft.client_seq == 2
        assert draft.payload["monthly_income"] == 0
        assert draft.payload["monthly_debt"] is None
        assert draft.payload["grade"] == "junior"
        assert draft.scale_payload["rs_q01"] is None
        assert len(draft.scale_payload) == ITEM_COUNT


def test_invalid_field_ranges_and_unknown_fields_are_rejected(app, client):
    public_id, token = session_credentials(client)

    for form, field_name in (
        (dict(VALID_FORM, loan_amount=99), "loan_amount"),
        (dict(VALID_FORM, loan_term_months=61), "loan_term_months"),
        (dict(VALID_FORM, monthly_income="2000"), "monthly_income"),
        (dict(VALID_FORM, unknown_field="x"), "form"),
    ):
        response = client.put(
            f"/api/sessions/{public_id}/draft",
            json=draft_payload(1, form),
            headers=auth(token),
        )
        assert_api_error(response, 400, "invalid_payload")
        assert field_name in response.get_json()["error"]["message"]


def test_behavior_batches_are_incremental_deduplicated_and_out_of_order_safe(app, client):
    public_id, token = session_credentials(client)
    url = f"/api/sessions/{public_id}/behavior-batches"
    event_2 = {
        "type": "page_view",
        "phase": "application",
        "page": 2,
        "client_time_ms": 2000,
    }
    event_1 = {
        "type": "page_view",
        "phase": "application",
        "page": 1,
        "client_time_ms": 1000,
    }

    second = client.post(
        url,
        json={"batch_id": "batch-seq-0002", "batch_seq": 2, "events": [event_2]},
        headers=auth(token),
    )
    assert second.status_code == 200
    assert second.get_json()["data"]["received_batches"] == 1

    first = client.post(
        url,
        json={"batch_id": "batch-seq-0001", "batch_seq": 1, "events": [event_1]},
        headers=auth(token),
    )
    assert first.status_code == 200
    assert first.get_json()["data"]["received_batches"] == 2
    assert first.get_json()["data"]["received_events"] == 2

    duplicate = client.post(
        url,
        json={"batch_id": "batch-seq-0002", "batch_seq": 2, "events": [event_2]},
        headers=auth(token),
    )
    assert duplicate.status_code == 200
    assert duplicate.get_json()["data"]["duplicate"] is True
    assert duplicate.get_json()["data"]["received_batches"] == 2
    assert duplicate.get_json()["data"]["received_events"] == 2

    seq_conflict = client.post(
        url,
        json={"batch_id": "different-batch-id", "batch_seq": 2, "events": [event_2]},
        headers=auth(token),
    )
    assert_api_error(seq_conflict, 409, "batch_seq_conflict")

    forbidden_content = {
        "type": "input_event",
        "phase": "application",
        "field": "monthly_income",
        "value": "2000",
    }
    unsafe = client.post(
        url,
        json={
            "batch_id": "batch-unsafe-0003",
            "batch_seq": 3,
            "events": [forbidden_content],
        },
        headers=auth(token),
    )
    assert_api_error(unsafe, 400, "invalid_payload")
    assert "不得包含输入正文" in unsafe.get_json()["error"]["message"]

    with app.app_context():
        assert db.session.scalar(select(func.count(BehaviorBatch.id))) == 2
        summary = db.session.execute(select(BehaviorSummary)).scalar_one()
        assert summary.received_batches == 2
        assert summary.received_events == 2
        assert summary.status == "received"


def test_final_submit_is_idempotent_and_blocks_late_drafts(app, client):
    public_id, token = session_credentials(client)
    draft = client.put(
        f"/api/sessions/{public_id}/draft",
        json=draft_payload(1),
        headers=auth(token),
    )
    assert draft.status_code == 200

    first = submit(client, public_id, token)
    assert first.status_code == 200
    first_data = first.get_json()["data"]
    assert first_data["status"] == "submitted"
    assert first_data["already_submitted"] is False
    assert first_data["receipt_id"]
    assert first_data["submitted_at"].endswith("Z")

    replay = submit(client, public_id, token)
    assert replay.status_code == 200
    replay_data = replay.get_json()["data"]
    assert replay_data["already_submitted"] is True
    assert replay_data["receipt_id"] == first_data["receipt_id"]
    assert replay_data["submitted_at"] == first_data["submitted_at"]

    changed = final_payload(
        "stage1-test-submission-key-9999",
        dict(VALID_FORM, loan_amount=99999),
    )
    altered_replay = client.post(
        f"/api/sessions/{public_id}/submit",
        json=changed,
        headers=auth(token),
    )
    assert altered_replay.status_code == 200
    assert altered_replay.get_json()["data"]["receipt_id"] == first_data["receipt_id"]

    late_draft = client.put(
        f"/api/sessions/{public_id}/draft",
        json=draft_payload(2, dict(VALID_FORM, loan_amount=5000)),
        headers=auth(token),
    )
    assert_api_error(late_draft, 409, "already_submitted")

    late_batch = client.post(
        f"/api/sessions/{public_id}/behavior-batches",
        json={
            "batch_id": "late-batch-0001",
            "batch_seq": 1,
            "events": [{"type": "page_view", "phase": "application", "page": 1}],
        },
        headers=auth(token),
    )
    assert_api_error(late_batch, 409, "already_submitted")

    with app.app_context():
        participant = db.session.execute(select(ParticipantSession)).scalar_one()
        submission = db.session.execute(select(Submission)).scalar_one()
        answers = db.session.execute(
            select(ScaleAnswer).order_by(ScaleAnswer.item_number)
        ).scalars().all()
        assert participant.status == "submitted"
        assert participant.progress == 100
        assert participant.receipt_id == first_data["receipt_id"]
        assert db.session.scalar(select(func.count(Submission.id))) == 1
        assert submission.payload["loan_amount"] == 12000
        assert submission.payload["monthly_debt"] is None
        assert participant.submitted_at is not None
        assert submission.scale_version == "repayment-29-v1"
        assert submission.scoring_version == "repayment-29-scoring-v1"
        assert set(submission.scale_scores["subscales"]) == {
            "ATR",
            "SN",
            "PBC",
            "LRI",
        }
        assert len(answers) == ITEM_COUNT
        reverse_row = next(row for row in answers if row.item_number == 7)
        assert reverse_row.raw_score == VALID_SCALE["rs_q07"]
        assert reverse_row.scored_score == 8 - VALID_SCALE["rs_q07"]
        assert reverse_row.is_reverse is True
        assert sum(1 for row in answers if row.is_reverse) == len(
            REVERSE_ITEM_NUMBERS
        )


def test_final_payload_requires_complete_fields_and_confirmation(app, client):
    public_id, token = session_credentials(client)
    incomplete = dict(VALID_FORM, loan_purpose=None)
    response = client.post(
        f"/api/sessions/{public_id}/submit",
        json={
            "submission_key": "stage1-test-incomplete-0001",
            "form": incomplete,
            "scale_answers": VALID_SCALE,
            "final_confirmed": True,
        },
        headers=auth(token),
    )
    assert_api_error(response, 400, "incomplete_form")

    unconfirmed = client.post(
        f"/api/sessions/{public_id}/submit",
        json={
            "submission_key": "stage1-test-unconfirmed-001",
            "form": VALID_FORM,
            "scale_answers": VALID_SCALE,
            "final_confirmed": False,
        },
        headers=auth(token),
    )
    assert_api_error(unconfirmed, 400, "final_confirmation_required")

    with app.app_context():
        participant = db.session.execute(select(ParticipantSession)).scalar_one()
        assert participant.status == "in_progress"
        assert db.session.scalar(select(func.count(Submission.id))) == 0
        assert db.session.scalar(select(func.count(ScaleAnswer.id))) == 0


def test_database_failure_never_returns_success(app, client):
    public_id, token = session_credentials(client)
    failure = OperationalError("INSERT", None, RuntimeError("database offline"))

    with patch("participant_routes.db.session.commit", side_effect=failure):
        response = submit(client, public_id, token)

    assert_api_error(response, 503, "storage_unavailable")
    assert "保存成功" not in response.get_data(as_text=True)

    with app.app_context():
        participant = db.session.execute(select(ParticipantSession)).scalar_one()
        assert participant.status == "in_progress"
        assert participant.progress == 0
        assert participant.receipt_id is None
        assert participant.submitted_at is None
        assert db.session.scalar(select(func.count(Submission.id))) == 0
        assert db.session.scalar(select(func.count(ScaleAnswer.id))) == 0
        assert db.session.scalar(select(func.count(BehaviorSummary.id))) == 0


def test_admin_requires_login_csrf_and_can_view_saved_records(app, client):
    public_id, token = session_credentials(client)
    client.put(
        f"/api/sessions/{public_id}/draft",
        json=draft_payload(1),
        headers=auth(token),
    )
    submit_response = submit(client, public_id, token)
    assert submit_response.status_code == 200
    receipt_id = submit_response.get_json()["data"]["receipt_id"]

    unauthenticated = client.get("/admin/")
    assert unauthenticated.status_code == 302
    assert "/admin/login" in unauthenticated.headers["Location"]
    assert client.get(f"/admin/participants/{public_id}").status_code == 302

    wrong_csrf = client.post(
        "/admin/login",
        data={
            "username": TEST_ADMIN_USERNAME,
            "password": TEST_ADMIN_PASSWORD,
            "csrf_token": "wrong",
        },
    )
    assert wrong_csrf.status_code == 400
    assert client.get("/admin/").status_code == 302

    csrf = get_csrf(client)
    wrong_password = client.post(
        "/admin/login",
        data={
            "username": TEST_ADMIN_USERNAME,
            "password": "wrong-password",
            "csrf_token": csrf,
        },
    )
    assert wrong_password.status_code == 401
    assert client.get("/admin/").status_code == 302

    login_admin(client)
    dashboard = client.get("/admin/")
    assert dashboard.status_code == 200
    html = dashboard.get_data(as_text=True)
    assert public_id in html
    assert receipt_id not in html  # dashboard shows summary, not every receipt field
    assert "采集概览" in html

    detail = client.get(f"/admin/participants/{public_id}")
    assert detail.status_code == 200
    detail_html = detail.get_data(as_text=True)
    assert public_id in detail_html
    assert receipt_id in detail_html
    assert "12000" in detail_html
    assert "29 题原始答案" in detail_html
    assert "还款态度（ATR）" in detail_html
    assert "主观规范（SN）" in detail_html
    assert "感知行为控制（PBC）" in detail_html
    assert "还款意愿（LRI）" in detail_html
    assert "反向题" in detail_html
    assert "逾期还款对我没有太大影响" in detail_html

    csrf = re.search(rb'name="csrf_token" value="([^"]+)"', dashboard.data).group(1)
    logout = client.post(
        "/admin/logout", data={"csrf_token": csrf.decode("utf-8")}
    )
    assert logout.status_code == 302
    assert client.get("/admin/").status_code == 302


def test_unconfigured_admin_login_fails_closed(app, client):
    app.config["ADMIN_USERNAME"] = ""
    app.config["ADMIN_PASSWORD_HASH"] = ""
    page = client.get("/admin/login")
    assert page.status_code == 200
    assert "管理员凭据尚未配置" in page.get_data(as_text=True)
    csrf = re.search(rb'name="csrf_token" value="([^"]+)"', page.data).group(1)
    response = client.post(
        "/admin/login",
        data={
            "username": "anyone",
            "password": "anything",
            "csrf_token": csrf.decode("utf-8"),
        },
    )
    assert response.status_code == 503
    assert client.get("/admin/").status_code == 302


def test_records_survive_engine_restart(app, client, database_path):
    public_id, token = session_credentials(client)
    response = submit(client, public_id, token)
    assert response.status_code == 200
    receipt = response.get_json()["data"]["receipt_id"]

    with app.app_context():
        db.session.remove()
        db.engine.dispose()

    restarted = create_app(make_test_config(database_path))
    with restarted.app_context():
        participant = db.session.execute(
            select(ParticipantSession).where(
                ParticipantSession.public_id == public_id
            )
        ).scalar_one()
        assert participant.status == "submitted"
        assert participant.receipt_id == receipt
        assert db.session.scalar(select(func.count(Submission.id))) == 1
        db.session.remove()


def test_health_and_database_ready(app, client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok", "database": "ok"}


def test_legacy_collect_endpoint_returns_gone(client):
    response = client.post("/collect", json={"form": {"name": "legacy"}})
    assert response.status_code == 410
    assert response.get_json()["error"]["code"] == "legacy_endpoint_disabled"


def test_explicit_test_mode_is_visible_and_configurable(app, client):
    response = client.get("/?test=1", follow_redirects=True)
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'data-is-test="true"' in html
    assert "测试模式" in html

    app.config["ALLOW_TEST_MODE"] = False
    disabled = client.get("/?test=1", follow_redirects=True)
    html = disabled.get_data(as_text=True)
    assert 'data-is-test="false"' in html
    assert "测试模式：</strong>本次创建的是测试会话" not in html


def test_old_logs_are_not_the_runtime_store():
    from pathlib import Path

    source = Path("app.py").read_text(encoding="utf-8")
    routes = Path("participant_routes.py").read_text(encoding="utf-8")
    assert "behavior_logs.json" not in source + routes
    assert "read_all_logs" not in source + routes
    assert "write_behavior_csv" not in source + routes
