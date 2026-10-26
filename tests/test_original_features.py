from __future__ import annotations

import csv
import io
import re
from sqlalchemy import select

from extensions import db
from models import ParticipantSession, Submission
from tests.test_stage1 import session_credentials, auth, login_admin, get_csrf
from config import CONSENT_VERSION

FORM = {"form_layout": "original-eight-page-v1", "nickname": "同学", "age": 20,
        "education": "bachelor", "occupation": "大学生", "monthly_income": 2000,
        "total_debt": 5000, "loan_amount": 12000, "loan_term": 12,
        "loan_purpose": "学习设备", "interest_rate": 8.5, "interest_rate_confirmed": True}
ANSWERS = {f"rs_q{i:02d}": 4 for i in range(1, 30)}


def finish(client, public_id, token, *, form=None, manifest=None):
    payload = {"submission_key": "original-feature-test-" + public_id, "form": form or FORM,
               "scale_answers": ANSWERS, "final_confirmed": True}
    if manifest is not None:
        payload["behavior_manifest"] = manifest
    return client.post(f"/api/sessions/{public_id}/submit", json=payload, headers=auth(token))


def test_original_eight_page_flow_and_local_assets(client):
    page = client.get("/apply").get_data(as_text=True)
    assert re.findall(r'class="form-page" data-page="(\d+)"', page) == [str(i) for i in range(1, 9)]
    for field in ("total_debt", "debt_ratio", "interest_rate", "loan_term", "interest_rate_confirmed"):
        assert f'id="{field}"' in page
    assert "cdn.tailwindcss.com" not in page
    assert 'src="/static/behavior_tracker.js"' in page
    assert page.count('class="scale-question"') == 29


def test_interface_version_is_recorded_without_backfilling_history(app, client):
    from research_export import analysis_row
    response = client.post("/api/sessions", json={"consent": True, "consent_version": CONSENT_VERSION,
        "is_test": True, "client_context": {"ui_version": "bank-application-v1"}})
    assert response.status_code == 201
    public_id = response.get_json()["data"]["participant_id"]
    old_id, _ = session_credentials(client)
    with app.app_context():
        participants = {p.public_id: p for p in db.session.scalars(select(ParticipantSession))}
        assert analysis_row(participants[public_id])["ui_version"] == "bank-application-v1"
        assert analysis_row(participants[old_id])["ui_version"] is None
    assert client.post("/api/sessions", json={"consent": True, "consent_version": CONSENT_VERSION,
        "client_context": {"ui_version": {"unrestricted": "data"}}}).status_code == 400


def test_cross_interface_resume_is_flagged_separately(app, client):
    public_id, token = session_credentials(client)
    response = client.post(f"/api/sessions/{public_id}/behavior-batches", json={
        "batch_id": "interface-resume-batch", "batch_seq": 1,
        "events": [{"type": "session_resume"}, {"type": "interface_change"}]}, headers=auth(token))
    assert response.status_code == 200
    with app.app_context():
        participant = db.session.scalar(select(ParticipantSession).where(ParticipantSession.public_id == public_id))
        assert participant.behavior_summary.metrics["quality_flags"] == ["interface_changed_during_session", "page_resumed"]


def test_original_form_keeps_total_debt_and_computes_ratio(app, client):
    public_id, token = session_credentials(client)
    response = finish(client, public_id, token, form=dict(FORM, debt_ratio=1))
    assert response.status_code == 200
    with app.app_context():
        saved = db.session.execute(select(Submission)).scalar_one()
        assert saved.payload["total_debt"] == 5000
        assert saved.payload["debt_ratio"] == 250
        assert "monthly_debt" not in saved.payload


def test_original_zero_income_and_unanswered_debt_stay_distinct(app, client):
    public_id, token = session_credentials(client)
    assert finish(client, public_id, token, form=dict(FORM, monthly_income=0, total_debt=None)).status_code == 200
    with app.app_context():
        form = db.session.execute(select(Submission)).scalar_one().payload
        assert form["monthly_income"] == 0 and form["total_debt"] is None and form["debt_ratio"] is None


def test_rate_confirmation_and_original_range_validation(client):
    public_id, token = session_credentials(client)
    assert finish(client, public_id, token, form=dict(FORM, interest_rate_confirmed=False)).status_code == 400
    assert finish(client, public_id, token, form=dict(FORM, age=17)).status_code == 400
    assert finish(client, public_id, token, form=dict(FORM, interest_rate=99)).status_code == 400


def test_behavior_summaries_and_manifest_are_separate_from_answers(app, client):
    public_id, token = session_credentials(client)
    events = [
        {"type": "page_duration", "phase": "application", "page": 3, "duration_ms": 1200, "client_time_ms": 1200},
        {"type": "field_duration", "phase": "application", "page": 3, "field": "monthly_income", "duration_ms": 800},
        {"type": "delete_event", "phase": "application", "field": "monthly_income"},
        {"type": "paste_event", "phase": "application", "field": "total_debt"},
        {"type": "page_duration", "phase": "survey", "page": 7, "duration_ms": 400},
        {"type": "hidden_duration", "phase": "application", "duration_ms": 30000},
    ]
    batch = {"batch_id": "original-batch-one", "batch_seq": 1, "events": events}
    assert client.post(f"/api/sessions/{public_id}/behavior-batches", json=batch, headers=auth(token)).status_code == 200
    assert finish(client, public_id, token, manifest={"batch_count": 1, "event_count": 6, "dropped_events": 0}).status_code == 200
    with app.app_context():
        summary = db.session.execute(select(ParticipantSession)).scalar_one().behavior_summary
        assert summary.status == "complete"
        assert summary.metrics["application_visible_ms"] == 1200
        assert summary.metrics["survey_visible_ms"] == 400
        assert summary.metrics["fields"]["monthly_income"]["focus_ms"] == 800
        assert summary.metrics["fields"]["monthly_income"]["delete_count"] == 1
        assert summary.metrics["fields"]["total_debt"]["paste_count"] == 1


