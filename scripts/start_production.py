"""Migrate the configured persistent database, then replace this process with Gunicorn."""
from __future__ import annotations
from pathlib import Path
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
os.environ["APP_ENV"] = "production"
subprocess.run([sys.executable, "-m", "flask", "--app", "app", "db", "upgrade"], check=True)
port = str(int(os.environ.get("PORT", "10000")))
os.execvp("gunicorn", ["gunicorn", "app:application", "--bind", "0.0.0.0:" + port,
    "--workers", "1", "--threads", "4", "--timeout", "120", "--graceful-timeout", "30",
    "--error-logfile", "-"])
