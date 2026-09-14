"""Deterministic minimum-asset routing; no generation or network calls."""
from __future__ import annotations

COMPLEX = {"physical_contact", "multi_character_choreography", "complex_prop_handoff", "cross_space_continuity", "complex_vfx_path"}

def decide(unit: dict, roles: set[str]) -> dict:
    flags = set(unit.get("risk_flags", [])); missing=[]
    if "character_master" not in roles: missing.append({"role":"character_master","purpose":"lock identity","minimum_scope":"approved character master"})
    if "scene_master" not in roles: missing.append({"role":"scene_master","purpose":"lock space","minimum_scope":"approved scene master"})
    if flags & COMPLEX: route="STORYBOARD_REQUIRED"; prompt="FAIL"
    elif missing: route="ASSET_PLAN_REQUIRED"; prompt="FAIL"
    elif flags - {"none"}: route="KEYFRAME_REQUIRED"; prompt="FAIL"
    else: route="PROMPT_ONLY_READY"; prompt="PASS"
    return {"production_unit_id":unit.get("production_unit_id"),"prompt_only":prompt,"recommended_route":route,"risk_factors":sorted(flags),"missing_assets":missing,"reason":"; ".join(["复杂风险" if flags & COMPLEX else "资产齐全且低风险"]),"blocked_until":[x["role"] for x in missing]}

