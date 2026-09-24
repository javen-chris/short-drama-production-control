"""Index every run in a project, so 20 segments are readable as one picture.

Storage model:

    <项目根>/workflow/
      ├─ run_index.json              one index per project (this module)
      └─ runs/
         ├─ RUN-EP02-U01.json        one file per segment, append-only
         ├─ RUN-EP02-U02.json
         └─ ...

One segment = one run = one file. The index is the map: it knows every run,
which one is active, and enough per-run state to render an overview without
opening 20 files.

Nothing here is a cache. The index is state, written by the orchestrator; reports
are rendered from it on demand and are always safe to re-render.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

INDEX_NAME = "run_index.json"
SEGMENTS_NAME = "segments.json"
PROJECT_STATE_NAME = "project_state.json"
RUNS_DIRNAME = "runs"


def segments_path(project_root: str | Path) -> Path:
    return Path(project_root) / "workflow" / SEGMENTS_NAME


def load_segments(project_root: str | Path) -> dict:
    """The user-owned segment list: what segments exist and what they are called.

    This is the authoritative source for segment names. The user maintains it (in
    the live page or by hand) and the agent reads it, so a segment is never named
    one thing in the report and another in the trace.
    """
    path = segments_path(project_root)
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"project": Path(project_root).name, "series": "", "episode": "", "segments": []}


def normalize_segments(document: dict) -> dict:
    """Reject a segment list that would make the project inconsistent."""
    if not isinstance(document, dict):
        raise ValueError("segment list must be an object")
    segments = document.get("segments")
    if not isinstance(segments, list):
        raise ValueError("segments must be a list")
    cleaned = []
    seen: set[str] = set()
    for index, item in enumerate(segments):
        if not isinstance(item, dict):
            raise ValueError(f"segment {index} must be an object")
        code = str(item.get("segment", "")).strip()
        if not code:
            raise ValueError(f"segment {index} needs a code")
        if code in seen:
            raise ValueError(f"duplicate segment code: {code}")
        seen.add(code)
        row = {"segment": code, "title": str(item.get("title", "")).strip(), "note": str(item.get("note", "")).strip()}
        if item.get("planned_seconds"):
            row["planned_seconds"] = int(item["planned_seconds"])
        cleaned.append(row)
    return {
        "project": str(document.get("project", "")).strip(),
        "series": str(document.get("series", "")).strip(),
        "episode": str(document.get("episode", "")).strip(),
        "updated_at": _now(),
        "segments": cleaned,
    }


def save_segments(project_root: str | Path, document: dict) -> Path:
    path = segments_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(normalize_segments(document), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def segment_run_id(document: dict, code: str) -> str:
    episode = document.get("episode") or document.get("project") or "SEG"
    return f"RUN-{episode}-{code}"


def apply_segments(index: dict, document: dict) -> dict:
    """Merge the user's segment list into the index.

    Segments that exist in the list but have no run yet appear as not-started rows,
    so filling in 20 segments immediately shows 20 named rows. Existing runs keep
    their state and only take the name from the list (the user's list wins on
    naming, the trace wins on status).
    """
    rows = {row.get("run_id"): row for row in index.get("runs", [])}
    by_segment = {row.get("segment"): row for row in index.get("runs", [])}
    for item in document.get("segments", []):
        code = item.get("segment", "")
        existing = by_segment.get(code)
        if existing:
            if item.get("title"):
                existing["segment_title"] = item["title"]
            continue
        run_id = segment_run_id(document, code)
        if run_id in rows:
            continue
        rows[run_id] = {
            "run_id": run_id,
            "segment": code,
            "segment_title": item.get("title", ""),
            "status": "",
            "current_step": "",
            "pending_decision": "",
            "progress": {"completed": 0, "total": 0},
            "path": f"{RUNS_DIRNAME}/{run_id}.json",
            "last_event_at": "",
            "updated_at": _now(),
        }
    index["runs"] = sorted(rows.values(), key=lambda r: r.get("run_id", ""))
    for key in ("project", "series", "episode"):
        if document.get(key) and not index.get(key):
            index[key] = document[key]
    return index


def segment_title_for(project_root: str | Path, segment: str) -> str:
    """What the user called this segment, so the agent can adopt the same name."""
    document = load_segments(project_root)
    for item in document.get("segments", []):
        if item.get("segment") == segment:
            return item.get("title", "")
    return ""


def project_state_path(project_root: str | Path) -> Path:
    return Path(project_root) / "workflow" / PROJECT_STATE_NAME


def load_project_state(project_root: str | Path) -> dict:
    """The agent's own status file, if it wrote one.

    Windows that drive production often keep their own `workflow/project_state.json`
    (stage, blockers, per-segment status). The board used to ignore it entirely, so
    a project could be visibly moving while the table still showed zero progress.
    Reading it is read-only and optional: a missing or broken file is just `{}`.
    """
    path = project_state_path(project_root)
    if not path.is_file():
        return {}
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return document if isinstance(document, dict) else {}


def project_state_mtime(project_root: str | Path) -> float:
    """When the producing window last touched its status file.

    ISO timestamps inside that file are often date-only ("2026-09-24"), which
    reads as midnight and makes a busy project look hours stale. The file's own
    mtime is what actually tells you it is still alive.
    """
    path = project_state_path(project_root)
    return path.stat().st_mtime if path.is_file() else 0.0


def index_path(project_root: str | Path) -> Path:
    return Path(project_root) / "workflow" / INDEX_NAME


def runs_dir(project_root: str | Path) -> Path:
    return Path(project_root) / "workflow" / RUNS_DIRNAME


def run_path(project_root: str | Path, run_id: str) -> Path:
    return runs_dir(project_root) / f"{run_id}.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_index(project_root: str | Path, *, project: str = "", series: str = "", episode: str = "") -> dict:
    """Load the index, creating an empty one if the project has no runs yet."""
    path = index_path(project_root)
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return {
        "project": project or Path(project_root).name,
        "series": series,
        "episode": episode,
        "active_run_id": "",
        "updated_at": _now(),
        "runs": [],
    }


def save_index(project_root: str | Path, index: dict) -> Path:
    path = index_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    index["updated_at"] = _now()
    path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def run_summary(run_id: str, state: dict, *, path: str = "") -> dict:
    """The per-run row stored in the index. Kept small on purpose."""
    steps = state.get("pipeline") or []
    completed = set(state.get("completed_steps", []) or [])
    return {
        "run_id": run_id,
        "segment": state.get("segment", ""),
        "segment_title": state.get("segment_title", ""),
        "status": state.get("status", ""),
        "current_step": state.get("current_step", ""),
        "pending_decision": state.get("pending_decision", ""),
        "progress": {"completed": len(completed & set(steps)), "total": len(steps)},
        "path": path or f"{RUNS_DIRNAME}/{run_id}.json",
        "last_event_at": (state.get("events") or [{}])[-1].get("at", ""),
        "updated_at": _now(),
    }


def register_run(index: dict, state: dict, *, path: str = "", make_active: bool = True) -> dict:
    """Add or refresh one run in the index; optionally mark it the active one."""
    run_id = state.get("run_id")
    if not run_id:
        raise ValueError("run state has no run_id")
    row = run_summary(run_id, state, path=path)
    rows = [r for r in index.get("runs", []) if r.get("run_id") != run_id]
    rows.append(row)
    rows.sort(key=lambda r: r.get("run_id", ""))
    index["runs"] = rows
    if make_active:
        index["active_run_id"] = run_id
    return index


def set_active(index: dict, run_id: str) -> dict:
    """Point the index at the segment currently being produced."""
    if run_id not in {r.get("run_id") for r in index.get("runs", [])}:
        raise ValueError(f"unknown run_id: {run_id}")
    index["active_run_id"] = run_id
    return index


def discover_runs(project_root: str | Path) -> list[dict]:
    """Rows for run files on disk that the index has not recorded yet.

    Segment files can be written by different windows; the index should not be
    the only thing that knows a run exists.
    """
    folder = runs_dir(project_root)
    if not folder.is_dir():
        return []
    rows = []
    for file in sorted(folder.glob("*.json")):
        try:
            state = json.loads(file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if state.get("run_id"):
            rows.append(run_summary(state["run_id"], state, path=f"{RUNS_DIRNAME}/{file.name}"))
    return rows


def sync_index(project_root: str | Path, index: dict) -> dict:
    """Merge on-disk runs into the index, keeping the newest status per run."""
    known = {r.get("run_id"): r for r in index.get("runs", [])}
    for row in discover_runs(project_root):
        previous = known.get(row["run_id"])
        if previous is None or (row.get("last_event_at", "") >= previous.get("last_event_at", "")):
            known[row["run_id"]] = row
    index["runs"] = sorted(known.values(), key=lambda r: r.get("run_id", ""))
    if not index.get("active_run_id") and index["runs"]:
        unfinished = [r for r in index["runs"] if r.get("status") not in {"COMPLETED"}]
        index["active_run_id"] = (unfinished or index["runs"])[-1]["run_id"]
    return index


def has_trace(project_root: str | Path) -> bool:
    """Is this folder a board project at all?

    A project is recognised by its index **or** its segment list. Requiring the
    index alone made the launcher reject a project that had only filled in its
    segment list - and the list can only be filled in on the page, which the
    launcher refused to open. That loop is the point of this check.
    """
    root = Path(project_root)
    return index_path(root).is_file() or segments_path(root).is_file()


def project_index(project_root: str | Path, *, project: str = "", series: str = "",
                  episode: str = "") -> dict:
    """The one way to read a project: on-disk runs + the user's segment list.

    Every consumer must go through here. Calling `load_index`/`sync_index` alone
    is what produced three different segment counts in three places (menu, static
    export, live page), because `apply_segments` was only ever called by the live
    page. Returns a merged index; callers may render it but must not assume it was
    persisted (the not-started rows are derived, never written).
    """
    index = load_index(project_root, project=project, series=series, episode=episode)
    index = sync_index(project_root, index)
    document = load_segments(project_root)
    if document.get("segments"):
        index = apply_segments(index, document)
    return index
