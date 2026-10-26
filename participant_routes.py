from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from errors import ApiError
from extensions import db
from models import (
    BehaviorBatch,
    BehaviorSummary,
    FormDraft,
    ParticipantSession,
    ScaleAnswer,
    Submission,
    iso_utc,
)
from security import authenticate_participant, new_write_token
from survey import score_survey
from behavior import summarize_events
from protocols import CONSENT_V4, EXPERIMENT_V4, FORM_V4, BEHAVIOR_V4, assigned_terms
from validation import (
    SCALE_FIELDS,
    validate_behavior_payload,
    validate_consent_payload,
    validate_draft_payload,
    validate_final_payload,
)

bp = Blueprint("participant_api", __name__, url_prefix="/api")


def _require_current_protocol(participant: ParticipantSession) -> None:
    """Support frozen v3 and v4 without accepting earlier incompatible protocols."""
    if (
        participant.experiment_version not in {current_app.config["EXPERIMENT_VERSION"], EXPERIMENT_V4}
        or participant.scale_version != current_app.config["SCALE_VERSION"]
    ):
        raise ApiError(
            409,
            "protocol_version_mismatch",
            "该参与会话来自旧版研究流程，不能继续写入当前数据。请返回首页重新参与。",
        )


    if participant.experiment_version == EXPERIMENT_V4 and not participant.terms_snapshot:
        raise ApiError(409, "protocol_version_mismatch", "本会话的展示条款缺失，请联系项目负责人")


def _score_submission_answers(
    scale_answers: dict[str, int | None],
) -> tuple[dict[str, object], dict[int, dict[str, object]]]:
    numeric_answers: dict[int, int | None] = {
        number: scale_answers[field_name]
        for number, field_name in enumerate(SCALE_FIELDS, start=1)
    }
    if any(value is None for value in numeric_answers.values()):
        raise ApiError(400, "incomplete_scale", "量表尚未全部完成，不能提交。")
    result = score_survey(numeric_answers)  # type: ignore[arg-type]
    snapshot = {
        "scale_version": result["scale_version"],
        "scoring_version": result["scoring_version"],
        "subscales": result["subscales"],
        "all_29_compatibility": result["all_29_compatibility"],
    }
    return snapshot, result["items"]


def _add_scale_answer_rows(
    participant: ParticipantSession,
    scale_answers: dict[str, int | None],
    scored_items: dict[int, dict[str, object]],
    now,
) -> None:
    for number, field_name in enumerate(SCALE_FIELDS, start=1):
        item = scored_items[number]
        db.session.add(
            ScaleAnswer(
                participant=participant,
                item_number=number,
                raw_score=scale_answers[field_name],
                scored_score=item["scored"],
                is_reverse=item["reverse"],
                answered_at=now,
            )
        )


def _json_payload() -> object:
    if not request.is_json:
        raise ApiError(415, "json_required", "请求必须使用 application/json")
    payload = request.get_json(silent=True)
    if payload is None:
        raise ApiError(400, "invalid_json", "JSON 内容无法解析")
    return payload


def _commit(operation: str) -> None:
    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        # Do not log request bodies, credentials, or SQL parameter values.
        current_app.logger.error("Database write failed: %s", operation)
        raise ApiError(
            503,
            "storage_unavailable",
            "服务器暂时无法保存数据。你的填写内容仍在当前页面，请稍后重试。",
        )


def _make_public_id(is_test: bool) -> str:
    prefix = "TEST-" if is_test else "XY-"
    return prefix + secrets.token_hex(6).upper()


def _new_participant(is_test: bool, *, v4: bool = False) -> tuple[ParticipantSession, str]:
    token, token_hash = new_write_token()
    now = datetime.now(timezone.utc)
    participant = ParticipantSession(
        public_id=_make_public_id(is_test),
        token_hash=token_hash,
        is_test=is_test,
        status="in_progress",
        progress=0,
        consent_version=CONSENT_V4 if v4 else current_app.config["CONSENT_VERSION"],
        consented_at=now,
        experiment_version=EXPERIMENT_V4 if v4 else current_app.config["EXPERIMENT_VERSION"],
        scale_version=current_app.config["SCALE_VERSION"],
        behavior_metrics_version=BEHAVIOR_V4 if v4 else current_app.config["BEHAVIOR_METRICS_VERSION"],
        terms_snapshot=assigned_terms() if v4 else None,
        created_at=now,
        updated_at=now,
        last_seen_at=now,
    )
    return participant, token


