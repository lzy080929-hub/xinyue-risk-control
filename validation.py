from __future__ import annotations

import math
import re
from typing import Any

from errors import ApiError
from survey import ITEM_COUNT, LIKERT_MAX, LIKERT_MIN

GRADE_LABELS = {
    "freshman": "本科一年级",
    "sophomore": "本科二年级",
    "junior": "本科三年级",
    "senior": "本科四年级",
    "graduate": "研究生及以上",
    "other_student": "其他在读学生",
}

PURPOSE_LABELS = {
    "tuition": "学费或学习相关支出",
    "living": "生活周转",
    "training": "培训或考试",
    "device": "学习设备",
    "other": "其他",
}

FORM_FIELDS = (
    "grade",
    "monthly_income",
    "monthly_debt",
    "loan_amount",
    "loan_term_months",
    "loan_purpose",
)
ORIGINAL_FIELDS = (
    "form_layout", "nickname", "age", "education", "occupation", "monthly_income",
    "total_debt", "debt_ratio", "loan_amount", "loan_term", "loan_purpose",
    "interest_rate", "interest_rate_confirmed",
)
ORIGINAL_REQUIRED = ("age", "education", "occupation", "loan_amount", "loan_term", "loan_purpose", "interest_rate")
EDUCATION_LABELS = {"high_school": "高中及以下", "college": "大专", "bachelor": "本科", "master_plus": "硕士及以上"}
REQUIRED_FORM_FIELDS = (
    "grade",
    "loan_amount",
    "loan_term_months",
    "loan_purpose",
)
SCALE_FIELDS = tuple(f"rs_q{index:02d}" for index in range(1, ITEM_COUNT + 1))
EVENT_FIELDS = set(FORM_FIELDS) | set(ORIGINAL_FIELDS) | set(SCALE_FIELDS) | {"final_confirmed"}
EVENT_TYPES = {
    "session_start",
    "page_view",
    "field_focus",
    "field_blur",
    "input_event",
    "delete_event",
    "paste_event",
    "visibility_change",
    "page_back",
    "step_advance",
    "navigation_switch",
    "submit_attempt",
    "page_duration", "field_duration", "field_first_input", "field_revisit",
    "field_edit_return", "non_sequential", "field_switch", "hidden_duration",
    "delete_after_input", "session_resume",
}
EVENT_PHASES = {"application", "survey"}
EVENT_VISIBILITY = {"visible", "hidden"}
EVENT_KEYS = {
    "type",
    "phase",
    "field",
    "page",
    "client_time_ms",
    "duration_ms",
    "visibility",
}
BATCH_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
SUBMISSION_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
MAX_EVENTS_PER_BATCH = 200


def _invalid(field: str, message: str) -> ApiError:
    return ApiError(400, "invalid_payload", f"字段 {field}：{message}")


