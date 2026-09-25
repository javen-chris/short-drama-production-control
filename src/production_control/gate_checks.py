"""Interpret auxiliary trace activity using the registry's Gate check definitions.

This projection never converts an auxiliary event into a completed protocol step.
Unknown activity remains visible in the chain-out section of the report.
"""
from __future__ import annotations

import json

from . import step_registry


def definitions() -> list[dict]:
    path = step_registry.repo_root() / step_registry.CHAIN_RELPATH
    try:
        rows = json.loads(path.read_text(encoding="utf-8")).get("gate_checks", [])
    except (OSError, ValueError):
        return []
    return rows if isinstance(rows, list) else []


def classify(audit_rows: list[dict]) -> tuple[list[dict], set[str]]:
    """Return check states and names handled, leaving unknown names untouched."""
    extras = {row.get("step"): row for row in audit_rows if row.get("verdict") == "EXTRA"}
    handled: set[str] = set()
    checks: list[dict] = []
    for definition in definitions():
        names = definition.get("activity_names") or []
        matches = [extras[name] for name in names if name in extras]
        handled.update(row["step"] for row in matches)
        latest = max(matches, key=lambda row: row.get("at") or "") if matches else None
        superseding = [extras[name] for name in definition.get("superseded_by", []) if name in extras]
        superseded = bool(latest and any(
            (row.get("at") or "") > (latest.get("at") or "") for row in superseding
        ))
        outcome = (latest or {}).get("outcome") or ""
        if not latest:
            status, label = "todo", "未见记录"
        elif superseded:
            status, label = "warn", "范围已变，需复核"
        elif outcome in {"BLOCKED", "FAILED", "PAUSED_EXCEPTION"}:
            status, label = "bad", "阻断"
        elif outcome == "COMPLETED":
            # Historical producer claims cannot satisfy an independent Gate.
            status, label = "wait", "已记录，待核验"
        else:
            status, label = "wait", "已提交，待核验"
        checks.append({
            "id": definition.get("id", ""), "gate": definition.get("gate", ""),
            "name": definition.get("name_zh", ""), "kind": definition.get("kind", ""),
            "purpose": definition.get("purpose_zh", ""),
            "decision": definition.get("decision_zh", ""),
            "counts_as_step_progress": definition.get("counts_as_step_progress", False),
            "status": status, "label": label, "latest": latest,
            "count": len(matches), "superseded": superseded,
        })
    return checks, handled