@bp.post("/sessions")
def create_session():
    payload = _json_payload()
    v4 = payload.get("consent_version") == CONSENT_V4
    consent = validate_consent_payload(
        payload, CONSENT_V4 if v4 else current_app.config["CONSENT_VERSION"]
    )
    is_test = consent["is_test"]
    if is_test and not current_app.config.get("ALLOW_TEST_MODE", False):
        raise ApiError(403, "test_mode_disabled", "当前环境不允许创建测试会话")

    # A unique public code can collide in theory. Retry with a new code rather
    # than exposing an IntegrityError to the participant.
    for attempt in range(5):
        participant, token = _new_participant(is_test, v4=v4)
        participant.client_context = consent["client_context"]
        participant.source = consent["source"]
        db.session.add(participant)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            if attempt == 4:
                raise ApiError(503, "session_create_failed", "暂时无法创建会话，请重试")
            continue
        except SQLAlchemyError:
            db.session.rollback()
            current_app.logger.error("Database write failed: create_session")
            raise ApiError(503, "storage_unavailable", "服务器暂时无法保存会话，请重试")

        response = jsonify(
            {
                "ok": True,
                "data": {
                    "participant_id": participant.public_id,
                    "write_token": token,
                    "status": participant.status,
                    "is_test": participant.is_test,
                    "consent_version": participant.consent_version,
                    "terms": participant.terms_snapshot,
                    "versions": {
                        "experiment": participant.experiment_version,
                        "scale": participant.scale_version,
                        "behavior_metrics": participant.behavior_metrics_version,
                    },
                },
            }
        )
        response.status_code = 201
        return response

    raise ApiError(503, "session_create_failed", "暂时无法创建会话，请重试")


@bp.get("/sessions/<public_id>")
def session_status(public_id: str):
    participant = authenticate_participant(public_id)
    if not participant.is_submitted:
        _require_current_protocol(participant)
    return jsonify({"ok": True, "data": {
        "status": participant.status, "progress": participant.progress,
        "draft_seq": participant.draft.client_seq if participant.draft else 0,
        "receipt": participant.receipt_payload(already_submitted=True) if participant.is_submitted else None,
    }})


@bp.put("/sessions/<public_id>/draft")
def save_draft(public_id: str):
    participant = authenticate_participant(public_id, for_update=True)
    if participant.is_submitted:
        raise ApiError(409, "already_submitted", "该会话已经提交，不能再修改草稿")
    _require_current_protocol(participant)

    draft_data = validate_draft_payload(_json_payload(), terms=participant.terms_snapshot if participant.experiment_version == EXPERIMENT_V4 else None)
    draft = participant.draft
    if draft is not None:
        if draft_data["client_seq"] < draft.client_seq:
            raise ApiError(
                409, "stale_draft", "这次草稿请求早于服务器已保存版本，未覆盖较新内容"
            )
        if draft_data["client_seq"] == draft.client_seq:
            if draft.payload != draft_data["form"] or draft.scale_payload != draft_data["scale_answers"]:
                raise ApiError(409, "draft_seq_conflict", "该草稿序号已用于不同内容，请使用更新的序号")
            return jsonify(
                {
                    "ok": True,
                    "data": {
                        "revision": draft.server_revision,
                        "progress": participant.progress,
                        "saved_at": iso_utc(draft.saved_at),
                        "duplicate": True,
                    },
                }
            )
        draft.payload = draft_data["form"]
        draft.scale_payload = draft_data["scale_answers"]
        draft.client_seq = draft_data["client_seq"]
        draft.server_revision += 1
        draft.saved_at = datetime.now(timezone.utc)
    else:
        draft = FormDraft(
            participant=participant,
            payload=draft_data["form"],
            scale_payload=draft_data["scale_answers"],
            client_seq=draft_data["client_seq"],
            server_revision=1,
            saved_at=datetime.now(timezone.utc),
        )
        db.session.add(draft)

    now = datetime.now(timezone.utc)
    participant.progress = draft_data["progress"]
    participant.last_seen_at = now
    participant.updated_at = now
    _commit("save_draft")

    return jsonify(
        {
            "ok": True,
            "data": {
                "revision": draft.server_revision,
                "progress": participant.progress,
                "saved_at": iso_utc(draft.saved_at),
                "duplicate": False,
            },
        }
    )


