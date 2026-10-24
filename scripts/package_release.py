"""Package an allowlisted deployable release; never include runtime research data or secrets."""
from pathlib import Path
from datetime import datetime, timezone
import json
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = ["app.py", "admin_routes.py", "participant_routes.py", "behavior.py", "research_export.py",
    "config.py", "models.py", "extensions.py", "security.py", "validation.py", "survey.py", "errors.py",
    "requirements-web.txt", "requirements-render.txt", "requirements-dev.txt", "pytest.ini", "render.yaml", "Procfile", "runtime.txt",
    ".env.example", ".gitignore", "README.md", "DEPLOY_RENDER.md", "start_local.ps1"]
ASSETS = ["original.css", "original_application.js", "behavior_tracker.js", "admin_dashboard.js", "styles.css", "favicon.svg"]


def main():
    files = [ROOT / name for name in ROOT_FILES]
    files += [ROOT / "static" / name for name in ASSETS]
    files += list((ROOT / "templates").glob("*.html"))
    files += [p for p in (ROOT / "migrations").rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.suffix in {".py", ".mako"}]
    files += [ROOT / "scripts" / name for name in ["start_production.py", "backup_local.py", "hash_admin_password.py", "package_release.py"]]
    files += list((ROOT / "docs").glob("*.md"))
    files += list((ROOT / "tests").glob("*.py"))
    missing = [str(p.relative_to(ROOT)) for p in files if not p.is_file()]
    if missing:
        raise RuntimeError("Release incomplete: " + ", ".join(missing))
    folder = ROOT / "dist"
    folder.mkdir(exist_ok=True)
    output = folder / ("xinyue-render-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".zip")
    with zipfile.ZipFile(output, "x", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(set(files)):
            archive.write(path, path.relative_to(ROOT).as_posix())
        archive.writestr("release_manifest.json", json.dumps({"format": 1, "files": sorted(p.relative_to(ROOT).as_posix() for p in set(files)), "runtime_data_included": False}, ensure_ascii=False, indent=2))
    print(output)


if __name__ == "__main__":
    main()
