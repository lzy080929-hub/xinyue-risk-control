"""Public learning-platform pages.

The learning pages are intentionally client-only: quiz answers, reading
progress, and calculator inputs never leave the visitor's browser. The
research application is kept on its own route and protocol.
"""

from __future__ import annotations

from flask import (
    Blueprint,
    abort,
    current_app,
    redirect,
    render_template,
    request,
    url_for,
)

from config import (
    BEHAVIOR_METRICS_VERSION,
    CONSENT_VERSION,
    EXPERIMENT_VERSION,
    FORM_VERSION,
    SCALE_VERSION,
)
from platform_content import (
    ASSESSMENT_QUESTION_COUNT,
    ASSESSMENT_QUESTIONS,
    ASSESSMENT_TOPICS,
    ASSESSMENT_TOPIC_COUNTS,
    FEATURED_TOPIC_SLUGS,
    LEARNING_ASSESSMENT_VERSION,
    LEARNING_SOURCE_NOTE,
    LEARNING_TOPIC_BY_SLUG,
    LEARNING_TOPIC_COUNT,
    LEARNING_TOPICS,
    PLATFORM_VERSION,
)
from survey import LIKERT_LABELS, SURVEY_ITEMS

bp = Blueprint("platform", __name__)


@bp.get("/")
def home():
    """Show the learning portal, while preserving old research share links.

    The previous application lived at ``/``. Links carrying ``test=1`` or a
    recruitment ``source`` therefore continue to open the application rather
    than dropping an in-progress participant on the new portal.
    """
    if request.args.get("test") == "1" or request.args.get("source"):
        return redirect(
            url_for("platform.apply", **request.args.to_dict(flat=True)),
            code=302,
        )
    featured_topics = [LEARNING_TOPIC_BY_SLUG[slug] for slug in FEATURED_TOPIC_SLUGS]
    return render_template(
        "platform/home.html",
        active_page="home",
        featured_topics=featured_topics,
        topic_count=LEARNING_TOPIC_COUNT,
        question_count=ASSESSMENT_QUESTION_COUNT,
        platform_version=PLATFORM_VERSION,
        learning_assessment_version=LEARNING_ASSESSMENT_VERSION,
    )


@bp.get("/apply")
def apply():
    """Render the existing eight-page research application unchanged."""
    test_mode = bool(
        current_app.config.get("ALLOW_TEST_MODE")
        and request.args.get("test") == "1"
    )
    return render_template(
        "original_application.html",
        consent_version=CONSENT_VERSION,
        experiment_version=EXPERIMENT_VERSION,
        scale_version=SCALE_VERSION,
        behavior_metrics_version=BEHAVIOR_METRICS_VERSION,
        form_version=FORM_VERSION,
        ui_version=current_app.config["UI_VERSION"],
        test_mode=test_mode,
        survey_items=tuple(enumerate(SURVEY_ITEMS, start=1)),
        likert_labels=LIKERT_LABELS,
    )


@bp.get("/assessment")
def assessment():
    return render_template(
        "platform/assessment.html",
        active_page="assessment",
        topics=ASSESSMENT_TOPICS,
        topic_counts=ASSESSMENT_TOPIC_COUNTS,
        questions=ASSESSMENT_QUESTIONS,
        question_count=ASSESSMENT_QUESTION_COUNT,
        learning_assessment_version=LEARNING_ASSESSMENT_VERSION,
    )


@bp.get("/learn")
def learn():
    return render_template(
        "platform/learn.html",
        active_page="learn",
        topics=LEARNING_TOPICS,
        topic_count=LEARNING_TOPIC_COUNT,
        source_note=LEARNING_SOURCE_NOTE,
    )


@bp.get("/learn/<slug>")
def learn_topic(slug: str):
    topic = LEARNING_TOPIC_BY_SLUG.get(slug)
    if topic is None:
        abort(404)
    position = LEARNING_TOPICS.index(topic)
    previous_topic = LEARNING_TOPICS[position - 1] if position > 0 else None
    next_topic = (
        LEARNING_TOPICS[position + 1]
        if position + 1 < LEARNING_TOPIC_COUNT
        else None
    )
    return render_template(
        "platform/learn_topic.html",
        active_page="learn",
        topic=topic,
        previous_topic=previous_topic,
        next_topic=next_topic,
        source_note=LEARNING_SOURCE_NOTE,
    )


@bp.get("/tools")
def tools():
    return render_template(
        "platform/tools.html",
        active_page="tools",
    )


@bp.get("/my-learning")
def my_learning():
    return render_template(
        "platform/my_learning.html",
        active_page="my-learning",
        topics=LEARNING_TOPICS,
        platform_version=PLATFORM_VERSION,
        learning_assessment_version=LEARNING_ASSESSMENT_VERSION,
    )


@bp.get("/about")
def about():
    return render_template(
        "platform/about.html",
        active_page="about",
        platform_version=PLATFORM_VERSION,
        learning_assessment_version=LEARNING_ASSESSMENT_VERSION,
    )
