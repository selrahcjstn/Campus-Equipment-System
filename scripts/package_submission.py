"""Build a source-only course submission ZIP; local data and credentials are excluded."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_PARTS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".local", "dist", "tmp", "media", "staticfiles", ".vscode", "node_modules"}
SOURCE_DIRS = {"apps", "config", "templates", "static", "docs", "scripts", "tests"}


def allowed(name):
    path = PurePosixPath(name)
    return (
        not path.is_absolute() and ".." not in path.parts
        and not EXCLUDED_PARTS.intersection(path.parts)
        and not (path.name.startswith(".env") and path.name != ".env.example")
        and path.suffix.lower() not in {".sqlite3", ".sqlite", ".db", ".pyc", ".pyo", ".log", ".zip"}
        and not path.name.lower().endswith((".sqlite3-wal", ".sqlite3-shm", ".sqlite3-journal", ".db-journal"))
        # This earlier export predates source-document corrections. Package the
        # current Markdown sources instead of presenting that PDF as current.
        and path.name != "Campus_Equipment_Borrowing_System_Documentation.pdf"
        and (path.parts[0] in SOURCE_DIRS or (len(path.parts) == 1 and (path.suffix == ".md" or path.name in {"manage.py", "requirements.txt", ".gitignore", ".env.example"})))
    )


def build(section, group, output_dir):
    for value in (section, group):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,39}", value):
            raise ValueError("Section and group must contain only letters, digits, underscores or hyphens.")
    raw = subprocess.check_output(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=ROOT)
    names = sorted({name for name in raw.decode("utf-8").split("\0") if name and allowed(name)})
    if not {"manage.py", "requirements.txt", ".env.example", "DEMO_SETUP.md"}.issubset(names):
        raise ValueError("Required setup files are missing from the source list.")
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"IT401W_ProjectA_{section}_{group}.zip"
    files = {}
    for name in names:
        source = ROOT / name
        if source.is_symlink() or not source.resolve().is_relative_to(ROOT.resolve()) or not source.is_file():
            raise ValueError(f"Unsafe or missing package file: {name}")
        files[name] = source.read_bytes()
    # Detect accidental copies of local runtime secrets in source/documents.
    secret_values = []
    for config in [ROOT / ".env", ROOT / ".env.demo"]:
        if config.exists():
            for line in config.read_text(encoding="utf-8-sig").splitlines():
                key, sep, value = line.partition("=")
                if sep and key.strip() in {"DJANGO_SECRET_KEY", "CAMPUS_DEMO_PASSWORD"}:
                    value = value.strip().strip("\"'")
                    if len(value) >= 12:
                        secret_values.append(value.encode())
    if any(secret in data for data in files.values() for secret in secret_values):
        raise ValueError("A local private credential was found in package content. No archive was written.")
    manifest = {"created_at": datetime.now(timezone.utc).isoformat(), "section": section, "group": group,
                "contains_database_or_credentials": False,
                "files": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}}
    with ZipFile(target, "w", compression=ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(f"campus-equipment-system/{name}", data)
        archive.writestr("campus-equipment-system/SUBMISSION_MANIFEST.json", json.dumps(manifest, indent=2))
    with ZipFile(target) as archive:
        if archive.testzip() or any(not allowed(name.removeprefix("campus-equipment-system/")) for name in archive.namelist() if not name.endswith("SUBMISSION_MANIFEST.json")):
            raise ValueError("Archive integrity or exclusion verification failed.")
    print(f"Created and verified {target.name}: {len(files)} source/documentation files; no local DB, .env, Git history, caches or virtual environment.")
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--section", required=True)
    parser.add_argument("--group", required=True)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    options = parser.parse_args()
    build(options.section, options.group, options.output_dir)