def require_object(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _invalid(field, "必须是 JSON 对象")
    return value


def _require_exact_keys(
    data: dict[str, Any], required: set[str], optional: set[str] = frozenset()
) -> None:
    missing = required - set(data)
    if missing:
        raise _invalid("payload", f"缺少 {', '.join(sorted(missing))}")
    unknown = set(data) - required - optional
    if unknown:
        raise _invalid("payload", f"存在未允许的字段 {', '.join(sorted(unknown))}")


def _as_int(value: Any, field: str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _invalid(field, "必须是整数")
    if isinstance(value, float) and (not math.isfinite(value) or not value.is_integer()):
        raise _invalid(field, "必须是整数")
    integer = int(value)
    if integer < minimum or integer > maximum:
        raise _invalid(field, f"必须在 {minimum} 到 {maximum} 之间")
    return integer


def _optional_int(
    value: Any, field: str, *, minimum: int, maximum: int
) -> int | None:
    if value is None or value == "":
        return None
    return _as_int(value, field, minimum=minimum, maximum=maximum)


def _enum(value: Any, field: str, allowed: dict[str, str]) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or value not in allowed:
        raise _invalid(field, "取值不在允许范围内")
    return value


def normalize_form(raw: Any, *, final: bool) -> dict[str, Any]:
    """Validate fields and preserve blank as null. Unknown keys are rejected."""
    form = require_object(raw, "form")
    if form.get("form_layout") == "original-eight-page-v1":
        return normalize_original_form(form, final=final)
    unknown = set(form) - set(FORM_FIELDS)
    if unknown:
        raise _invalid("form", f"存在未允许的字段 {', '.join(sorted(unknown))}")

    normalized: dict[str, Any] = {
        "grade": _enum(form.get("grade"), "grade", GRADE_LABELS),
        "monthly_income": _optional_int(
            form.get("monthly_income"), "monthly_income", minimum=0, maximum=100_000
        ),
        "monthly_debt": _optional_int(
            form.get("monthly_debt"), "monthly_debt", minimum=0, maximum=1_000_000
        ),
        "loan_amount": _optional_int(
            form.get("loan_amount"), "loan_amount", minimum=100, maximum=100_000
        ),
        "loan_term_months": _optional_int(
            form.get("loan_term_months"), "loan_term_months", minimum=1, maximum=60
        ),
        "loan_purpose": _enum(form.get("loan_purpose"), "loan_purpose", PURPOSE_LABELS),
    }

    if final:
        empty = [field for field in REQUIRED_FORM_FIELDS if normalized[field] is None]
        if empty:
            raise ApiError(
                400,
                "incomplete_form",
                "以下必填项尚未完成：" + "、".join(empty),
            )
    return normalized


def _short_text(value: Any, field: str, maximum: int) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or len(value.strip()) > maximum or any(ord(c) < 32 for c in value):
        raise _invalid(field, f"请填写不超过 {maximum} 字的文本")
    return value.strip() or None


def normalize_original_form(form: dict, *, final: bool) -> dict[str, Any]:
    unknown = set(form) - set(ORIGINAL_FIELDS)
    if unknown:
        raise _invalid("form", "存在未允许的字段 " + ", ".join(sorted(unknown)))
    normalized = {
        "form_layout": "original-eight-page-v1",
        "nickname": _short_text(form.get("nickname"), "nickname", 40),
        "age": _optional_int(form.get("age"), "age", minimum=18, maximum=80),
        "education": _enum(form.get("education"), "education", EDUCATION_LABELS),
        "occupation": _short_text(form.get("occupation"), "occupation", 50),
        "monthly_income": _optional_int(form.get("monthly_income"), "monthly_income", minimum=0, maximum=1_000_000),
        "total_debt": _optional_int(form.get("total_debt"), "total_debt", minimum=0, maximum=10_000_000),
        "loan_amount": _optional_int(form.get("loan_amount"), "loan_amount", minimum=100, maximum=100_000),
        "loan_term": _optional_int(form.get("loan_term"), "loan_term", minimum=1, maximum=60),
        "loan_purpose": _short_text(form.get("loan_purpose"), "loan_purpose", 100),
        "interest_rate": form.get("interest_rate") if form.get("interest_rate") not in (None, "") else None,
        "interest_rate_confirmed": form.get("interest_rate_confirmed", False),
    }
    rate = normalized["interest_rate"]
    if rate is not None and (isinstance(rate, bool) or not isinstance(rate, (int, float)) or rate not in (8.5, 10.5, 12.5)):
        raise _invalid("interest_rate", "请选择页面提供的模拟年化利率")
    if not isinstance(normalized["interest_rate_confirmed"], bool):
        raise _invalid("interest_rate_confirmed", "必须是布尔值")
    income, debt = normalized["monthly_income"], normalized["total_debt"]
    normalized["debt_ratio"] = round(debt / income * 100, 2) if income and debt is not None else None
    if final:
        missing = [k for k in ORIGINAL_REQUIRED if normalized[k] is None]
        if missing:
            raise ApiError(400, "incomplete_form", "请补齐申请信息：" + "、".join(missing))
        if not normalized["interest_rate_confirmed"]:
            raise ApiError(400, "rate_confirmation_required", "请先确认模拟利率说明")
    return normalized


def normalize_scale_answers(
    raw: Any, *, final: bool
) -> dict[str, int | None]:
    """Normalize all 29 fixed answer slots without converting blanks to zero."""
    data = require_object({} if raw is None else raw, "scale_answers")
    unknown = set(data) - set(SCALE_FIELDS)
    if unknown:
        raise _invalid(
            "scale_answers",
            f"存在未允许的题号 {', '.join(sorted(unknown))}",
        )

    normalized: dict[str, int | None] = {}
    missing_numbers: list[int] = []
    for number, field_name in enumerate(SCALE_FIELDS, start=1):
        value = data.get(field_name)
        if value is None or value == "":
            normalized[field_name] = None
            missing_numbers.append(number)
            continue
        if isinstance(value, bool) or not isinstance(value, int):
            raise _invalid(field_name, "必须是 1—7 的整数或留空")
        if value < LIKERT_MIN or value > LIKERT_MAX:
            raise _invalid(field_name, f"必须在 {LIKERT_MIN} 到 {LIKERT_MAX} 之间")
        normalized[field_name] = value

    if final and missing_numbers:
        shown = "、".join(str(number) for number in missing_numbers[:8])
        suffix = " 等" if len(missing_numbers) > 8 else ""
        raise ApiError(
            400,
            "incomplete_scale",
            f"量表还有 {len(missing_numbers)} 题未作答（第 {shown}{suffix} 题），"
            "请补齐后再提交。",
        )
    return normalized


def compute_progress(
    normalized_form: dict[str, Any],
    scale_answers: dict[str, int | None] | None = None,
) -> int:
    required = ORIGINAL_REQUIRED if normalized_form.get("form_layout") == "original-eight-page-v1" else REQUIRED_FORM_FIELDS
    completed_form = sum(
        1 for field in required if normalized_form.get(field) is not None
    )
    completed_scale = sum(
        1
        for value in (scale_answers or {}).values()
        if value is not None
    )
    total_required = len(required) + ITEM_COUNT
    return round((completed_form + completed_scale) / total_required * 100)


def validate_consent_payload(payload: Any, expected_consent_version: str) -> dict[str, Any]:
    data = require_object(payload, "payload")
    _require_exact_keys(
        data,
        required={"consent", "consent_version"},
        optional={"is_test", "client_context", "source"},
    )
    if data["consent"] is not True:
        raise ApiError(400, "consent_required", "必须先明确同意知情说明")
    if data["consent_version"] != expected_consent_version:
        raise ApiError(
            409,
            "consent_version_mismatch",
            "知情同意版本已更新，请刷新页面重新阅读后再开始",
        )
    is_test = data.get("is_test", False)
    if not isinstance(is_test, bool):
        raise _invalid("is_test", "必须是布尔值")
    context = require_object(data.get("client_context", {}), "client_context")
    _require_exact_keys(context, set(), {"device_type", "browser", "viewport_width", "viewport_height", "input_type_supported"})
    cleaned = {}
    for key in ("viewport_width", "viewport_height"):
        if key in context:
            cleaned[key] = _as_int(context[key], key, minimum=1, maximum=20000)
    for key, allowed in (("device_type", {"mobile", "tablet", "desktop"}), ("browser", {"wechat", "chrome", "safari", "firefox", "edge", "other"})):
        if key in context:
            if context[key] not in allowed:
                raise _invalid(key, "取值无效")
            cleaned[key] = context[key]
    if "input_type_supported" in context:
        if not isinstance(context["input_type_supported"], bool):
            raise _invalid("input_type_supported", "必须是布尔值")
        cleaned["input_type_supported"] = context["input_type_supported"]
    source = data.get("source") or None
    if source is not None and (not isinstance(source, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", source)):
        raise _invalid("source", "只允许64位以内的字母、数字、下划线或连字符")
    return {"is_test": is_test, "client_context": cleaned, "source": source}


def validate_draft_payload(payload: Any) -> dict[str, Any]:
    data = require_object(payload, "payload")
    _require_exact_keys(
        data, required={"client_seq", "form"}, optional={"scale_answers"}
    )
    client_seq = _as_int(
        data["client_seq"], "client_seq", minimum=1, maximum=1_000_000_000
    )
    normalized = normalize_form(data["form"], final=False)
    scale_answers = normalize_scale_answers(data.get("scale_answers"), final=False)
    return {
        "client_seq": client_seq,
        "form": normalized,
        "scale_answers": scale_answers,
        "progress": compute_progress(normalized, scale_answers),
    }


def validate_final_payload(payload: Any) -> dict[str, Any]:
    data = require_object(payload, "payload")
    _require_exact_keys(
        data,
        required={"submission_key", "form", "scale_answers", "final_confirmed"},
        optional={"behavior_manifest"},
    )
    key = data["submission_key"]
    if not isinstance(key, str) or not SUBMISSION_KEY_RE.fullmatch(key):
        raise _invalid("submission_key", "格式无效")
    if data["final_confirmed"] is not True:
        raise ApiError(400, "final_confirmation_required", "请先完成最终确认")
    normalized = normalize_form(data["form"], final=True)
    scale_answers = normalize_scale_answers(data["scale_answers"], final=True)
    return {
        "submission_key": key,
        "form": normalized,
        "scale_answers": scale_answers,
        "final_confirmed": True,
        "behavior_manifest": validate_manifest(data.get("behavior_manifest")),
    }


def validate_manifest(raw: Any) -> dict | None:
    if raw is None:
        return None
    data = require_object(raw, "behavior_manifest")
    _require_exact_keys(data, {"batch_count", "event_count", "dropped_events"})
    return {k: _as_int(data[k], k, minimum=0, maximum=1_000_000) for k in data}


def _validate_event(event: Any, index: int) -> dict[str, Any]:
    if not isinstance(event, dict):
        raise _invalid(f"events[{index}]", "必须是 JSON 对象")
    unknown = set(event) - EVENT_KEYS
    if unknown:
        raise _invalid(
            f"events[{index}]",
            f"不允许记录字段 {', '.join(sorted(unknown))}；行为事件不得包含输入正文",
        )
    event_type = event.get("type")
    if not isinstance(event_type, str) or event_type not in EVENT_TYPES:
        raise _invalid(f"events[{index}].type", "事件类型无效")

    cleaned: dict[str, Any] = {"type": event_type}
    if "phase" in event:
        if event["phase"] not in EVENT_PHASES:
            raise _invalid(f"events[{index}].phase", "必须为 application 或 survey")
        cleaned["phase"] = event["phase"]
    if "field" in event:
        if event["field"] not in EVENT_FIELDS:
            raise _invalid(f"events[{index}].field", "字段名无效")
        cleaned["field"] = event["field"]
    if "page" in event:
        cleaned["page"] = _as_int(
            event["page"], f"events[{index}].page", minimum=1, maximum=50
        )
    if "client_time_ms" in event:
        cleaned["client_time_ms"] = _as_int(
            event["client_time_ms"],
            f"events[{index}].client_time_ms",
            minimum=0,
            maximum=7 * 24 * 60 * 60 * 1000,
        )
    if "duration_ms" in event:
        cleaned["duration_ms"] = _as_int(
            event["duration_ms"],
            f"events[{index}].duration_ms",
            minimum=0,
            maximum=7 * 24 * 60 * 60 * 1000,
        )
    if "visibility" in event:
        if event["visibility"] not in EVENT_VISIBILITY:
            raise _invalid(
                f"events[{index}].visibility", "必须为 visible 或 hidden"
            )
        cleaned["visibility"] = event["visibility"]
    return cleaned


def validate_behavior_payload(payload: Any) -> dict[str, Any]:
    data = require_object(payload, "payload")
    _require_exact_keys(data, required={"batch_id", "batch_seq", "events"})
    batch_id = data["batch_id"]
    if not isinstance(batch_id, str) or not BATCH_ID_RE.fullmatch(batch_id):
        raise _invalid("batch_id", "必须为 8—64 位字母、数字、下划线或连字符")
    batch_seq = _as_int(
        data["batch_seq"], "batch_seq", minimum=1, maximum=1_000_000
    )
    events = data["events"]
    if not isinstance(events, list) or not events:
        raise _invalid("events", "必须是非空数组")
    if len(events) > MAX_EVENTS_PER_BATCH:
        raise _invalid("events", f"单批最多 {MAX_EVENTS_PER_BATCH} 条")
    cleaned = [_validate_event(event, index) for index, event in enumerate(events)]
    return {
        "batch_id": batch_id,
        "batch_seq": batch_seq,
        "events": cleaned,
        "event_count": len(cleaned),
        "mode": "incremental",
    }
