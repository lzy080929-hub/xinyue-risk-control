"""CSV research exports with original and prior-form meanings kept distinct."""
from __future__ import annotations
import csv
import io
import json
from models import iso_utc
from validation import ORIGINAL_FIELDS, FORM_FIELDS

ANALYSIS_FIELDS = list(dict.fromkeys(list(ORIGINAL_FIELDS) + list(FORM_FIELDS)))
BEHAVIOR_FIELDS = ("application_visible_ms", "survey_visible_ms", "total_elapsed_ms", "hidden_duration_ms", "back_navigation_count", "non_sequential_fill_count", "related_field_switch_count", "resume_count", "submit_attempt_count")
TRACKED_FIELDS = ("nickname", "age", "education", "occupation", "monthly_income", "total_debt", "debt_ratio", "loan_amount", "loan_term", "loan_purpose", "interest_rate")
FIELD_METRICS = ("focus_ms", "focus_count", "input_count", "delete_count", "delete_after_input_count", "paste_count", "revisit_count", "return_edit_count", "first_input_latency_ms")
BASE_HEADERS = ["participant_id", "is_test", "status", "source", "created_at", "submitted_at", "experiment_version", "scale_version", "behavior_metrics_version", "form_version", "receipt_id", "behavior_status", "received_batches", "received_events", "expected_batches", "expected_events", "dropped_events", "quality_flags", "device_type", "browser", "viewport_width", "viewport_height"]
HEADERS = BASE_HEADERS + ANALYSIS_FIELDS + [f"rs_q{i:02d}" for i in range(1, 30)] + [f"{key}_{metric}" for key in ("ATR", "SN", "PBC", "LRI") for metric in ("total", "mean", "valid_count")] + list(BEHAVIOR_FIELDS) + [f"page_{i}_dwell_ms" for i in range(1, 9)] + [f"{field}_{metric}" for field in TRACKED_FIELDS for metric in FIELD_METRICS]


def safe_cell(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value
    return value


def analysis_row(participant):
    submitted, summary = participant.submission, participant.behavior_summary
    form = submitted.payload if submitted else (participant.draft.payload if participant.draft else {})
    row = {key: form.get(key) for key in ANALYSIS_FIELDS}
    row.update({"participant_id": participant.public_id, "is_test": participant.is_test, "status": participant.status, "source": participant.source, "created_at": iso_utc(participant.created_at), "submitted_at": iso_utc(participant.submitted_at), "experiment_version": participant.experiment_version, "scale_version": submitted.scale_version if submitted else participant.scale_version, "behavior_metrics_version": participant.behavior_metrics_version, "form_version": submitted.form_version if submitted else form.get("form_layout"), "receipt_id": participant.receipt_id})
    for key in ("status", "received_batches", "received_events", "expected_batches", "expected_events", "dropped_events"):
        row["behavior_status" if key == "status" else key] = getattr(summary, key, None)
    metrics = summary.metrics or {} if summary else {}
    row["quality_flags"] = metrics.get("quality_flags", [])
    for key in ("device_type", "browser", "viewport_width", "viewport_height"):
        row[key] = (participant.client_context or {}).get(key)
    raw = {answer.item_number: answer.raw_score for answer in participant.scale_answers} if submitted else {}
    for i in range(1, 30):
        row[f"rs_q{i:02d}"] = raw.get(i) if submitted else (participant.draft.scale_payload or {}).get(f"rs_q{i:02d}") if participant.draft else None
    subscales = (submitted.scale_scores or {}).get("subscales", {}) if submitted else {}
    for key in ("ATR", "SN", "PBC", "LRI"):
        for metric in ("total", "mean", "valid_count"):
            row[f"{key}_{metric}"] = subscales.get(key, {}).get(metric)
    for key in BEHAVIOR_FIELDS:
        row[key] = metrics.get(key)
    for i in range(1, 9):
        row[f"page_{i}_dwell_ms"] = metrics.get("page_dwell_ms", {}).get(str(i))
    for field in TRACKED_FIELDS:
        for metric in FIELD_METRICS:
            row[f"{field}_{metric}"] = metrics.get("fields", {}).get(field, {}).get(metric)
    return row


def csv_text(participants, *, events=False):
    output = io.StringIO(newline="")
    output.write("\ufeff")
    if events:
        headers = ["participant_id", "is_test", "experiment_version", "batch_id", "batch_seq", "event_index", "type", "phase", "page", "field", "client_time_ms", "duration_ms", "visibility"]
        writer = csv.DictWriter(output, fieldnames=headers)
        writer.writeheader()
        for participant in participants:
            for batch in participant.behavior_batches:
                for index, event in enumerate(batch.events):
                    # Survey-phase process variables stay out of the application-X export.
                    if event.get("phase", "application") != "application":
                        continue
                    row = {"participant_id": participant.public_id, "is_test": participant.is_test, "experiment_version": participant.experiment_version, "batch_id": batch.batch_id, "batch_seq": batch.batch_seq, "event_index": index, **event}
                    writer.writerow({key: safe_cell(row.get(key)) for key in headers})
    else:
        writer = csv.DictWriter(output, fieldnames=HEADERS)
        writer.writeheader()
        for participant in participants:
            writer.writerow({key: safe_cell(value) for key, value in analysis_row(participant).items()})
    return output.getvalue()
