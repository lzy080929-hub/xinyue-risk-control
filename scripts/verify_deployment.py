"""Read-only public deployment checks. Does not create participants or send credentials."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="Public HTTPS origin, e.g. https://example.onrender.com")
    parser.add_argument("--timeout", type=int, default=10)
    args = parser.parse_args()
    parts = urlsplit(args.url)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment or parts.path not in {"", "/"}:
        parser.error("Use an HTTPS origin without a path, query, or credentials.")
    if not 1 <= args.timeout <= 30:
        parser.error("timeout must be 1 to 30 seconds")
    base = args.url.rstrip("/")
    checks = []
    def fetch(path):
        try:
            with urlopen(Request(base + path, headers={"User-Agent": "XinyueReadOnlyDeploymentCheck/1"}), timeout=args.timeout) as response:
                return response.status, response.read(2_000_000)
        except HTTPError as failure:
            return failure.code, failure.read(200_000)
        except (URLError, TimeoutError, OSError):
            return None, b""
    status, body = fetch("/health")
    try:
        health = json.loads(body)
    except (ValueError, UnicodeError):
        health = {}
    checks.append({"check": "database_health", "passed": status == 200 and health.get("database") == "ok", "http_status": status})

    status, body = fetch("/")
    home_html = body.decode("utf-8", errors="replace")
    portal_deployed = (
        status == 200
        and 'class="platform-body' in home_html
        and 'href="/assessment"' in home_html
        and "学会管理生活费" in home_html
    )
    checks.append({
        "check": "public_home_reachable",
        "passed": status == 200 and (portal_deployed or 'class="form-page" data-page=' in home_html),
        "http_status": status,
        "entry": "learning_portal" if portal_deployed else "legacy_application",
    })

    if portal_deployed:
        status_apply, body = fetch("/apply")
        application_status = status_apply
        application_html = body.decode("utf-8", errors="replace")
        application_path = "/apply"
        status_assessment, body_assessment = fetch("/assessment")
        assessment_html = body_assessment.decode("utf-8", errors="replace")
        checks.append({
            "check": "learning_assessment",
            "passed": status_assessment == 200
            and assessment_html.count('class="quiz-question"') == 16
            and assessment_html.count('value="unsure"') == 16,
            "http_status": status_assessment,
        })
        status_css, body_css = fetch("/static/platform.css")
        expected_css = hashlib.sha256((ROOT / "static" / "platform.css").read_bytes()).hexdigest()
        checks.append({
            "check": "matches_local_platform_asset",
            "passed": status_css == 200 and hashlib.sha256(body_css).hexdigest() == expected_css,
            "http_status": status_css,
        })
    else:
        application_status = status
        application_html = home_html
        application_path = "/"

    checks.append({
        "check": "eight_page_bank_interface",
        "passed": application_status == 200
        and application_html.count('class="form-page" data-page=') == 8
        and any('data-ui-version="' + version + '"' in application_html for version in ("bank-application-v1", "bank-application-v2")),
        "http_status": application_status,
        "path": application_path,
    })

    status, body = fetch("/static/bank-interface.css")
    expected = hashlib.sha256((ROOT / "static" / "bank-interface.css").read_bytes()).hexdigest()
    actual = hashlib.sha256(body).hexdigest() if status == 200 else None
    checks.append({"check": "matches_local_interface_asset", "passed": status == 200 and actual == expected, "http_status": status})
    status, _ = fetch("/admin/api/overview")
    checks.append({"check": "admin_api_requires_login", "passed": status == 401, "http_status": status})
    not_verified = [
        "real mobile/WeChat access",
        "authenticated test submission and CSV",
        "persistent PostgreSQL configuration",
        "retention after restart and backup restoration",
    ]
    if not portal_deployed:
        not_verified.append("learning platform deployment (public home is still the legacy application)")
    report = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "origin": base,
        "read_only": True,
        "portal_deployed": portal_deployed,
        "checks": checks,
        "read_only_checks_passed": all(item["passed"] for item in checks),
        "not_verified": not_verified,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["read_only_checks_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
