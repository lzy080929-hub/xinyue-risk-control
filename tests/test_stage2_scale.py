from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select

from config import CONSENT_VERSION
from extensions import db
from models import (
    FormDraft,
    ParticipantSession,
    ScaleAnswer,
    Submission,
)
from survey import (
    ITEM_COUNT,
    LIKERT_LABELS,
    REVERSE_ITEM_NUMBERS,
    SURVEY_ITEMS,
)
from tests.conftest import TEST_ADMIN_PASSWORD, TEST_ADMIN_USERNAME

VALID_FORM = {
    "grade": "junior",
    "monthly_income": 2000,
    "monthly_debt": None,
    "loan_amount": 12000,
    "loan_term_months": 12,
    "loan_purpose": "training",
}
ALL_FOUR = {
    f"rs_q{number:02d}": 4
    for number in range(1, ITEM_COUNT + 1)
}


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def create_session(client, *, is_test: bool = True):
    response = client.post(
        "/api/sessions",
        json={
            "consent": True,
            "consent_version": CONSENT_VERSION,
            "is_test": is_test,
        },
    )
    assert response.status_code == 201, response.get_data(as_text=True)
    data = response.get_json()["data"]
    return data["participant_id"], data["write_token"]


def submit(client, participant_id: str, token: str, answers: dict):
    return client.post(
        f"/api/sessions/{participant_id}/submit",
        json={
            "submission_key": "stage2-test-submission-key-0001",
            "form": VALID_FORM,
            "scale_answers": answers,
            "final_confirmed": True,
        },
        headers=auth(token),
    )


def get_csrf(client) -> str:
    page = client.get("/admin/login")
    assert page.status_code == 200
    match = re.search(rb'name="csrf_token" value="([^"]+)"', page.data)
    assert match
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


