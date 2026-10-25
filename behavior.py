"""Derive documented aggregate features from content-free incremental events."""
from __future__ import annotations


def summarize_events(events: list[dict], context: dict | None = None) -> dict:
    result = {
        "application_visible_ms": 0, "survey_visible_ms": 0,
        "hidden_duration_ms": 0, "total_elapsed_ms": 0,
        "back_navigation_count": 0, "non_sequential_fill_count": 0,
        "related_field_switch_count": 0, "resume_count": 0,
        "submit_attempt_count": 0, "page_dwell_ms": {}, "fields": {},
        "quality_flags": [],
    }
    for event in events:
        kind = event["type"]
        phase = event.get("phase", "application")
        duration = event.get("duration_ms", 0)
        result["total_elapsed_ms"] = max(result["total_elapsed_ms"], event.get("client_time_ms", 0))
        if kind == "page_duration":
            page = str(event.get("page", 0))
            result["page_dwell_ms"][page] = result["page_dwell_ms"].get(page, 0) + duration
            result["survey_visible_ms" if phase == "survey" else "application_visible_ms"] += duration
        elif kind == "hidden_duration":
            result["hidden_duration_ms"] += duration
        elif kind == "session_resume":
            result["resume_count"] += 1
        elif kind == "interface_change":
            if "interface_changed_during_session" not in result["quality_flags"]:
                result["quality_flags"].append("interface_changed_during_session")
        elif kind == "submit_attempt":
            result["submit_attempt_count"] += 1
        if phase != "application":
            continue
        for event_type, feature in (("page_back", "back_navigation_count"), ("non_sequential", "non_sequential_fill_count"), ("field_switch", "related_field_switch_count")):
            if kind == event_type:
                result[feature] += 1
        field = event.get("field")
        if not field:
            continue
        metrics = result["fields"].setdefault(field, {
            "focus_ms": 0, "focus_count": 0, "input_count": 0, "delete_count": 0,
            "delete_after_input_count": 0, "paste_count": 0, "revisit_count": 0,
            "return_edit_count": 0, "first_input_latency_ms": None,
        })
        counts = {"field_focus": "focus_count", "input_event": "input_count", "delete_event": "delete_count", "delete_after_input": "delete_after_input_count", "paste_event": "paste_count", "field_revisit": "revisit_count", "field_edit_return": "return_edit_count"}
        if kind in counts:
            metrics[counts[kind]] += 1
        elif kind == "field_duration":
            metrics["focus_ms"] += duration
        elif kind == "field_first_input" and metrics["first_input_latency_ms"] is None:
            metrics["first_input_latency_ms"] = duration
    if result["resume_count"]:
        result["quality_flags"].append("page_resumed")
    if (context or {}).get("input_type_supported") is False:
        result["quality_flags"].append("input_type_unsupported")
        for metrics in result["fields"].values():
            metrics["delete_count"] = None
            metrics["delete_after_input_count"] = None
    return result
