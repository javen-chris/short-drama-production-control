from __future__ import annotations

from .capabilities import get_capability

ROUTE_TO_MODE = {
    "PROMPT_ONLY_READY": "direct_prompt",
    "KEYFRAME_REQUIRED": "keyframe_assisted",
    "STORYBOARD_REQUIRED": "storyboard_required",
    "DEGRADED_DIRECT": "degraded_direct",
}
BLOCKING_ROUTES = {"ASSET_PLAN_REQUIRED", "BLOCKED_MISSING_MASTER"}


def compile_payload(contract: dict, prompt: dict, decision: dict) -> dict:
    if not contract.get("authorization", {}).get("video_submission_authorized"):
        raise ValueError("video submission is not authorized")
    if prompt.get("qa_review", {}).get("status") != "PASS" or prompt.get("script_review", {}).get("status") != "PASS":
        raise ValueError("prompt/script QA must be PASS")
    route = decision.get("recommended_route")
    if route in BLOCKING_ROUTES:
        raise ValueError(f"asset decision blocks submission: {route}")
    if route not in ROUTE_TO_MODE:
        raise ValueError(f"unknown recommended_route: {route}")
    expected_mode = ROUTE_TO_MODE[route]
    if contract.get("storyboard_mode") != expected_mode:
        raise ValueError(f"storyboard_mode {contract.get('storyboard_mode')!r} does not match route {route} (expected {expected_mode})")
    roles = {asset.get("role") for asset in contract.get("assets", [])}
    if route == "STORYBOARD_REQUIRED" and "storyboard_composite" not in roles:
        raise ValueError("STORYBOARD_REQUIRED route needs one storyboard_composite asset before submission")
    if route == "KEYFRAME_REQUIRED" and "keyframe" not in roles:
        raise ValueError("KEYFRAME_REQUIRED route needs at least one keyframe asset before submission")
    if prompt.get("unit_id") != decision.get("production_unit_id"):
        raise ValueError("prompt unit_id does not match decision production_unit_id")
    cap = get_capability(contract["provider"])
    return {
        "payload_id": f"{contract['contract_id']}-{prompt['unit_id']}",
        "production_unit_id": decision["production_unit_id"],
        "provider": contract["provider"],
        "contract_id": contract["contract_id"],
        "prompt_unit_id": prompt["unit_id"],
        "asset_paths": [a["path"] for a in contract["assets"]],
        "submission_authorized": True,
        "degraded": bool(decision.get("degraded", False)),
        "fallback_notes": decision.get("fallback_notes", []),
        "capability_snapshot": cap,
    }
