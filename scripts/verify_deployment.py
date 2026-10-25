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
    html = body.decode("utf-8", errors="replace")
    checks.append({"check": "eight_page_bank_interface", "passed": status == 200 and html.count('class="form-page" data-page=') == 8 and 'data-ui-version="bank-application-v1"' in html, "http_status": status})
    status, body = fetch("/static/bank-interface.css")
    expected = hashlib.sha256((ROOT / "static" / "bank-interface.css").read_bytes()).hexdigest()
    actual = hashlib.sha256(body).hexdigest() if status == 200 else None
    checks.append({"check": "matches_local_interface_asset", "passed": status == 200 and actual == expected, "http_status": status})
    status, _ = fetch("/admin/api/overview")
    checks.append({"check": "admin_api_requires_login", "passed": status == 401, "http_status": status})
    report = {"checked_at_utc": datetime.now(timezone.utc).isoformat(), "origin": base, "read_only": True,
        "checks": checks, "read_only_checks_passed": all(item["passed"] for item in checks),
        "not_verified": ["real mobile/WeChat access", "authenticated test submission and CSV", "persistent PostgreSQL configuration", "retention after restart and backup restoration"]}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["read_only_checks_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
