"""Append one step to a run trace.

Protocol 18 says every completed step must be recorded, and a step with no record
counts as not done. Hand-writing the nested JSON is error-prone, so appending is
one call: the step, the skill that ran it, the protocol documents it read, the
evidence path, and the outcome.

Python-side helper; the CLI wrapper is tools/append_event.py.
"""
from __future__ import annotations

import json
import warnings
from datetime import datetime, timezone
from pathlib import Path

from . import run_index, run_state


def append_event(project_root: str | Path, run_id: str, *, step: str, skill_id: str = "",
                 protocol_refs: list[str] | None = None, evidence: str = "",
                 outcome: str = "COMPLETED", reason: str = "", validator: str = "",
                 at: str = "", allow_missing_evidence: bool = False) -> dict:
    """Append one event and return the updated state.

    If an evidence path is given it must exist: pointing at a file that is not
    there is how a trace starts claiming work it cannot show. Write the evidence
    first, then record the step. Use allow_missing_evidence only when the step
    genuinely has no artefact of its own.
    """
    root = Path(project_root)
    path = run_index.run_path(root, run_id)
    if not path.is_file():
        raise FileNotFoundError(f"没有找到轨迹文件：{path}（先创建该段的运行，或检查 run_id）")

    if evidence and not allow_missing_evidence:
        target = root / evidence
        if not target.is_file():
            raise FileNotFoundError(
                f"证据文件不存在：{target}\n"
                "按 18 号规则，证据必须真实存在——先把这一步的实际产物／记录写成文件，再记事件。"
            )
    if not evidence:
        warnings.warn("这一步没有 evidence 路径；18 号规则要求每步都能追到证据", stacklevel=2)

    state = json.loads(path.read_text(encoding="utf-8"))

    event = {
        "step": step,
        "outcome": outcome,
        "at": at or datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "skill_id": skill_id or step,
        "protocol_refs": [{"path": p} for p in (protocol_refs or [])],
        "evidence": evidence,
        "validator": validator,
    }
    if reason:
        event["reason"] = reason

    state.setdefault("events", []).append(event)

    pipeline = state.get("pipeline") or []
    if outcome == "COMPLETED":
        completed = state.setdefault("completed_steps", [])
        if step not in completed:
            completed.append(step)
        remaining = [s for s in pipeline if s not in completed]
        state["current_step"] = remaining[0] if remaining else ""
        state["status"] = "COMPLETED" if not remaining else "RUNNING"
        state.pop("pending_decision", None)
    elif outcome in {"WAITING_APPROVAL", "PAUSED_EXCEPTION", "BLOCKED"}:
        state["status"] = outcome if outcome != "WAITING_APPROVAL" else "WAITING_APPROVAL"
        state["current_step"] = step
        if reason:
            state["pending_decision"] = reason

    run_state.write_task(path, state)
    index = run_index.load_index(root)
    run_index.register_run(index, state, make_active=state.get("status") != "COMPLETED")
    run_index.save_index(root, index)
    return state
