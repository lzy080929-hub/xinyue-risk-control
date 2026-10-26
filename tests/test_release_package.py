"""Check the shipped artifact, independent of the source checkout's migration files."""
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import zipfile

from scripts.package_release import build_release


def test_packaged_release_can_migrate_without_source_files(tmp_path):
    archive = build_release(tmp_path / 'release')
    checkout = tmp_path / 'unpacked'
    with zipfile.ZipFile(archive) as package:
        names = package.namelist()
        assert 'migrations/alembic.ini' in names
        assert '.env' not in names
        assert not any(name.startswith(('.tools/', 'instance/', 'verification_artifacts/')) for name in names)
        assert not any(Path(name).suffix in {'.db', '.sqlite3'} for name in names)
        package.extractall(checkout)
    environment = os.environ.copy()
    for key in ('SECRET_KEY', 'ADMIN_USERNAME', 'ADMIN_PASSWORD_HASH'):
        environment.pop(key, None)
    database = tmp_path / 'release-check.sqlite3'
    environment.update(APP_ENV='development', DATABASE_URL='sqlite:///' + database.as_posix(), FLASK_DEBUG='0')
    result = subprocess.run([sys.executable, '-m', 'flask', '--app', 'app', 'db', 'upgrade'],
        cwd=checkout, env=environment, capture_output=True, text=True, encoding='utf-8', timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
    with sqlite3.connect(database) as connection:
        assert connection.execute('SELECT version_num FROM alembic_version').fetchone()[0] == 'a83c6f2d901e'
