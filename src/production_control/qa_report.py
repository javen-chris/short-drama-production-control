"""Unified QA checks before and after generation, plus rework accounting."""
from __future__ import annotations

REQUIRED_PRE = {"authority", "script", "assets", "prompt", "skill", "authorization", "cost_estimate"}
REQUIRED_POST = {
    "decode", "duration", "resolution", "audio",
    "identity", "character_count", "limb", "prop", "continuity", "dialogue", "pseudo_text", "cost",
}
REWORK_CLASSES = ("identity", "character_count", "limb", "prop", "continuity", "dialogue", "image_quality", "cost")
VALID_VALUES = {"PASS", "FAIL", "UNCERTAIN"}

IMAGE_QUALITY_KEYS = {"decode", "duration", "resolution", "pseudo_text"}
DIALOGUE_KEYS = {"audio"}


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


def _rework_class(name: str) -> str:
    if name in IMAGE_QUALITY_KEYS:
        return "image_quality"
    if name in DIALOGUE_KEYS:
        return "dialogue"
    return name if name in REWORK_CLASSES else "image_quality"


def classify_rework(reports: list[dict]) -> dict[str, int]:
    """Aggregate failed and uncertain checks into the eight protocol classes."""
    counts = {name: 0 for name in REWORK_CLASSES}
    for report in reports:
        for name, value in report.get("checks", {}).items():
            if value in {"FAIL", "UNCERTAIN"}:
                counts[_rework_class(name)] += 1
    return counts


def top_rework_classes(reports: list[dict], limit: int = 3) -> list[tuple[str, int]]:
    counts = classify_rework(reports)
    ranked = [(name, count) for name, count in counts.items() if count > 0]
    ranked.sort(key=lambda item: (-item[1], item[0]))
    return ranked[:limit]