def _refresh_behavior_summary(participant: ParticipantSession) -> BehaviorSummary:
    batches = db.session.scalars(select(BehaviorBatch).where(BehaviorBatch.participant_id == participant.id).order_by(BehaviorBatch.batch_seq)).all()
    count = len(batches)
    summary = participant.behavior_summary
    if summary is None:
        summary = BehaviorSummary(participant=participant)
        db.session.add(summary)
    summary.received_batches = count
    summary.received_events = sum(batch.event_count for batch in batches)
    summary.last_batch_at = max((batch.received_at.replace(tzinfo=timezone.utc) if batch.received_at.tzinfo is None else batch.received_at for batch in batches), default=None)
    summary.metrics = summarize_events([event for batch in batches for event in batch.events], participant.client_context)
    # "received" only means some batches are present. It is not a claim that
    # expected behavior data is complete.
    summary.status = "received" if count else "not_started"
    if summary.expected_batches is not None:
        contiguous = (not batches and summary.expected_batches == 0) or (count == summary.expected_batches and batches[0].batch_seq == 1 and batches[-1].batch_seq == summary.expected_batches)
        summary.status = "complete" if contiguous and count > 0 and summary.received_events == summary.expected_events and not summary.dropped_events else "incomplete"
        if summary.dropped_events:
            summary.metrics["quality_flags"].append("event_buffer_overflow")
    summary.updated_at = datetime.now(timezone.utc)
    return summary


