"""Deterministic minimum-asset routing; no generation or network calls.

Tail frames and storyboards are authorization-gated enhancements: when the
user has not authorized producing them, the route degrades and production
continues instead of blocking. Character/scene MASTER authority still blocks.
"""
from __future__ import annotations

COMPLEX = {"physical_contact", "multi_character_choreography", "complex_prop_handoff", "cross_space_continuity", "complex_vfx_path"}
NON_BLOCKING_FLAGS = {"none", "real_tail_frame_required"}


def decide(unit: dict, roles: set[str], auth: dict | None = None) -> dict:
    auth = auth or {}
    flags = set(unit.get("risk_flags", []))
    missing: list[dict] = []
    fallback_notes: list[str] = []

    if "character_master" not in roles:
        missing.append({"role": "character_master", "purpose": "lock identity", "minimum_scope": "approved character master"})
    if "scene_master" not in roles:
        missing.append({"role": "scene_master", "purpose": "lock space", "minimum_scope": "approved scene master"})

    if "real_tail_frame_required" in flags and "real_tail_frame" not in roles:
        if auth.get("allow_tail_frame_generation"):
            fallback_notes.append("real_tail_frame authorized but not yet produced; produce it before submission")
        else:
            fallback_notes.append("no real_tail_frame and generation not authorized; degrade to confirmed start_state text")

    if flags & COMPLEX:
        if auth.get("allow_storyboard_generation"):
            route = "STORYBOARD_REQUIRED"
            reason = "复杂风险且已授权制作故事本；提交前需故事本拼版 QA PASS"
            prompt = "FAIL"
            degraded = False
        else:
            route = "DEGRADED_DIRECT"
            reason = "复杂风险但未授权制作故事本；降级为强化禁项的直接 Prompt，QA 加严"
            prompt = "PASS"
            degraded = True
            fallback_notes.append("storyboard not authorized; degraded_direct with strengthened prohibitions")
    elif missing:
        route = "ASSET_PLAN_REQUIRED"
        reason = "身份权威缺失：" + "、".join(x["role"] for x in missing)
        prompt = "FAIL"
        degraded = False
    elif flags - NON_BLOCKING_FLAGS:
        route = "KEYFRAME_REQUIRED"
        reason = "存在关键构图/状态风险，需关键状态图"
        prompt = "FAIL"
        degraded = False
    else:
        route = "PROMPT_ONLY_READY"
        reason = "资产齐全且无阻断风险"
        prompt = "PASS"
        degraded = False

    return {
        "production_unit_id": unit.get("production_unit_id"),
        "prompt_only": prompt,
        "recommended_route": route,
        "risk_factors": sorted(flags),
        "missing_assets": missing,
        "degraded": degraded,
        "fallback_notes": fallback_notes,
        "reason": reason,
        "blocked_until": [x["role"] for x in missing],
    }
