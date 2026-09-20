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
RUNS_DIRNAME = "runs"


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
