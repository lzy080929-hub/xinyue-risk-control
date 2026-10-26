from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import Flask, jsonify, render_template, request
from sqlalchemy import event, text
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.middleware.proxy_fix import ProxyFix

import admin_routes
import participant_routes
import platform_routes
import rrt_routes
from config import build_runtime_config
from errors import ApiError
from extensions import db, migrate
from security import LoginRateLimiter, api_error_response
from models import ParticipantSession, RrtInvitation, RrtResponse


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def _format_cn_time(value: datetime | None) -> str:
    if value is None:
        return "—"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S")


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(build_runtime_config(app.instance_path))
    if test_config:
        app.config.update(test_config)

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    db.init_app(app)
    # Batch mode keeps future SQLite development migrations practical.
    migrate.init_app(app, db, render_as_batch=True)
    app.extensions["login_limiter"] = LoginRateLimiter()
    app.jinja_env.filters["cn_time"] = _format_cn_time

    if app.config.get("IS_PRODUCTION"):
        # Render and similar platforms terminate TLS at one reverse proxy.
        app.wsgi_app = ProxyFix(  # type: ignore[method-assign]
            app.wsgi_app, x_for=1, x_proto=1, x_host=0, x_port=0, x_prefix=0
        )

    app.register_blueprint(participant_routes.bp)
    app.register_blueprint(platform_routes.bp)
    app.register_blueprint(rrt_routes.bp)
    app.register_blueprint(admin_routes.bp)

    @app.get("/favicon.ico")
    def favicon():
        return "", 204

    @app.get("/health")
    def health():
        try:
            db.session.execute(text("SELECT 1"))
            db.session.execute(select(ParticipantSession.id, ParticipantSession.client_context, ParticipantSession.terms_snapshot).limit(1))
            db.session.execute(select(RrtInvitation.id, RrtInvitation.redeemed).limit(1))
            db.session.execute(select(RrtResponse.id, RrtResponse.choice).limit(1))
        except SQLAlchemyError:
            app.logger.error("Database readiness check failed")
            return jsonify({"status": "degraded", "database": "unavailable"}), 503
        return jsonify({"status": "ok", "database": "ok"})

    @app.post("/collect")
    def legacy_collect():
        return (
            jsonify(
                {
                    "ok": False,
                    "error": {
                        "code": "legacy_endpoint_disabled",
                        "message": "旧版提交接口已停用，请刷新页面后重新参与。",
                    },
                }
            ),
            410,
        )

    @app.after_request
    def security_headers(response):
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; form-action 'self'; "
            "frame-ancestors 'none'; base-uri 'self'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=()"
        )
        if app.config.get("IS_PRODUCTION"):
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )
        if response.mimetype in {"text/html", "application/json"}:
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(ApiError)
    def handle_api_error(error: ApiError):
        return api_error_response(error)

    @app.errorhandler(413)
    def payload_too_large(_error):
        if request.path.startswith("/api/"):
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": {
                            "code": "payload_too_large",
                            "message": "提交内容超过大小限制，请精简后重试。",
                        },
                    }
                ),
                413,
            )
        return render_template("error.html", status=413, message="请求内容过大。"), 413

    @app.errorhandler(404)
    def not_found(_error):
        if request.path.startswith("/api/"):
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": {
                            "code": "not_found",
                            "message": "接口不存在。",
                        },
                    }
                ),
                404,
            )
        return render_template("error.html", status=404, message="页面不存在。"), 404

    @app.errorhandler(405)
    def method_not_allowed(_error):
        if request.path.startswith("/api/"):
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": {
                            "code": "method_not_allowed",
                            "message": "请求方法不允许。",
                        },
                    }
                ),
                405,
            )
        return render_template("error.html", status=405, message="请求方式不支持。"), 405

    @app.errorhandler(SQLAlchemyError)
    def handle_database_error(_error):
        db.session.rollback()
        app.logger.error("Unhandled database error")
        if request.path.startswith("/api/"):
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": {
                            "code": "storage_unavailable",
                            "message": "服务器暂时无法访问数据库，请稍后重试。",
                        },
                    }
                ),
                503,
            )
        return render_template("error.html", status=503, message="数据库暂时不可用。"), 503

    return app


application = create_app()
app = application


if __name__ == "__main__":
    import os

    host = os.environ.get("FLASK_HOST", "127.0.0.1")
    port = int(os.environ.get("FLASK_PORT", "5000"))
    # Never enable the debugger implicitly, including from a stale FLASK_DEBUG.
    debug = os.environ.get("FLASK_DEBUG", "").lower() in ("1", "true", "yes")
    if application.config.get("IS_PRODUCTION") and debug:
        raise RuntimeError("正式环境禁止开启 Flask debug。")
    application.run(host=host, port=port, debug=debug)
