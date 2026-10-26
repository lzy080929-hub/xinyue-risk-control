"""Optional group RRT. Random branches never reach the server."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo
import hashlib
import hmac
import math
import re

from flask import Blueprint, current_app, jsonify, render_template, request
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from errors import ApiError
from extensions import db
from models import RrtInvitation, RrtResponse
from protocols import EXPERIMENT_V4, RRT_VERSION
from security import admin_required, authenticate_participant

bp = Blueprint("rrt", __name__)


def _commit():
    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        raise ApiError(503, "storage_unavailable", "调查尚未确认保存，请保留页面重试；申请回执不受影响。") from None


def _voucher(participant):
    # Recoverable eligibility credential, not a response ID. Never persisted in
    # the response table. Existing server key stays in memory only.
    message = f"{RRT_VERSION}:{participant.public_id}:{participant.token_hash}".encode()
    return hmac.new(current_app.config["SECRET_KEY"].encode(), message, hashlib.sha256).hexdigest()


@bp.post("/api/sessions/<public_id>/rrt-invitation")
def invite(public_id):
    participant = authenticate_participant(public_id, for_update=True)
    if not participant.is_submitted or participant.experiment_version != EXPERIMENT_V4:
        raise ApiError(409, "rrt_not_eligible", "请先完成并保存新版申请与问卷")
    if request.get_json(silent=True) != {"consent": True}:
        raise ApiError(400, "rrt_consent_required", "请先自愿同意独立调查说明")
    value = _voucher(participant)
    digest = hashlib.sha256(value.encode()).hexdigest()
    invitation = db.session.scalar(select(RrtInvitation).where(RrtInvitation.participant_id == participant.id))
    if invitation is None:
        invitation = RrtInvitation(participant_id=participant.id, token_hash=digest,
            protocol_version=RRT_VERSION, redeemed=False)
        db.session.add(invitation)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            invitation = db.session.scalar(select(RrtInvitation).where(RrtInvitation.participant_id == participant.id))
            if invitation is None:
                raise ApiError(409, "rrt_invitation_conflict", "调查凭证准备失败，请重试") from None
        except SQLAlchemyError:
            db.session.rollback()
            raise ApiError(503, "storage_unavailable", "调查凭证尚未准备成功，请稍后重试") from None
    return jsonify(ok=True, data={"protocol_version": RRT_VERSION,
        "already_recorded": invitation.redeemed, "voucher": None if invitation.redeemed else value})


@bp.post("/api/rrt/responses")
def respond():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or set(payload) != {"choice", "protocol_version"}:
        raise ApiError(400, "invalid_payload", "只允许提交混合回答和方案版本")
    if not isinstance(payload["choice"], str) or payload["choice"] not in {"yes", "no", "skipped"} or payload["protocol_version"] != RRT_VERSION:
        raise ApiError(400, "invalid_payload", "调查回答或版本无效")
    header = request.headers.get("Authorization", "")
    value = header[7:] if header.startswith("Bearer ") else ""
    if not re.fullmatch(r"[a-f0-9]{64}", value):
        raise ApiError(401, "unauthorized", "调查凭证无效")
    digest = hashlib.sha256(value.encode()).hexdigest()
    invitation = db.session.scalar(select(RrtInvitation).where(RrtInvitation.token_hash == digest).with_for_update())
    if invitation is None or invitation.protocol_version != RRT_VERSION:
        raise ApiError(401, "unauthorized", "调查凭证无效")
    if invitation.redeemed:
        return jsonify(ok=True, data={"recorded": True, "already_recorded": True})
    # Only the invitation determines test/formal status; clients cannot choose.
    from models import ParticipantSession
    participant = db.session.get(ParticipantSession, invitation.participant_id)
    claimed = db.session.execute(update(RrtInvitation).where(
        RrtInvitation.id == invitation.id, RrtInvitation.redeemed.is_(False)).values(redeemed=True))
    if claimed.rowcount != 1:
        db.session.rollback()
        return jsonify(ok=True, data={"recorded": True, "already_recorded": True})
    db.session.add(RrtResponse(protocol_version=RRT_VERSION, is_test=participant.is_test,
        batch_day=datetime.now(ZoneInfo("Asia/Shanghai")).date(), choice=payload["choice"]))
    _commit()
    return jsonify(ok=True, data={"recorded": True, "already_recorded": False})


def estimate(yes: int, no: int, skipped: int) -> dict:
    n = yes + no
    result = {"version": RRT_VERSION, "yes": yes, "no": no, "valid": n,
        "skipped_after_consent": skipped, "mixed_yes_rate": None, "estimate_raw": None,
        "ci95_raw": None, "estimate_constrained": None}
    if n:
        q, z = yes / n, 1.959963984540054
        center = (q + z*z/(2*n)) / (1 + z*z/n)
        margin = z * math.sqrt(q*(1-q)/n + z*z/(4*n*n)) / (1 + z*z/n)
        raw = 2*q - 0.5
        result.update(mixed_yes_rate=q, estimate_raw=raw,
            ci95_raw=[2*(center-margin)-0.5, 2*(center+margin)-0.5],
            estimate_constrained=min(1, max(0, raw)))
    return result


def _summary():
    kind = request.args.get("kind", "formal")
    if kind not in {"formal", "test"}:
        raise ApiError(400, "invalid_payload", "请分别查看正式组或测试组")
    rows = db.session.execute(select(RrtResponse.choice, func.count()).where(
        RrtResponse.protocol_version == RRT_VERSION, RrtResponse.is_test.is_(kind == "test")
    ).group_by(RrtResponse.choice)).all()
    counts = dict(rows)
    return kind, estimate(counts.get("yes", 0), counts.get("no", 0), counts.get("skipped", 0))


@bp.get("/admin/api/rrt-summary")
@admin_required
def summary_api():
    kind, result = _summary()
    return jsonify(ok=True, data={"kind": kind, **result})


@bp.get("/admin/rrt")
@admin_required
def summary_page():
    kind, result = _summary()
    return render_template("admin_rrt.html", kind=kind, result=result)
