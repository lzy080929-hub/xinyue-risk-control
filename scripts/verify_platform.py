"""Real-browser verification for the public learning platform.

Uses an isolated SQLite database and a local server. It checks responsive
layout, browser-local learning records, calculator results, and that the
learning pages never call the research API.
"""

from __future__ import annotations

import json
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from flask_migrate import upgrade
from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import WSGIRequestHandler, make_server

from app import create_app
from extensions import db
from tests.conftest import make_test_config


class Quiet(WSGIRequestHandler):
    def log_request(self, *args):
        pass


def assert_no_horizontal_overflow(page, widths):
    original = page.viewport_size
    for width in widths:
        page.set_viewport_size({"width": width, "height": 900})
        overflow = page.evaluate(
            "document.documentElement.scrollWidth > document.documentElement.clientWidth"
        )
        assert not overflow, f"horizontal overflow at {width}px on {page.url}"
    if original:
        # Callers take screenshots after this check; keep their chosen viewport.
        page.set_viewport_size(original)


def main():
    artifacts = ROOT / "verification_artifacts"
    artifacts.mkdir(exist_ok=True)
    out = Path(tempfile.mkdtemp(prefix="platform-", dir=artifacts))
    config = make_test_config(out / "verification.sqlite3")
    application = create_app(config)
    with application.app_context():
        upgrade(directory=str(ROOT / "migrations"))

    server = make_server("127.0.0.1", 0, application, threaded=True, request_handler=Quiet)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    report = {
        "database_isolated": True,
        "production_data_modified": False,
        "output_directory": str(out),
    }
    page_errors = []
    console_errors = []
    requests = []

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chrome", headless=True)
            try:
                context = browser.new_context(
                    viewport={"width": 390, "height": 900},
                    is_mobile=True,
                    has_touch=True,
                    locale="zh-CN",
                )
                context.on("request", lambda request: requests.append(request.url))
                page = context.new_page()

                def watch(target):
                    target.on("pageerror", lambda error: page_errors.append(str(error)))
                    target.on(
                        "console",
                        lambda message: console_errors.append(message.text)
                        if message.type == "error"
                        else None,
                    )

                watch(page)
                page.goto(base + "/", wait_until="networkidle")
                expect(page.locator("h1")).to_contain_text("学会管理生活费")
                expect(page.locator(".module-card")).to_have_count(3)
                assert page.locator("form").count() == 0
                assert page.locator("script[src*='behavior_tracker']").count() == 0
                assert_no_horizontal_overflow(page, (320, 360, 390))
                page.screenshot(path=str(out / "01-home-mobile.png"), full_page=False)

                page.set_viewport_size({"width": 1440, "height": 1000})
                assert_no_horizontal_overflow(page, (1440,))
                assert page.viewport_size["width"] == 1440
                page.screenshot(path=str(out / "02-home-desktop.png"), full_page=False)
                page.screenshot(path=str(out / "02-home-desktop-full.png"), full_page=True)
                page.set_viewport_size({"width": 390, "height": 900})

                # The resume banner only checks for a key, and never parses it.
                page.evaluate(
                    "sessionStorage.setItem('xinyue.original-eight-page.v3', 'not-json')"
                )
                page.reload(wait_until="networkidle")
                expect(page.locator("[data-resume-banner]")).to_be_visible()
                assert page.evaluate(
                    "sessionStorage.getItem('xinyue.original-eight-page.v3')"
                ) == "not-json"
                page.evaluate("sessionStorage.removeItem('xinyue.original-eight-page.v3')")
                report["resume_banner_presence_only"] = True

                # Complete 10 correct, 4 wrong, 1 unsure, 1 blank.
                page.goto(base + "/assessment", wait_until="networkidle")
                for number in range(1, 11):
                    fieldset = page.locator(
                        f'.quiz-question[data-question="{number}"]'
                    )
                    correct = fieldset.get_attribute("data-correct")
                    fieldset.locator(f'input[value="{correct}"]').check(force=True)
                for number in range(11, 15):
                    fieldset = page.locator(
                        f'.quiz-question[data-question="{number}"]'
                    )
                    correct = fieldset.get_attribute("data-correct")
                    wrong = "1" if correct == "0" else "0"
                    fieldset.locator(f'input[value="{wrong}"]').check(force=True)
                page.locator(
                    '.quiz-question[data-question="15"] input[value="unsure"]'
                ).check(force=True)

                expect(page.locator("#assessment-count")).to_have_text(
                    "已选择 15 / 16 题"
                )
                assert page.locator("#assessment-progress").get_attribute("value") == "15"
                page.locator("#assessment-submit-button").click()
                expect(page.locator("#assessment-result")).to_be_visible()
                expect(page.locator("#result-score")).to_have_text("10")
                expect(page.locator("#result-rate")).to_have_text("62.5%")
                expect(page.locator("#result-completion")).to_contain_text("15 / 16")
                expect(page.locator("#result-completion")).to_contain_text("未作答 1 题")
                expect(page.locator(".answer-review:visible")).to_have_count(16)
                expect(page.locator(".result-topic-card")).to_have_count(4)
                expect(page.locator("#result-recommendations a")).to_have_count(2)
                expect(page.locator(".quiz-question.is-wrong")).to_have_count(4)
                expect(page.locator(".quiz-question.is-unsure")).to_have_count(1)
                expect(page.locator(".quiz-question.is-unanswered")).to_have_count(1)
                assert_no_horizontal_overflow(page, (320, 360, 390, 1440))
                # Element screenshots ignore the sticky header's scroll padding.
                # Hide it only for this documentation image so the score is visible.
                page.evaluate(
                    "document.querySelector('.platform-header').style.visibility = 'hidden'"
                )
                try:
                    page.locator("#assessment-result").screenshot(
                        path=str(out / "03-assessment-result-mobile.png")
                    )
                finally:
                    page.evaluate(
                        "document.querySelector('.platform-header').style.visibility = ''"
                    )

                state = page.evaluate(
                    "JSON.parse(localStorage.getItem('xinyue.learning.v1'))"
                )
                assert state["assessment"]["score"] == 10
                assert state["assessment"]["answered"] == 15
                assert state["assessment"]["total"] == 16
                assert len(state["assessment"]["topics"]) == 4
                assert len(state["assessment"]["recommendations"]) == 2
                assert "answers" not in state["assessment"]
                assert "q1" not in json.dumps(state, ensure_ascii=False)
                report["assessment_browser_local_only"] = True

                page.locator("#retry-assessment").click()
                expect(page.locator("#assessment-result")).to_be_hidden()
                expect(page.locator("#assessment-count")).to_have_text(
                    "已选择 0 / 16 题"
                )
                assert page.locator('.quiz-question input:checked').count() == 0
                assert page.locator('.quiz-question input[value="0"]').first.is_enabled()
                report["assessment_retry"] = True

                # Mark one article as read and verify progress on both pages.
                page.goto(base + "/learn/living-budget", wait_until="networkidle")
                expect(page.locator("[data-article-read-badge]")).to_be_hidden()
                page.locator("[data-mark-read]").click()
                expect(page.locator("[data-article-read-badge]")).to_be_visible()
                expect(page.locator("[data-mark-read]")).to_be_disabled()
                expect(page.locator("[data-read-status]")).to_contain_text(
                    "已保存到当前浏览器"
                )
                assert_no_horizontal_overflow(page, (320, 360, 390, 1440))
                page.screenshot(path=str(out / "04-article-mobile.png"), full_page=False)

                page.goto(base + "/learn", wait_until="networkidle")
                assert_no_horizontal_overflow(page, (320, 360, 390, 1440))
                assert page.locator("[data-learning-read-progress]").get_attribute(
                    "value"
                ) == "1"
                expect(page.locator(".read-badge:visible")).to_have_count(1)
                report["reading_progress_local"] = True

                # Calculators use the real rendered controls.
                page.goto(base + "/tools", wait_until="networkidle")
                page.locator("#loan-calculate").click()
                expect(page.locator("#loan-monthly")).to_have_text("860.66 元")
                expect(page.locator("#loan-total")).to_have_text("10,327.97 元")
                expect(page.locator("#loan-interest")).to_have_text("327.97 元")
                expect(page.locator("#loan-effective")).to_have_text("6.17%")

                page.locator("#budget-calculate").click()
                expect(page.locator("#budget-remaining")).to_have_text("300.00 元")
                expect(page.locator("#budget-summary")).to_contain_text("每天 10.00 元")
                assert page.locator("#budget-essential-bar").get_attribute("value") == "60"
                assert page.locator("#budget-open-bar").get_attribute("value") == "10"

                page.fill("#budget-essential", "")
                page.locator("#budget-calculate").click()
                expect(page.locator("#budget-error")).to_be_visible()
                page.fill("#budget-essential", "1800")
                page.locator("#budget-calculate").click()
                expect(page.locator("#budget-error")).to_be_hidden()

                first_scam = page.locator("[data-scam]").first
                first_scam.locator('.scam-option[data-correct="true"]').click()
                expect(first_scam.locator(".feedback-good")).to_be_visible()
                expect(first_scam.locator(".scam-option[disabled]")).to_have_count(3)
                assert_no_horizontal_overflow(page, (320, 360, 390, 1440))
                page.evaluate("window.scrollTo({top: 0, behavior: 'instant'})")
                page.screenshot(path=str(out / "05-tools-mobile.png"), full_page=True)

                tools_state = page.evaluate(
                    "JSON.parse(localStorage.getItem('xinyue.learning.v1')).tools"
                )
                assert set(tools_state) == {"loan", "budget", "anti-fraud"}
                report["tools_calculate_and_local_marker"] = True

                # My learning reads only the local summary.
                page.goto(base + "/my-learning", wait_until="networkidle")
                expect(page.locator("#my-assessment-rate")).to_have_text("62.5")
                expect(page.locator("#my-assessment-score")).to_have_text("10")
                expect(page.locator("#my-assessment-answered")).to_have_text("15")
                expect(page.locator("#my-assessment-topics .record-topic")).to_have_count(4)
                expect(page.locator("#my-assessment-recommendation")).to_contain_text(
                    "建议复习"
                )
                expect(page.locator("[data-tool-status].is-used")).to_have_count(3)
                assert page.locator("[data-learning-read-progress]").get_attribute(
                    "value"
                ) == "1"
                assert_no_horizontal_overflow(page, (320, 360, 390, 1440))
                page.screenshot(path=str(out / "06-my-learning-mobile.png"), full_page=True)

                # Clear only browser-local learning data.
                page.once("dialog", lambda dialog: dialog.accept())
                page.locator("#clear-learning-data").click()
                expect(page.locator("#assessment-record-empty")).to_be_visible()
                expect(page.locator("#assessment-record")).to_be_hidden()
                expect(page.locator("[data-tool-status].is-used")).to_have_count(0)
                assert page.evaluate("localStorage.getItem('xinyue.learning.v1')") is None
                expect(page.locator("#clear-learning-status")).to_contain_text("已清除")
                report["local_clear"] = True

                # Existing recruitment/test link still reaches the eight-page application.
                application_page = context.new_page()
                watch(application_page)
                application_page.goto(
                    base + "/?test=1&source=platform_browser_check",
                    wait_until="networkidle",
                )
                assert "/apply?" in application_page.url
                assert "source=platform_browser_check" in application_page.url
                expect(application_page.locator(".form-page")).to_have_count(8)
                assert (
                    application_page.locator("#loan-application-form").get_attribute(
                        "data-ui-version"
                    )
                    == "bank-application-v1"
                )
                assert application_page.locator(".scale-question").count() == 29
                assert application_page.evaluate(
                    "document.documentElement.scrollWidth <= innerWidth"
                )
                application_page.close()
                report["application_redirect_regression"] = True

                assert not page_errors, page_errors
                research_requests = [
                    url
                    for url in requests
                    if "/api/" in url or "/collect" in url or "/behavior-batches" in url
                ]
                assert not research_requests, research_requests
                assert not console_errors, console_errors
                report["javascript_errors"] = page_errors
                report["console_errors"] = console_errors
                report["learning_pages_research_api_requests"] = research_requests
                report["passed"] = True
            finally:
                browser.close()
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
        with application.app_context():
            db.session.remove()
            db.engine.dispose()

    (out / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
