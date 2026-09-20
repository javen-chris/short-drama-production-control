"""Validate a production contract without contacting a provider."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = ROOT / "schemas"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def schema_errors(contract: dict) -> list[str]:
    schema = load_json(SCHEMAS / "production_contract.schema.json")
    prompt_schema = load_json(SCHEMAS / "prompt_unit.schema.json")
    registry = Registry().with_resources(
        [
            (schema["$id"], Resource.from_contents(schema)),
            (prompt_schema["$id"], Resource.from_contents(prompt_schema)),
        ]
    )
    return [error.message for error in Draft202012Validator(schema, registry=registry).iter_errors(contract)]


def policy_errors(contract: dict) -> list[str]:
    errors: list[str] = []
    roles = [asset["role"] for asset in contract.get("assets", [])]
    prompt = contract.get("prompt_unit", {})
    risk_flags = set(prompt.get("risk_flags", []))
    mode = contract.get("storyboard_mode")
    auth = contract.get("authorization", {})

    if not prompt.get("skill_production", {}).get("skill_id"):
        errors.append("every video prompt must record the Skill that produced it")
    if prompt.get("qa_review", {}).get("status") != "PASS":
        errors.append("every video prompt must have independent QA status PASS")
    if prompt.get("script_review", {}).get("status") != "PASS":
        errors.append("script review must be PASS before provider routing")

    if contract.get("current_gate") not in {"G5", "G6"}:
        errors.append("current_gate must be G5 or G6 for a provider-ready production contract")
    if "character_master" not in roles or "scene_master" not in roles:
        errors.append("character_master and scene_master are both required")
    if auth.get("video_submission_authorized") and auth.get("max_submissions", 0) != 1:
        errors.append("a submission-authorized first release contract must allow exactly one submission")
    if not auth.get("video_submission_authorized") and auth.get("max_submissions", 0) != 0:
        errors.append("max_submissions must be 0 when video submission is not authorized")
    complex_flags = {"physical_contact", "multi_character_choreography", "complex_prop_handoff", "cross_space_continuity", "complex_vfx_path"}
    if risk_flags & complex_flags and mode not in {"storyboard_required", "degraded_direct"}:
        errors.append("complex risk flags require storyboard_required mode or degraded_direct fallback")
    if mode == "storyboard_required" and not auth.get("allow_storyboard_generation"):
        errors.append("storyboard_required mode requires authorization.allow_storyboard_generation")
    if mode == "storyboard_required" and "storyboard_composite" not in roles:
        errors.append("storyboard_required mode needs one storyboard_composite asset, never individual storyboard frames")
    if mode == "degraded_direct":
        if auth.get("allow_storyboard_generation"):
            errors.append("degraded_direct must not be used when storyboard generation is authorized")
        if not risk_flags & complex_flags:
            errors.append("degraded_direct fallback only applies to complex risk flags")
    if mode == "keyframe_assisted" and "keyframe" not in roles:
        errors.append("keyframe_assisted mode needs at least one keyframe asset")
    if "real_tail_frame_required" in risk_flags:
        if auth.get("allow_tail_frame_generation") and "real_tail_frame" not in roles:
            errors.append("real_tail_frame_required with tail-frame generation authorized needs a real_tail_frame asset")
    # No real_tail_frame and generation not authorized -> allowed to continue degraded;
    # the degradation is recorded by asset_decider.fallback_notes, never a blocking error.
    if "none" in risk_flags and len(risk_flags) != 1:
        errors.append("risk_flags may contain none only by itself")
    return errors


def validate_contract(contract: dict) -> list[str]:
    return schema_errors(contract) + policy_errors(contract)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python -m production_control.contract_validator <production_contract.json>")
        return 2
    errors = validate_contract(load_json(Path(sys.argv[1])))
    if errors:
        print(json.dumps({"status": "BLOCKED_PRECHECK", "errors": errors}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({"status": "READY_FOR_PROVIDER_ADAPTER"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
