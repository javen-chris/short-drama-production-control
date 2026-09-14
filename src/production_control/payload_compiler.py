from __future__ import annotations
from .capabilities import get_capability
def compile_payload(contract: dict, prompt: dict, decision: dict) -> dict:
    if not contract.get("authorization",{}).get("video_submission_authorized"): raise ValueError("video submission is not authorized")
    if prompt.get("qa_review",{}).get("status")!="PASS" or prompt.get("script_review",{}).get("status")!="PASS": raise ValueError("prompt/script QA must be PASS")
    if decision.get("recommended_route") in {"ASSET_PLAN_REQUIRED","BLOCKED_MISSING_MASTER"}: raise ValueError("asset decision blocks submission")
    cap=get_capability(contract["provider"])
    return {"payload_id":f"{contract['contract_id']}-{prompt['unit_id']}","production_unit_id":decision["production_unit_id"],"provider":contract["provider"],"contract_id":contract["contract_id"],"prompt_unit_id":prompt["unit_id"],"asset_paths":[a["path"] for a in contract["assets"]],"submission_authorized":True,"capability_snapshot":cap}

