from __future__ import annotations
REQUIRED_PRE={"script","assets","prompt","skill"}; REQUIRED_POST={"decode","duration","resolution","audio","visual_continuity"}
def validate_report(report: dict, phase: str) -> list[str]:
    required=REQUIRED_PRE if phase=="pre_generation" else REQUIRED_POST
    errors=[]
    if report.get("status")!="PASS": errors.append("QA status must be PASS")
    errors.extend(f"missing QA item: {x}" for x in required-set(report.get("checks",{})))
    return errors

