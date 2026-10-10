"""Audit a finished or paused run: did each step actually invoke its Skill and
read the protocol documents that govern it?

This is the runtime half of protocol compliance. Read attestation proves the
agent read the core protocol *before starting*; this proves every *step* named
the Skill that ran it and the documents it relied on. A run that completed
without those fields is not a compliant run - it is an untraceable one.
"""
from __future__ import annotations

from . import step_registry
from .orchestrator import plan_steps
from .outcomes import COMPLETING_OUTCOMES

# The documents each step is expected to have actually open. Kept explicit in the
# registry so a missing read is a named failure, not a vague "did not follow
# protocol" - and read from there rather than repeated here, so adding a protocol
# file to a step is a one-line edit in `skills/skill-chain.json`.
#
# Protocol 3.0 (2026-09-20) added the _v3.0 file-name suffix.
def _protocol_requirements() -> dict[str, list[str]]:
    return {step.skill: list(step.protocol_refs) for step in step_registry.load()}


STEP_PROTOCOL_REQUIREMENTS = _protocol_requirements()


def _last_completed_event(state: dict, step: str) -> dict | None:
    for event in reversed(state.get("events", [])):
        if event.get("step") == step and event.get("outcome") in COMPLETING_OUTCOMES:
            return event
    return None


def _read_paths(event: dict) -> dict[str, str | None]:
    refs: dict[str, str | None] = {}
    for item in event.get("protocol_refs", []) or []:
        if isinstance(item, str):
            refs[item] = None
        elif isinstance(item, dict) and item.get("path"):
            refs[item["path"]] = item.get("sha256")
    return refs


def normalise_ref(path: str) -> str:
    """Reduce a protocol reference to a comparable key.

    A step may record a document as an absolute path, a project-relative path,
    or just its file name, and all three mean the same read. Comparing the raw
    strings treated those as different documents, so a step that had demonstrably
    opened `09_脚本优化与分镜拆解规范_v3.0.md` was reported as never having read
    it.

    The comparison key is the file name alone, lowercased. Protocol document
    names carry a version suffix and are unique across the protocol set, so the
    directory a copy lives in is not part of the document's identity - and an
    absolute path drags in as many ancestor directories as the install happens
    to have.
    """
    text = (path or "").strip().replace("\\", "/")
    while "//" in text:
        text = text.replace("//", "/")
    text = text.rstrip("/")
    if not text:
        return ""
    parts = [p for p in text.split("/") if p not in ("", ".")]
    if not parts:
        return ""
    return parts[-1].lower()


def missing_required_reads(event: dict, step: str) -> list[str]:
    """Which of this step's required documents it did not record opening.

    Returns the required paths in their canonical form (as written in
    STEP_PROTOCOL_REQUIREMENTS), so the board can name what is absent.
    """
    refs = _read_paths(event)
    recorded = {normalise_ref(p) for p in refs}
    required = STEP_PROTOCOL_REQUIREMENTS.get(step, [])
    return [p for p in required if normalise_ref(p) not in recorded]


def verify_run_compliance(state: dict, chain: dict | None = None, manifest: dict | None = None) -> dict:
    """Check every completed step for Skill identity, protocol reads, and evidence."""
    errors: list[str] = []
    steps = state.get("pipeline") or plan_steps(chain or {})
    completed = set(state.get("completed_steps", []))

    for step in steps:
        disposition = (state.get("step_dispositions") or {}).get(step, {})
        if disposition and not disposition.get("applicable", True):
            continue
        if step not in completed:
            continue
        event = _last_completed_event(state, step)
        if event is None:
            errors.append(f"{step}: marked completed but has no completing event")
            continue
        if not event.get("skill_id"):
            errors.append(f"{step}: event records no skill_id")
        elif event["skill_id"] != step:
            errors.append(f"{step}: event skill_id is {event['skill_id']}")
        if not event.get("evidence"):
            errors.append(f"{step}: event records no evidence path")
        refs = _read_paths(event)
        contract_steps = (state.get('execution_contract') or {}).get('steps', [])
        historical_step = next((s for s in contract_steps if s.get('id') == event.get('step_id')
                                or (not event.get('step_id') and s.get('skill') == step)), None)
        if historical_step is not None:
            recorded = {normalise_ref(p) for p in refs}
            missing = [r['path'] for r in historical_step.get('protocol_refs', [])
                       if normalise_ref(r['path']) not in recorded]
        else:
            missing = missing_required_reads(event, step)
        for path in missing:
            errors.append(f"{step}: did not record reading {path}")
        if manifest:
            by_path = {entry["path"]: entry["sha256"] for entry in manifest.get("files", [])}
            for path, digest in refs.items():
                if path in by_path and digest and digest != by_path[path]:
                    errors.append(f"{step}: {path} hash does not match the protocol manifest")

    covered = [s for s in steps if s in completed]
    not_applicable = [s for s in steps
                      if (state.get("step_dispositions") or {}).get(s, {}).get("applicable") is False]
    return {
        "status": "PASS" if not errors else "NON_COMPLIANT",
        "run_id": state.get("run_id"),
        "completed_steps": covered,
        "pending_steps": [s for s in steps if s not in completed and s not in not_applicable],
        "not_applicable_steps": not_applicable,
        "errors": errors,
    }


def compliance_gaps(state: dict, chain: dict | None = None) -> list[str]:
    """Steps that finished but left no trace of what they read."""
    result = verify_run_compliance(state, chain)
    return result["errors"]
