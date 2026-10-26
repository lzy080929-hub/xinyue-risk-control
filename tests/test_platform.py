from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from platform_content import (
    ASSESSMENT_QUESTION_COUNT,
    ASSESSMENT_QUESTIONS,
    ASSESSMENT_TOPICS,
    LEARNING_ASSESSMENT_VERSION,
    LEARNING_TOPIC_BY_SLUG,
    LEARNING_TOPIC_COUNT,
    LEARNING_TOPICS,
    PLATFORM_VERSION,
)

ROOT = Path(__file__).resolve().parents[1]


def test_platform_assessment_and_learning_content_are_well_formed():
    assert ASSESSMENT_QUESTION_COUNT == 16
    assert len(ASSESSMENT_TOPICS) == 4
    assert len(LEARNING_TOPICS) == LEARNING_TOPIC_COUNT == 12
    assert LEARNING_ASSESSMENT_VERSION == "literacy-learning-v1"
    assert PLATFORM_VERSION == "platform-v1"

    numbers = [question["number"] for question in ASSESSMENT_QUESTIONS]
    assert numbers == list(range(1, 17))
    assert len(set(numbers)) == 16

    for topic in ASSESSMENT_TOPICS:
        topic_questions = [q for q in ASSESSMENT_QUESTIONS if q["topic"] == topic["slug"]]
        assert len(topic_questions) == 4
        for question in topic_questions:
            assert len(question["options"]) == 4
            assert 0 <= question["correct_index"] < len(question["options"])
            assert question["explanation"]
            assert question["learn_slug"] in LEARNING_TOPIC_BY_SLUG

    slugs = [topic["slug"] for topic in LEARNING_TOPICS]
    assert len(slugs) == len(set(slugs)) == 12
    for topic in LEARNING_TOPICS:
        assert topic["scenario"] and topic["summary"]
        assert topic["concept"] and topic["example"] and topic["actions"]
        assert topic["sources"]


def test_portal_and_learning_pages_render_without_inline_code(client):
    paths = [
        "/",
        "/assessment",
        "/learn",
        "/learn/living-budget",
        "/tools",
        "/my-learning",
        "/about",
    ]
    for path in paths:
        response = client.get(path)
        assert response.status_code == 200, path
        html = response.get_data(as_text=True)
        assert "behavior_tracker.js" not in html
        assert "/api/" not in html
        assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html), path
        assert not re.search(r"\sstyle\s*=", html), path
        assert not re.search(r"\son(?:click|change|load|error|submit)\s*=", html), path
        assert 'class="platform-header"' in html
        assert 'class="platform-footer"' in html

    home = client.get("/").get_data(as_text=True)
    assert "学会管理生活费，看懂每一次借贷" in home
    assert home.count('class="module-card') == 3
    assert "金融素养测评" in home and "知识科普" in home and "信贷申请体验" in home
    assert 'href="/assessment"' in home
    assert 'href="/apply"' in home

    assessment = client.get("/assessment").get_data(as_text=True)
    assert assessment.count('class="quiz-question"') == 16
    assert assessment.count('value="unsure"') == 16
    assert assessment.count('class="answer-review" hidden') == 16
    assert assessment.count('class="assessment-section"') == 4
    assert 'id="assessment-result" class="result-panel" tabindex="-1" hidden' in assessment
    assert "<form" not in assessment

    learn = client.get("/learn").get_data(as_text=True)
    assert learn.count('class="learn-card"') == 12
    assert "阅读记录只保存在当前浏览器" in learn

    tools = client.get("/tools").get_data(as_text=True)
    assert 'id="loan-calculator"' in tools
    assert 'id="budget-tool"' in tools
    assert tools.count("data-scam>") == 4
    assert "<form" not in tools


def test_learning_pages_use_only_browser_local_scripts(client):
    script_names = ["platform.js", "assessment.js", "tools.js", "my_learning.js"]
    for name in script_names:
        text = (ROOT / "static" / name).read_text(encoding="utf-8")
        assert "fetch(" not in text, name
        assert "XMLHttpRequest" not in text, name
        assert "sendBeacon" not in text, name
        assert "/api/" not in text, name

    platform_js = (ROOT / "static" / "platform.js").read_text(encoding="utf-8")
    assert "xinyue.learning.v1" in platform_js
    assert "xinyue.original-eight-page.v3" in platform_js
    assert "never read, parse, or transmit the application draft" in platform_js

    for name in ["platform_content.py", "platform_routes.py"]:
        source = (ROOT / name).read_text(encoding="utf-8")
        assert "from models" not in source, name
        assert "from extensions import db" not in source, name
        assert "research_export" not in source, name


def test_old_application_and_recruitment_links_keep_working(client):
    response = client.get("/?test=1&source=class_a")
    assert response.status_code == 302
    location = urlparse(response.headers["Location"])
    assert location.path == "/apply"
    assert parse_qs(location.query) == {"test": ["1"], "source": ["class_a"]}

    response = client.get("/?source=class_a")
    assert response.status_code == 302
    location = urlparse(response.headers["Location"])
    assert location.path == "/apply"
    assert parse_qs(location.query) == {"source": ["class_a"]}

    response = client.get("/")
    assert response.status_code == 200
    assert 'class="hero"' in response.get_data(as_text=True)

    response = client.get("/apply?source=class_a")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'class="form-page" data-page="1"' in html
    assert html.count('class="form-page"') == 8
    assert 'src="/static/behavior_tracker.js"' in html


def test_every_learning_topic_has_a_public_article(client):
    for topic in LEARNING_TOPICS:
        response = client.get("/learn/" + topic["slug"])
        assert response.status_code == 200, topic["slug"]
        html = response.get_data(as_text=True)
        assert topic["title"] in html
        assert "校园情境" in html
        assert "资料依据" in html
        assert "不构成" in html

    assert client.get("/learn/not-a-real-topic").status_code == 404


def test_platform_security_headers_and_error_entry(client):
    response = client.get("/")
    assert response.headers["Content-Security-Policy"] == (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "img-src 'self' data:; connect-src 'self'; form-action 'self'; "
        "frame-ancestors 'none'; base-uri 'self'"
    )
    assert response.headers["X-Frame-Options"] == "DENY"

    missing = client.get("/definitely-not-a-page")
    assert missing.status_code == 404
    html = missing.get_data(as_text=True)
    assert 'href="/"' in html
    assert "返回平台首页" in html
