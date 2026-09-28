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
from . import step_registry
from . import execution_contract

SKILL_CHAIN = "skills/skill-chain.json"

# Steps that must not be crossed without an explicit human decision. The prompts
# live on the steps themselves in `skills/skill-chain.json`; keeping a second
# name-keyed copy here is how the two drift apart.
APPROVAL_BREAKPOINTS = step_registry.approval_breakpoints()

NON_PASS_OUTCOMES = {"qa_failure", "qa_uncertain", "missing_master", "unknown_cloud_task", "degraded_qa_failure"}

# A step that reports success must also say which Skill ran it, which protocol
# documents it read, and where the evidence lives. No evidence, no completion.
REQUIRED_STEP_EVIDENCE = ("skill_id", "protocol_refs", "evidence")


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


def start(state_path: str | Path, chain: dict, run_id: str, contract_id: str, *,
          project_root: str | Path | None = None, segment: str = "", segment_title: str = "",
          series: str = "", episode: str = "", contract: dict | None = None) -> dict:
    """Begin one segment run.

    With project_root set, the run file lands in <project>/workflow/runs/<run_id>.json
    and the project index is updated, so a 20-segment episode stays navigable.

    segment_title is the human-readable name shown in reports, e.g.
    "B-2A（物理格斗）" rather than a bare code.
    """
    steps = [item["skill"] for item in contract["steps"]
             if item["applicable"]] if contract else plan_steps(chain)
    steps = list(dict.fromkeys(steps))
    if project_root:
        from . import run_index

        state_path = run_index.run_path(project_root, run_id)
        Path(state_path).parent.mkdir(parents=True, exist_ok=True)
        if not segment_title:
            # Adopt the name the user entered in the segment list, so the trace and
            # the report never disagree about what this segment is called.
            segment_title = run_index.segment_title_for(project_root, segment or run_id)
    state = run_state.start_run(state_path, run_id, contract_id, steps[0])
    state["pipeline"] = steps
    state["segment"] = segment or run_id
    state["segment_title"] = segment_title
    state["series"] = series
    state["episode"] = episode
    if contract:
        state["execution_contract"] = contract
        current = execution_contract.contract_step(contract, contract.get("current_step_id", ""))
        if current:
            state["current_step"] = current["skill"]
            state["checkpoint"] = current["skill"]
        # The registry can legitimately reuse one Skill for multiple stable
        # steps (for example, pre-generation and post-generation QA). Keep the
        # dashboard's Skill-level summary applicable if any matching step is;
        # the full per-step decisions remain in execution_contract.steps.
        dispositions: dict[str, dict] = {}
        for item in contract["steps"]:
            current_disposition = dispositions.get(item["skill"])
            if current_disposition is None or (item["applicable"] and not current_disposition["applicable"]):
                dispositions[item["skill"]] = {
                    "applicable": item["applicable"], "reason": item["reason"],
                    "step_id": item["id"], "disposition": item["disposition"],
                }
        state["step_dispositions"] = dispositions
        state["task_id"] = contract["task_id"]
        state["version"] = contract["version"]
        state["execution_model"] = contract["execution_model"]
        state["qa_model"] = contract["qa_model"]
    if project_root:
        state["project_root"] = str(project_root)
    run_state.write_task(state_path, state)
    _persist(state)
    return run_state.read_task(state_path)


def _persist(state: dict) -> None:
    """Write the run file and refresh the project index after every move.

    The report is only as good as what is on disk, so persistence happens inside
    the orchestrator rather than relying on a caller to remember.
    """
    root = state.get("project_root")
    if not root:
        return
    from . import run_index

    path = run_index.run_path(root, state.get("run_id", "RUN-UNKNOWN"))
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    run_state.write_task(path, state)

    index = run_index.load_index(root, series=state.get("series", ""), episode=state.get("episode", ""))
    # Only a segment that actually advanced takes over the active marker:
    # pre-creating later segments must not steal it from the one in progress.
    has_progress = bool(state.get("events"))
    run_index.register_run(index, state, make_active=has_progress or not index.get("active_run_id"))
    run_index.save_index(root, index)


def advance(state: dict, handlers: dict, approvals: set[str] | None = None) -> dict:
    """Run exactly one step, persist the result, then return."""
    state = _advance(state, handlers, approvals)
    _persist(state)
    return state


def _advance(state: dict, handlers: dict, approvals: set[str] | None = None) -> dict:
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
    missing = [field for field in REQUIRED_STEP_EVIDENCE if not result.get(field)]
    if missing:
        run_state.pause_for_exception(state, current, f"step reported success without recording {', '.join(missing)}")
        return state
    if result.get("skill_id") != current:
        run_state.pause_for_exception(state, current, f"skill_id {result.get('skill_id')!r} does not match step {current}")
        return state
    run_state.complete(
        state,
        current,
        skill_id=result.get("skill_id"),
        protocol_refs=result.get("protocol_refs"),
        validator=result.get("validator", ""),
        attestation_id=result.get("attestation_id", ""),
        evidence=result.get("evidence", ""),
    )
    if state["status"] != "COMPLETED":
        state["status"] = "RUNNING"
        state.pop("pending_decision", None)
        next_step = run_state.resume_point(state)
        if next_step:
            state["current_step"] = next_step
            state["checkpoint"] = next_step
    return state