@bp.post("/sessions/<public_id>/behavior-batches")
def upload_behavior_batch(public_id: str):
    participant = authenticate_participant(public_id, for_update=True)
    if participant.is_submitted:
        raise ApiError(409, "already_submitted", "该会话已经提交，不能再上传行为批次")
    _require_current_protocol(participant)

    batch_data = validate_behavior_payload(_json_payload())
    existing = db.session.execute(
        select(BehaviorBatch).where(
            BehaviorBatch.participant_id == participant.id,
            BehaviorBatch.batch_id == batch_data["batch_id"],
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.batch_seq != batch_data["batch_seq"] or existing.events != batch_data["events"]:
            raise ApiError(409, "batch_content_conflict", "同一批次标识不能用于不同内容")
        summary = _refresh_behavior_summary(participant)
        _commit("behavior_duplicate_summary")
        return jsonify(
            {
                "ok": True,
                "data": {
                    "batch_id": existing.batch_id,
                    "batch_seq": existing.batch_seq,
                    "duplicate": True,
                    "received_batches": summary.received_batches,
                    "received_events": summary.received_events,
                    "mode": "incremental",
                },
            }
        )

    seq_collision = db.session.execute(
        select(BehaviorBatch.id).where(
            BehaviorBatch.participant_id == participant.id,
            BehaviorBatch.batch_seq == batch_data["batch_seq"],
        )
    ).scalar_one_or_none()
    if seq_collision is not None:
        raise ApiError(
            409,
            "batch_seq_conflict",
            "该批次序号已有不同内容，未写入；请勿改写已上传批次",
        )

    batch = BehaviorBatch(
        participant=participant,
        batch_id=batch_data["batch_id"],
        batch_seq=batch_data["batch_seq"],
        events=batch_data["events"],
        event_count=batch_data["event_count"],
        received_at=datetime.now(timezone.utc),
    )
    db.session.add(batch)
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        # A concurrent retry may have won the unique constraint.
        participant = authenticate_participant(public_id)
        existing = db.session.execute(
            select(BehaviorBatch).where(
                BehaviorBatch.participant_id == participant.id,
                BehaviorBatch.batch_id == batch_data["batch_id"],
            )
        ).scalar_one_or_none()
        if existing is None:
            raise ApiError(409, "batch_conflict", "批次写入冲突，请重新上传")
        if existing.batch_seq != batch_data["batch_seq"] or existing.events != batch_data["events"]:
            raise ApiError(409, "batch_content_conflict", "同一批次标识不能用于不同内容")
        summary = _refresh_behavior_summary(participant)
        _commit("behavior_concurrent_duplicate")
        return jsonify(
            {
                "ok": True,
                "data": {
                    "batch_id": existing.batch_id,
                    "batch_seq": existing.batch_seq,
                    "duplicate": True,
                    "received_batches": summary.received_batches,
                    "received_events": summary.received_events,
                    "mode": "incremental",
                },
            }
        )

    summary = _refresh_behavior_summary(participant)
    participant.last_seen_at = datetime.now(timezone.utc)
    _commit("upload_behavior_batch")

    return jsonify(
        {
            "ok": True,
            "data": {
                "batch_id": batch.batch_id,
                "batch_seq": batch.batch_seq,
                "duplicate": False,
                "received_batches": summary.received_batches,
                "received_events": summary.received_events,
                "mode": "incremental",
            },
        }
    )


@bp.post("/sessions/<public_id>/submit")
def submit(public_id: str):
    participant = authenticate_participant(public_id, for_update=True)

    if participant.is_submitted:
        # A repeated request (including after a lost response) returns the same
        # durable receipt and never creates a second submitted record.
        return jsonify(
            {
                "ok": True,
                "data": participant.receipt_payload(already_submitted=True),
            }
        )
    _require_current_protocol(participant)

    final_data = validate_final_payload(_json_payload(), terms=participant.terms_snapshot if participant.experiment_version == EXPERIMENT_V4 else None)
    form_version = FORM_V4 if participant.experiment_version == EXPERIMENT_V4 else current_app.config["FORM_VERSION"]
    scale_snapshot, scored_items = _score_submission_answers(
        final_data["scale_answers"]
    )
    now = datetime.now(timezone.utc)
    canonical = json.dumps(
        {
            "form": final_data["form"],
            "scale_answers": final_data["scale_answers"],
            "final_confirmed": True,
            "form_version": form_version,
            "scale_version": scale_snapshot["scale_version"],
            "scoring_version": scale_snapshot["scoring_version"],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    submission = Submission(
        participant=participant,
        submission_key=final_data["submission_key"],
        receipt_id=str(uuid.uuid4()),
        payload=final_data["form"],
        content_hash=hashlib.sha256(canonical).hexdigest(),
        form_version=form_version,
        scale_version=scale_snapshot["scale_version"],
        scoring_version=scale_snapshot["scoring_version"],
        scale_scores=scale_snapshot,
        submitted_at=now,
    )
    db.session.add(submission)
    _add_scale_answer_rows(
        participant, final_data["scale_answers"], scored_items, now
    )

    participant.status = "submitted"
    participant.progress = 100
    participant.submitted_at = now
    participant.submission_key = final_data["submission_key"]
    participant.receipt_id = submission.receipt_id
    participant.updated_at = now
    participant.last_seen_at = now
    summary = _refresh_behavior_summary(participant)
    manifest = final_data["behavior_manifest"]
    if manifest is not None:
        summary.expected_batches = manifest["batch_count"]
        summary.expected_events = manifest["event_count"]
        summary.dropped_events = manifest["dropped_events"]
        _refresh_behavior_summary(participant)

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        current_app.logger.error("Database integrity failure: final submit")
        raise ApiError(409, "submission_conflict", "提交发生冲突，请刷新后核对状态")
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.error("Database write failed: final submit")
        raise ApiError(
            503,
            "storage_unavailable",
            "服务器未确认保存成功。请保留当前页面并稍后重试。",
        )

    return jsonify(
        {
            "ok": True,
            "data": participant.receipt_payload(already_submitted=False),
        }
    )
