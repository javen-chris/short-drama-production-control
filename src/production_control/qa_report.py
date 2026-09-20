from __future__ import annotations

REQUIRED_PRE = {"script", "assets", "prompt", "skill"}
REQUIRED_POST = {"decode", "duration", "resolution", "audio", "visual_continuity"}
VALID_VALUES = {"PASS", "FAIL", "UNCERTAIN"}


def validate_report(report: dict, phase: str) -> list[str]:
    required = REQUIRED_PRE if phase == "pre_generation" else REQUIRED_POST
    errors: list[str] = []
    if report.get("status") not in VALID_VALUES:
        errors.append("QA status must be PASS, FAIL, or UNCERTAIN")
    checks = report.get("checks", {})
    errors.extend(f"missing QA item: {x}" for x in required - set(checks))
    for name, value in checks.items():
        if value not in VALID_VALUES:
            errors.append(f"QA item {name} must be PASS/FAIL/UNCERTAIN, got {value!r}")
    if report.get("status") == "PASS":
        failed = sorted(name for name, value in checks.items() if value != "PASS")
        if failed:
            errors.append("QA status PASS requires every check to be PASS: " + ", ".join(failed))
    return errors
