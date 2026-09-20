"""Advance a pipeline one step at a time, stopping at approvals and exceptions.

The orchestrator consumes validated inputs only. It never creates story content,
never changes assets, never retries paid work, and never publishes. A step that
raises StepFailure or returns a non-PASS outcome parks the run in the exception
queue; resuming always continues from the recorded checkpoint.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import run_state

SKILL_CHAIN = "skills/skill-chain.json"

# Steps that must not be crossed without an explicit human decision.
APPROVAL_BREAKPOINTS = {
    "short-drama-script-breakdown": "确认秒表脚本与节拍链",
    "short-drama-script-reviewer": "确认镜头拆解与角色/空间调度",
    "short-drama-prompt-compiler": "确认视频 Prompt、参数与本次成本",
    "short-drama-production-qa": "确认生成前 QA 结论与放行",
    "runninghub-local-adapter": "明确授权本次付费提交",
    "xiaoyunque-local-adapter": "明确授权本次付费提交",
    "libtv-local-adapter": "明确授权本次付费提交",
}

NON_PASS_OUTCOMES = {"qa_failure", "qa_uncertain", "missing_master", "unknown_cloud_task", "degraded_qa_failure"}


class StepFailure(Exception):
    """Raised by a step handler to park the run in the exception queue."""

    def __init__(self, reason: str, evidence: str = "") -> None:
        super().__init__(reason)
        self.reason = reason
        self.evidence = evidence


def plan_steps(chain: dict) -> list[str]:
    """Flatten the skill chain into an ordered, de-duplicated step list."""
    steps: list[str] = []
    for step in chain.get("steps", []):
        name = step.get("skill")
        if name and name not in steps:
            steps.append(name)
    return steps


def load_chain(path: str | Path = SKILL_CHAIN) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def start(state_path: str | Path, chain: dict, run_id: str, contract_id: str) -> dict:
    steps = plan_steps(chain)
    state = run_state.start_run(state_path, run_id, contract_id, steps[0])
    state["pipeline"] = steps
    run_state.write_task(state_path, state)
    return run_state.read_task(state_path)


def advance(state: dict, handlers: dict, approvals: set[str] | None = None) -> dict:
    """Run exactly one step, then return. Stops at approvals, exceptions, or the end."""
    approvals = approvals or set()
    steps = state.get("pipeline") or []
    if not steps:
        run_state.block(state, "-", "empty pipeline plan")
        return state
    current = run_state.resume_point(state)
    if not current:
        state["status"] = "COMPLETED"
        return state
    if current in APPROVAL_BREAKPOINTS and current not in approvals:
        run_state.wait_for_approval(state, current, APPROVAL_BREAKPOINTS[current])
        return state
    handler = handlers.get(current)
    if handler is None:
        run_state.block(state, current, f"no handler registered for {current}")
        return state
    try:
        result = handler() or {}
    except StepFailure as exc:
        run_state.pause_for_exception(state, current, exc.reason, exc.evidence)
        return state
    if result.get("outcome") in NON_PASS_OUTCOMES:
        run_state.pause_for_exception(state, current, result.get("reason", result["outcome"]), result.get("evidence", ""))
        return state
    run_state.complete(state, current)
    if state["status"] != "COMPLETED":
        state["status"] = "RUNNING"
        state.pop("pending_decision", None)
        next_step = run_state.resume_point(state)
        if next_step:
            state["current_step"] = next_step
            state["checkpoint"] = next_step
    return state