def test_participant_page_shows_fixed_29_items_and_likert_legend(client):
    response = client.get("/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert html.count('class="scale-question"') == ITEM_COUNT
    numbers = re.findall(r'data-question-number="(\d+)"', html)
    assert numbers == [str(number) for number in range(1, ITEM_COUNT + 1)]
    positions = [html.index(text) for text in SURVEY_ITEMS]
    assert positions == sorted(positions)
    assert 'name="rs_q01"' in html
    assert 'name="rs_q29"' in html
    assert "1—7 分分别表示" in html
    for value, label in LIKERT_LABELS.items():
        assert f"<b>{value}</b>{label}" in html


def test_draft_saves_scale_answers_and_supports_editing(app, client):
    participant_id, token = create_session(client)
    ten_answers = {
        name: (4 if index < 10 else None)
        for index, name in enumerate(ALL_FOUR)
    }
    first = client.put(
        f"/api/sessions/{participant_id}/draft",
        json={
            "client_seq": 1,
            "form": VALID_FORM,
            "scale_answers": ten_answers,
        },
        headers=auth(token),
    )
    assert first.status_code == 200, first.get_data(as_text=True)
    assert first.get_json()["data"]["progress"] == 42
    assert first.get_json()["data"]["revision"] == 1

    second = client.put(
        f"/api/sessions/{participant_id}/draft",
        json={
            "client_seq": 2,
            "form": dict(VALID_FORM, grade="senior"),
            "scale_answers": ALL_FOUR,
        },
        headers=auth(token),
    )
    assert second.status_code == 200
    assert second.get_json()["data"]["progress"] == 100
    assert second.get_json()["data"]["revision"] == 2

    with app.app_context():
        participant = db.session.execute(select(ParticipantSession)).scalar_one()
        draft = db.session.execute(select(FormDraft)).scalar_one()
        assert participant.progress == 100
        assert draft.client_seq == 2
        assert draft.payload["grade"] == "senior"
        assert len(draft.scale_payload) == ITEM_COUNT
        assert set(draft.scale_payload.values()) == {4}
        # Draft answers are not final answers and must not create scored rows.
        assert db.session.scalar(select(func.count(ScaleAnswer.id))) == 0


def test_missing_final_scale_answer_writes_nothing(app, client):
    participant_id, token = create_session(client)
    incomplete = dict(ALL_FOUR, rs_q17=None)
    response = submit(client, participant_id, token, incomplete)

    assert response.status_code == 400
    body = response.get_json()
    assert body["ok"] is False
    assert body["error"]["code"] == "incomplete_scale"
    assert "17" in body["error"]["message"]

    with app.app_context():
        participant = db.session.execute(select(ParticipantSession)).scalar_one()
        assert participant.status == "in_progress"
        assert participant.progress == 0
        assert db.session.scalar(select(func.count(Submission.id))) == 0
        assert db.session.scalar(select(func.count(ScaleAnswer.id))) == 0


@pytest.mark.parametrize("invalid", [0, 8, True, "4", 4.5])
def test_invalid_scale_answer_values_are_rejected(app, client, invalid):
    participant_id, token = create_session(client)
    answers = dict(ALL_FOUR, rs_q02=invalid)
    response = submit(client, participant_id, token, answers)
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "invalid_payload"
    assert "rs_q02" in response.get_json()["error"]["message"]

    with app.app_context():
        assert db.session.scalar(select(func.count(Submission.id))) == 0
        assert db.session.scalar(select(func.count(ScaleAnswer.id))) == 0


def test_unknown_scale_field_is_rejected(app, client):
    participant_id, token = create_session(client)
    response = submit(
        client, participant_id, token, dict(ALL_FOUR, rs_q30=4)
    )
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "invalid_payload"
    assert "rs_q30" in response.get_json()["error"]["message"]


def test_final_submit_scores_reverse_items_and_persists_raw_answers(app, client):
    participant_id, token = create_session(client)
    answers = dict(ALL_FOUR)
    answers["rs_q07"] = 1  # reverse -> 7
    answers["rs_q23"] = 7  # reverse -> 1
    answers["rs_q29"] = 2  # reverse -> 6

    response = submit(client, participant_id, token, answers)
    assert response.status_code == 200, response.get_data(as_text=True)
    data = response.get_json()["data"]
    assert set(data) == {
        "behavior_status",
        "participant_id",
        "status",
        "submitted_at",
        "receipt_id",
        "submission_key",
        "already_submitted",
    }
    response_text = response.get_data(as_text=True)
    assert "ATR" not in response_text
    assert "scale_scores" not in response_text
    assert "subscales" not in response_text

    with app.app_context():
        participant = db.session.execute(select(ParticipantSession)).scalar_one()
        submission = db.session.execute(select(Submission)).scalar_one()
        rows = db.session.execute(
            select(ScaleAnswer).order_by(ScaleAnswer.item_number)
        ).scalars().all()
        scores = submission.scale_scores["subscales"]

        assert participant.status == "submitted"
        assert participant.progress == 100
        assert submission.scale_version == "repayment-29-v1"
        assert submission.scoring_version == "repayment-29-scoring-v1"
        assert len(rows) == ITEM_COUNT
        assert sum(1 for row in rows if row.is_reverse) == len(
            REVERSE_ITEM_NUMBERS
        )

        assert scores["ATR"]["total"] == 35
        assert scores["ATR"]["mean"] == 4.375
        assert scores["ATR"]["valid_count"] == 8
        assert scores["ATR"]["expected_count"] == 8
        assert scores["SN"]["total"] == 32
        assert scores["SN"]["mean"] == 4
        assert scores["PBC"]["total"] == 29
        assert scores["PBC"]["mean"] == 3.625
        assert scores["PBC"]["valid_count"] == 8
        assert scores["LRI"]["total"] == 22
        assert scores["LRI"]["mean"] == 4.4
        assert scores["LRI"]["valid_count"] == 5

        by_number = {row.item_number: row for row in rows}
        assert by_number[7].raw_score == 1
        assert by_number[7].scored_score == 7
        assert by_number[7].is_reverse is True
        assert by_number[23].raw_score == 7
        assert by_number[23].scored_score == 1
        assert by_number[29].raw_score == 2
        assert by_number[29].scored_score == 6
        assert by_number[1].raw_score == 4
        assert by_number[1].scored_score == 4
        assert by_number[1].is_reverse is False


def test_repeat_final_submit_does_not_duplicate_scale_rows(app, client):
    participant_id, token = create_session(client)
    first = submit(client, participant_id, token, ALL_FOUR)
    assert first.status_code == 200
    receipt = first.get_json()["data"]["receipt_id"]

    replay = submit(
        client,
        participant_id,
        token,
        dict(ALL_FOUR, rs_q01=7),
    )
    assert replay.status_code == 200
    assert replay.get_json()["data"]["receipt_id"] == receipt
    assert replay.get_json()["data"]["already_submitted"] is True

    with app.app_context():
        assert db.session.scalar(select(func.count(Submission.id))) == 1
        assert db.session.scalar(select(func.count(ScaleAnswer.id))) == ITEM_COUNT


@pytest.mark.parametrize(
    ("version_field", "old_value"),
    [
        ("experiment_version", "xinyue-stage1-v1"),
        ("scale_version", "repayment-29-v0"),
    ],
)
def test_old_protocol_session_cannot_mix_into_stage_two(
    app, client, version_field, old_value
):
    participant_id, token = create_session(client)
    with app.app_context():
        participant = db.session.execute(select(ParticipantSession)).scalar_one()
        setattr(participant, version_field, old_value)
        db.session.commit()

    draft = client.put(
        f"/api/sessions/{participant_id}/draft",
        json={
            "client_seq": 1,
            "form": VALID_FORM,
            "scale_answers": ALL_FOUR,
        },
        headers=auth(token),
    )
    assert draft.status_code == 409
    assert draft.get_json()["error"]["code"] == "protocol_version_mismatch"

    final = submit(client, participant_id, token, ALL_FOUR)
    assert final.status_code == 409
    assert final.get_json()["error"]["code"] == "protocol_version_mismatch"

    with app.app_context():
        assert db.session.scalar(select(func.count(FormDraft.id))) == 0
        assert db.session.scalar(select(func.count(Submission.id))) == 0
        assert db.session.scalar(select(func.count(ScaleAnswer.id))) == 0


def test_admin_detail_shows_draft_raw_answers_without_scores(app, client):
    participant_id, token = create_session(client)
    draft_answers = {
        name: (5 if index < 10 else None)
        for index, name in enumerate(ALL_FOUR)
    }
    response = client.put(
        f"/api/sessions/{participant_id}/draft",
        json={
            "client_seq": 1,
            "form": VALID_FORM,
            "scale_answers": draft_answers,
        },
        headers=auth(token),
    )
    assert response.status_code == 200

    login_admin(client)
    detail = client.get(f"/admin/participants/{participant_id}")
    assert detail.status_code == 200
    html = detail.get_data(as_text=True)
    assert "草稿：仅展示自动保存的原始答案" in html
    assert "提交后计分" in html
    assert "该会话尚未最终提交" in html
    assert "29 题原始答案" in html
    assert "10 / 29 已作答" in html
    assert "score-card" not in html


def test_stage_one_submission_is_kept_without_backfilled_scale_data(app, client):
    now = datetime.now(timezone.utc)
    with app.app_context():
        participant = ParticipantSession(
            public_id="XY-LEGACY000001",
            token_hash="0" * 64,
            is_test=False,
            status="submitted",
            progress=100,
            consent_version="consent-stage1-v1",
            consented_at=now,
            experiment_version="xinyue-stage1-v1",
            scale_version="repayment-29-v1",
            behavior_metrics_version="behavior-schema-v1",
            created_at=now,
            updated_at=now,
            last_seen_at=now,
            submitted_at=now,
            submission_key="legacy-stage-one-submission-0001",
            receipt_id=str(uuid.uuid4()),
        )
        db.session.add(participant)
        db.session.flush()
        db.session.add(
            Submission(
                participant=participant,
                submission_key=participant.submission_key,
                receipt_id=participant.receipt_id,
                payload=VALID_FORM,
                content_hash="0" * 64,
                form_version="application-v1",
                scale_version=None,
                scoring_version=None,
                scale_scores=None,
                submitted_at=now,
            )
        )
        db.session.commit()

    login_admin(client)
    detail = client.get("/admin/participants/XY-LEGACY000001")
    assert detail.status_code == 200
    html = detail.get_data(as_text=True)
    assert "阶段一历史记录，未采集量表答案" in html
    assert "不会为历史记录补造" in html
    assert "（阶段一未采集）" in html
    assert "（已保存原始答案）" not in html
    assert "29 题原始答案" not in html
    assert "还款态度（ATR）" not in html
    assert "score-card" not in html

    with app.app_context():
        assert db.session.scalar(select(func.count(ScaleAnswer.id))) == 0
        submission = db.session.execute(select(Submission)).scalar_one()
        assert submission.scale_version is None
        assert submission.scoring_version is None
        assert submission.scale_scores is None
