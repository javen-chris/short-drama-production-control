from __future__ import annotations

import re
from pathlib import Path

SECRET = re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*['\"][^'\"]+['\"]")
MEDIA = {".mp4", ".mov", ".mkv", ".wav", ".mp3", ".png", ".jpg", ".jpeg", ".webp"}
TEXT = {".py", ".json", ".yml", ".yaml", ".md", ".toml", ".txt", ".html", ".js", ".ts"}

# Public docs may use the explicit D:\\path\\to placeholder, but must not publish
# an absolute developer path. Test code may construct synthetic paths as fixtures.
WINDOWS_PATH = re.compile(r"(?i)\b[A-Z]:[\\/](?!path[\\/]to(?:[\\/]|\b))[^\\/\s\"'<>]+(?:[\\/][^\\/\s\"'<>]+)*")
RUN_ID = re.compile(r"(?i)\bRUN-EP\d{2}-A\d+(?:-[A-Z0-9]+)?\b")
PROVIDER_TASK_ID = re.compile(r"(?i)\btask-\d{10,}\b")
WORKFLOW_RECORD_DIRS = {
    "runs", "qa", "qa_reports", "authorization", "authorizations",
    "budget", "budgets", "submission_receipts", "asset_snapshots",
}


def _is_synthetic_fixture(relative: str) -> bool:
    """The checked-in examples/tests are synthetic fixtures, not live RUN evidence."""
    return relative.split("/", 1)[0].lower() in {"examples", "tests"}


def _is_workflow_record_path(relative: str) -> bool:
    parts = [part.lower() for part in Path(relative).parts]
    return any(
        parts[index] == "workflow" and parts[index + 1] in WORKFLOW_RECORD_DIRS
        for index in range(len(parts) - 1)
    )


def scan(root: str | Path) -> list[str]:
    """Report media, secrets, machine paths, live RUN IDs, and production records.

    ``examples/`` and ``tests/`` may contain explicitly synthetic RUN fixtures.
    Media and secrets are forbidden everywhere. Test code may construct synthetic
    Windows paths; production-shaped paths and identifiers are checked outside tests.
    """
    root = Path(root)
    errors: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or ".git" in path.parts:
            continue
        relative = path.relative_to(root).as_posix()
        if path.suffix.lower() in MEDIA:
            errors.append(f"media file tracked: {relative}")
        if _is_workflow_record_path(relative) and not _is_synthetic_fixture(relative):
            errors.append(f"production workflow data path: {relative}")
        if path.suffix.lower() not in TEXT:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if not relative.startswith("tests/") and WINDOWS_PATH.search(content):
            errors.append(f"machine-specific Windows path: {relative}")
        if SECRET.search(content):
            errors.append(f"possible secret: {relative}")
        if not _is_synthetic_fixture(relative):
            if RUN_ID.search(content):
                errors.append(f"production RUN identifier: {relative}")
            if PROVIDER_TASK_ID.search(content):
                errors.append(f"provider task identifier: {relative}")
    return errors
