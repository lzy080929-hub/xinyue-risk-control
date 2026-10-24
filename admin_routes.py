from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlsplit
import ipaddress
import re
import threading

from flask import (
    Blueprint,
    abort,
    current_app,
    redirect,
    render_template,
    request,
    session as web_session,
    url_for,
    jsonify, Response,
)
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import selectinload

from extensions import db
from models import BehaviorSummary, ParticipantSession, iso_utc
from research_export import csv_text
from werkzeug.security import generate_password_hash
from dotenv import set_key
from zoneinfo import ZoneInfo
from security import (
    admin_required,
    check_admin_credentials,
    ensure_csrf_token,
    rotate_csrf_token,
    validate_csrf,
)
from survey import REVERSE_ITEM_NUMBERS, SUBSCALE_LABELS, SURVEY_ITEMS
from validation import GRADE_LABELS, PURPOSE_LABELS

bp = Blueprint("admin", __name__, url_prefix="/admin")
_setup_lock = threading.Lock()


def _setup_available():
    if current_app.config.get("IS_PRODUCTION") or current_app.config.get("ADMIN_PASSWORD_HASH"):
        return False
    try:
        local = ipaddress.ip_address(request.remote_addr or "").is_loopback
    except ValueError:
        return False
    return local and urlsplit(request.host_url).hostname in {"127.0.0.1", "localhost", "::1"}


@bp.route("/setup", methods=["GET", "POST"])
def local_setup():
    if not _setup_available():
        abort(404)
    error = None
    if request.method == "POST":
        if not validate_csrf(request.form.get("csrf_token")):
            abort(400)
        username, password = request.form.get("username", ""), request.form.get("password", "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{3,50}", username):
            error = "用户名请使用3—50位字母、数字、下划线或连字符。"
        elif len(password) < 12 or len(password) > 200 or password != request.form.get("confirm"):
            error = "请设置至少12位的密码，并确保两次输入一致。"
        else:
            with _setup_lock:
                if not _setup_available():
                    abort(409)
                target = Path(current_app.config["LOCAL_SETUP_FILE"])
                hashed = generate_password_hash(password)
                try:
                    set_key(str(target), "SECRET_KEY", current_app.config["SECRET_KEY"])
                    set_key(str(target), "ADMIN_USERNAME", username)
                    set_key(str(target), "ADMIN_PASSWORD_HASH", hashed)
                except OSError:
                    error = "无法保存本机配置，请确认项目文件夹可写。"
                else:
                    current_app.config["ADMIN_USERNAME"] = username
                    current_app.config["ADMIN_PASSWORD_HASH"] = hashed
                    return redirect(url_for("admin.login"))
    return render_template("admin_setup.html", csrf_token=ensure_csrf_token(), error=error)


def _login_limiter():
    return current_app.extensions["login_limiter"]


def _render_login(
    *, error: str | None = None, status: int = 200
):
    if web_session.get("admin_username"):
        return redirect(url_for("admin.dashboard"))
    configured = bool(
        current_app.config.get("ADMIN_USERNAME")
        and current_app.config.get("ADMIN_PASSWORD_HASH")
    )
    response = current_app.make_response(
        render_template(
            "admin_login.html",
            error=error,
            csrf_token=ensure_csrf_token(),
            admin_configured=configured,
            local_setup_available=_setup_available(),
        )
    )
    response.status_code = status
    return response


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return _render_login()

    if not validate_csrf(request.form.get("csrf_token")):
        return _render_login(error="页面已过期，请重新提交登录。", status=400)

    ip_key = request.remote_addr or "unknown"
    limiter = _login_limiter()
    if limiter.is_limited(ip_key):
        return _render_login(
            error="登录尝试过于频繁，请 15 分钟后再试。", status=429
        )

    if not current_app.config.get("ADMIN_USERNAME") or not current_app.config.get(
        "ADMIN_PASSWORD_HASH"
    ):
        return _render_login(
            error="管理员登录尚未配置，请联系站点维护者。", status=503
        )

    username = request.form.get("username", "")
    password = request.form.get("password", "")
    if not check_admin_credentials(username, password):
        limiter.record_failure(ip_key)
        return _render_login(error="用户名或密码不正确。", status=401)

    limiter.reset(ip_key)
    web_session.clear()
    web_session["admin_username"] = current_app.config["ADMIN_USERNAME"]
    web_session.permanent = True
    rotate_csrf_token()
    return redirect(url_for("admin.dashboard"))


@bp.post("/logout")
@admin_required
def logout():
    if not validate_csrf(request.form.get("csrf_token")):
        abort(400)
    web_session.clear()
    return redirect(url_for("admin.login"))


