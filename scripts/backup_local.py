"""Create a consistent, separate backup of a local SQLite database."""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import argparse
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path)
    parser.add_argument("--output-directory", type=Path, default=ROOT / "instance/backups")
    args = parser.parse_args()
    if args.database is None:
        from config import build_runtime_config
        from sqlalchemy.engine import make_url
        url = make_url(build_runtime_config(str(ROOT / "instance"))["SQLALCHEMY_DATABASE_URI"])
        if url.get_backend_name() != "sqlite":
            raise RuntimeError("The configured database is not local SQLite. Back it up with its provider before migration.")
        source = Path(url.database)
        if not source.is_absolute():
            source = ROOT / "instance" / source
        source = source.resolve()
    else:
        source = args.database.resolve()
    if not source.is_file():
        print("No existing local database; nothing to back up.")
        return
    folder = args.output_directory.resolve()
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / (source.stem + "-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".sqlite3")
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as reader:
        with sqlite3.connect(target) as writer:
            reader.backup(writer)
            if writer.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("Backup integrity check failed")
    print("Backup saved:", target)


if __name__ == "__main__":
    main()
