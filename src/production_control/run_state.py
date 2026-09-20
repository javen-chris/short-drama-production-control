"""Append-only run state with checkpoints, so a paused pipeline can resume."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .task_state import read_task, write_task

WAITING = "WAITING_APPROVAL"
PAUSED = "PAUSED_EXCEPTION"


def start_run(path: str | Path, run_id: str, contract_id: str, first_step: str) -> dict:
    state = {
        "run_id": run_id,
        "contract_id": contract_id,
        "current_step": first_step,
        "status": "RUNNING",
        "checkpoint": first_step,
        "completed_steps": [],
        "events": [],
    }
    write_task(path, state)
    return read_task(path)


def record_event(state: dict, step: str, outcome: str, reason: str = "", evidence: str = "") -> dict:
    """Append one event and keep completed steps in order."""
    event = {"step": step, "outcome": outcome, "at": datetime.now(timezone.utc).isoformat()}
    if reason:
        event["reason"] = reason
    if evidence:
        event["evidence"] = evidence
    state.setdefault("events", []).append(event)
    if outcome == "COMPLETED" and step not in state.get("completed_steps", []):
        state.setdefault("completed_steps", []).append(step)
    return event


def wait_for_approval(state: dict, step: str, decision: str) -> dict:
    """Pause on a human approval breakpoint."""
    state["status"] = WAITING
    state["current_step"] = step
    state["pending_decision"] = decision
    state["checkpoint"] = step
    return record_event(state, step, WAITING, decision)


def pause_for_exception(state: dict, step: str, reason: str, evidence: str = "") -> dict:
    state["status"] = PAUSED
    state["current_step"] = step
    state["pending_decision"] = reason
    state["checkpoint"] = step
    return record_event(state, step, PAUSED, reason, evidence)


def block(state: dict, step: str, reason: str) -> dict:
    state["status"] = "BLOCKED"
    state["current_step"] = step
    state["pending_decision"] = reason
    return record_event(state, step, "BLOCKED", reason)


def complete(state: dict, step: str) -> dict:
    event = record_event(state, step, "COMPLETED")
    pending = [name for name in state.get("pipeline", []) if name not in state["completed_steps"]]
    if not pending:
        state["status"] = "COMPLETED"
        state.pop("pending_decision", None)
    return event


def resume_point(state: dict) -> str:
    """A run may only continue from its last checkpoint, never by replaying paid work."""
    if state.get("status") in {"WAITING_APPROVAL", "PAUSED_EXCEPTION", "BLOCKED"}:
        return state.get("checkpoint", state.get("current_step", ""))
    completed = set(state.get("completed_steps", []))
    pending = [name for name in state.get("pipeline", []) if name not in completed]
    return pending[0] if pending else ""


def load(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))