@bp.get("/")
@admin_required
def dashboard():
    try:
        total = db.session.scalar(select(func.count(ParticipantSession.id))) or 0
        tests = (
            db.session.scalar(
                select(func.count(ParticipantSession.id)).where(
                    ParticipantSession.is_test.is_(True)
                )
            )
            or 0
        )
        submitted = (
            db.session.scalar(
                select(func.count(ParticipantSession.id)).where(
                    ParticipantSession.status == "submitted"
                )
            )
            or 0
        )
        in_progress = total - submitted
        last_batch_at = db.session.scalar(select(func.max(BehaviorSummary.last_batch_at)))
        participants = db.session.scalars(
            _filtered_query()
            .options(
                selectinload(ParticipantSession.draft),
                selectinload(ParticipantSession.submission),
                selectinload(ParticipantSession.behavior_summary),
            )
            .order_by(ParticipantSession.created_at.desc())
            .limit(200)
        ).all()
    except SQLAlchemyError:
        current_app.logger.error("Database read failed: admin dashboard")
        return (
            render_template(
                "admin_error.html",
                message="数据库暂时不可用，无法读取研究数据。",
                csrf_token=ensure_csrf_token(),
            ),
            503,
        )

    return render_template(
        "admin_dashboard.html",
        total=total,
        tests=tests,
        formal=total - tests,
        submitted=submitted,
        in_progress=in_progress,
        last_batch_at=last_batch_at,
        participants=participants,
        csrf_token=ensure_csrf_token(),
        grade_labels=GRADE_LABELS,
        purpose_labels=PURPOSE_LABELS,
        generated_at=datetime.now(timezone.utc),
        filters=request.args,
    )


def _filtered_query(*, export=False):
    query = select(ParticipantSession)
    kind = request.values.get("kind", "formal" if export else "all")
    status = request.values.get("status", "submitted" if export else "all")
    if kind not in {"formal", "test", "all"} or status not in {"all", "submitted", "in_progress"}:
        abort(400)
    if kind != "all":
        query = query.where(ParticipantSession.is_test.is_(kind == "test"))
    if status != "all":
        query = query.where(ParticipantSession.status == status)
    for key, column in (("version", ParticipantSession.experiment_version), ("source", ParticipantSession.source)):
        value = request.values.get(key, "")
        if value:
            if len(value) > 64:
                abort(400)
            query = query.where(column == value)
    for key in ("start", "end"):
        value = request.values.get(key, "")
        if value:
            try:
                bound = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=ZoneInfo("Asia/Shanghai"))
            except ValueError:
                abort(400)
            if key == "end":
                bound += timedelta(days=1)
            bound = bound.astimezone(timezone.utc)
            query = query.where(ParticipantSession.created_at >= bound) if key == "start" else query.where(ParticipantSession.created_at < bound)
    return query


@bp.get("/api/overview")
@admin_required
def overview():
    participants = db.session.scalars(_filtered_query().options(selectinload(ParticipantSession.draft), selectinload(ParticipantSession.behavior_summary)).order_by(ParticipantSession.created_at.desc()).limit(200)).all()
    total = db.session.scalar(select(func.count(ParticipantSession.id))) or 0
    tests = db.session.scalar(select(func.count(ParticipantSession.id)).where(ParticipantSession.is_test.is_(True))) or 0
    submitted = db.session.scalar(select(func.count(ParticipantSession.id)).where(ParticipantSession.status == "submitted")) or 0
    return jsonify({"ok": True, "data": {
        "total": total, "tests": tests, "formal": total - tests, "submitted": submitted,
        "in_progress": total - submitted, "synced_at": iso_utc(datetime.now(timezone.utc)),
        "participants": [{"participant_id": p.public_id, "is_test": p.is_test, "status": p.status, "progress": p.progress,
            "created_at": iso_utc(p.created_at), "saved_at": iso_utc(p.draft.saved_at) if p.draft else None,
            "submitted_at": iso_utc(p.submitted_at), "source": p.source,
            "received_batches": p.behavior_summary.received_batches if p.behavior_summary else 0,
            "received_events": p.behavior_summary.received_events if p.behavior_summary else 0,
            "behavior_status": p.behavior_summary.status if p.behavior_summary else "not_started"} for p in participants],
    }})