def test_missing_behavior_batch_does_not_claim_complete(app, client):
    public_id, token = session_credentials(client)
    response = finish(client, public_id, token, manifest={"batch_count": 2, "event_count": 4, "dropped_events": 0})
    assert response.status_code == 200
    assert response.get_json()["data"]["behavior_status"] == "incomplete"
    with app.app_context():
        assert db.session.execute(select(Submission)).scalar_one() is not None


def test_changed_replay_is_rejected_and_text_never_enters_events(client):
    public_id, token = session_credentials(client)
    url = f"/api/sessions/{public_id}/behavior-batches"
    batch = {"batch_id": "stable-batch-id-one", "batch_seq": 1, "events": [{"type": "paste_event", "field": "total_debt"}]}
    assert client.post(url, json=batch, headers=auth(token)).status_code == 200
    altered = dict(batch, events=[{"type": "input_event", "field": "total_debt"}])
    assert client.post(url, json=altered, headers=auth(token)).status_code == 409
    forbidden = dict(batch, batch_id="another-batch-id", batch_seq=2, events=[{"type": "input_event", "field": "total_debt", "text": "private"}])
    assert client.post(url, json=forbidden, headers=auth(token)).status_code == 400


def test_session_read_requires_owner_token(client):
    public_id, token = session_credentials(client)
    assert client.get(f"/api/sessions/{public_id}").status_code == 401
    assert client.get(f"/api/sessions/{public_id}", headers=auth(token)).get_json()["data"]["status"] == "in_progress"


def test_csv_default_excludes_test_drafts_and_neutralizes_formulas(client):
    first = client.post("/api/sessions", json={"consent": True, "consent_version": CONSENT_VERSION, "is_test": False}).get_json()["data"]
    assert finish(client, first["participant_id"], first["write_token"], form=dict(FORM, nickname="=1+1")).status_code == 200
    test_id, token = session_credentials(client)
    assert finish(client, test_id, token).status_code == 200
    assert client.get("/admin/api/overview").status_code == 401
    assert client.post("/admin/export.csv").status_code == 302
    login_admin(client)
    assert client.post("/admin/export.csv").status_code == 400
    csrf = re.search(rb'name="csrf_token" value="([^"]+)"', client.get("/admin/").data).group(1).decode()
    response = client.post("/admin/export.csv", data={"csrf_token": csrf})
    rows = list(csv.DictReader(io.StringIO(response.get_data(as_text=True).lstrip("\ufeff"))))
    assert len(rows) == 1
    assert rows[0]["participant_id"] == first["participant_id"]
    assert rows[0]["nickname"] == "'=1+1"
    assert rows[0]["total_debt"] == "5000" and rows[0]["monthly_debt"] == ""
    assert rows[0]["ATR_total"] == "32"
    assert "token" not in response.get_data(as_text=True).lower()


def test_overview_filter_reports_only_selected_records(client):
    public_id, token = session_credentials(client)
    assert finish(client, public_id, token).status_code == 200
    login_admin(client)
    assert len(client.get("/admin/api/overview?kind=test&status=submitted").get_json()["data"]["participants"]) == 1
    assert client.get("/admin/api/overview?kind=formal").get_json()["data"]["participants"] == []
    assert client.get("/admin/api/overview?start=invalid").status_code == 400


def test_local_setup_is_csrf_protected_and_saves_hash_only(app, client, tmp_path):
    app.config.update(ADMIN_USERNAME="", ADMIN_PASSWORD_HASH="", LOCAL_SETUP_FILE=str(tmp_path / "local.env"))
    assert client.post("/admin/setup", data={}).status_code == 400
    page = client.get("/admin/setup")
    token = re.search(rb'name="csrf_token" value="([^"]+)"', page.data).group(1).decode()
    password = "test-local-only-password-42"
    result = client.post("/admin/setup", data={"csrf_token": token, "username": "local_admin", "password": password, "confirm": password})
    assert result.status_code == 302
    contents = (tmp_path / "local.env").read_text()
    assert password not in contents and "ADMIN_PASSWORD_HASH" in contents
    assert client.get("/admin/setup").status_code == 404


def test_local_setup_cannot_be_used_in_production_or_rebound_host(app, client):
    app.config.update(ADMIN_PASSWORD_HASH="", ADMIN_USERNAME="")
    assert client.get("/admin/setup", headers={"Host": "foreign.example"}).status_code == 404
    app.config["IS_PRODUCTION"] = True
    assert client.get("/admin/setup").status_code == 404