@bp.post("/export.csv")
@admin_required
def export_csv():
    if not validate_csrf(request.form.get("csrf_token")):
        abort(400)
    query = _filtered_query(export=True)
    count = db.session.scalar(select(func.count()).select_from(query.subquery())) or 0
    if count > 10000:
        return "记录超过10000条，请按日期或版本缩小导出范围。", 413
    participants = db.session.scalars(query.options(selectinload(ParticipantSession.draft), selectinload(ParticipantSession.submission), selectinload(ParticipantSession.scale_answers), selectinload(ParticipantSession.behavior_summary), selectinload(ParticipantSession.behavior_batches)).order_by(ParticipantSession.id)).all()
    mode = request.form.get("format", "analysis")
    if mode not in {"analysis", "events"}:
        abort(400)
    response = Response(csv_text(participants, events=mode == "events"), content_type="text/csv; charset=utf-8")
    response.headers["Content-Disposition"] = f'attachment; filename="xinyue-{mode}-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}.csv"'
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.get("/participants/<public_id>")
@admin_required
def participant_detail(public_id: str):
    try:
        participant = db.session.scalar(
            select(ParticipantSession)
            .where(ParticipantSession.public_id == public_id)
            .options(
                selectinload(ParticipantSession.draft),
                selectinload(ParticipantSession.submission),
                selectinload(ParticipantSession.behavior_summary),
                selectinload(ParticipantSession.scale_answers),
            )
        )
    except SQLAlchemyError:
        current_app.logger.error("Database read failed: participant detail")
        return (
            render_template(
                "admin_error.html",
                message="数据库暂时不可用，无法读取该记录。",
                csrf_token=ensure_csrf_token(),
            ),
            503,
        )

    if participant is None:
        abort(404)

    form_data = None
    if participant.submission is not None:
        form_data = participant.submission.payload
    elif participant.draft is not None:
        form_data = participant.draft.payload

    submitted_answers = {
        answer.item_number: answer for answer in participant.scale_answers
    }
    draft_answers = {}
    if (
        participant.submission is None
        and participant.draft
        and isinstance(participant.draft.scale_payload, dict)
    ):
        draft_answers = participant.draft.scale_payload

    scale_rows = []
    for number, text in enumerate(SURVEY_ITEMS, start=1):
        saved = submitted_answers.get(number)
        field_name = f"rs_q{number:02d}"
        raw = saved.raw_score if saved else draft_answers.get(field_name)
        scored = saved.scored_score if saved else None
        reverse = (
            saved.is_reverse
            if saved
            else number in REVERSE_ITEM_NUMBERS
        )
        scale_rows.append(
            {
                "number": number,
                "text": text,
                "raw": raw,
                "scored": scored,
                "reverse": reverse,
            }
        )
    scale_answered_count = sum(1 for row in scale_rows if row["raw"] is not None)

    scale_scores = (
        participant.submission.scale_scores
        if participant.submission is not None
        else None
    )
    subscale_rows = []
    if isinstance(scale_scores, dict):
        subscales = scale_scores.get("subscales", {})
        if isinstance(subscales, dict):
            for key in ("ATR", "SN", "PBC", "LRI"):
                score = subscales.get(key)
                if isinstance(score, dict):
                    subscale_rows.append(
                        {
                            "key": key,
                            "label": SUBSCALE_LABELS[key],
                            "total": score.get("total"),
                            "mean": score.get("mean"),
                            "valid_count": score.get("valid_count"),
                            "expected_count": score.get("expected_count"),
                        }
                    )

    historical_without_scale = (
        participant.submission is not None
        and participant.submission.scale_version is None
    )
    scale_debug = {
        "scale_version": (
            participant.submission.scale_version
            if participant.submission is not None
            else participant.scale_version
        ),
        "scoring_version": (
            participant.submission.scoring_version
            if participant.submission is not None
            else None
        ),
        "answers": {
            str(row["number"]): {
                "raw": row["raw"],
                "scored": row["scored"],
                "reverse": row["reverse"],
            }
            for row in scale_rows
            if row["raw"] is not None or row["scored"] is not None
        },
        "scores": scale_scores,
    }

    return render_template(
        "admin_detail.html",
        participant=participant,
        form_data=form_data or {},
        grade_labels=GRADE_LABELS,
        purpose_labels=PURPOSE_LABELS,
        scale_rows=scale_rows,
        scale_answered_count=scale_answered_count,
        subscale_rows=subscale_rows,
        scale_scores=scale_scores,
        historical_without_scale=historical_without_scale,
        scale_debug=scale_debug,
        csrf_token=ensure_csrf_token(),
        behavior_metrics=(participant.behavior_summary.metrics or {}) if participant.behavior_summary else {},
        original_form=form_data.get("form_layout") == "original-eight-page-v1" if form_data else False,
    )
