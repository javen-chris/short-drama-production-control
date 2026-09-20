"""Pre-flight hard gate before any video node is built.

Character, scene, and prop MASTER manifests are mandatory. Tail frames and
storyboards are authorization-gated: missing ones must be recorded as a
degradation, and they never block the gate on their own.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = ROOT / "schemas"

MANDATORY_MASTER = {"character_master", "scene_master", "prop_master"}
DEGRADABLE = {"tail_frame", "storyboard"}


def schema_errors(record: dict) -> list[str]:
    schema = json.loads((SCHEMAS / "preflight.schema.json").read_text(encoding="utf-8"))
    return [e.message for e in Draft202012Validator(schema).iter_errors(record)]


def policy_errors(record: dict) -> list[str]:
    errors: list[str] = []
    manifest = record.get("asset_manifest", [])
    roles = {item.get("role") for item in manifest}
    resolved = {item.get("role") for item in manifest if item.get("path")}
    degraded = {item.get("role") for item in manifest if item.get("degraded_note") and not item.get("path")}
    status = record.get("node_status")

    missing_master = sorted(MANDATORY_MASTER - resolved)
    if missing_master and status == "READY_FOR_NODE":
        errors.append("MASTER manifest incomplete, node status cannot be READY: " + ", ".join(missing_master))
    for item in manifest:
        role = item.get("role")
        if role in DEGRADABLE and role not in resolved and role not in degraded:
            errors.append(f"{role}: missing and not recorded as a degradation")
        if item.get("path") and item.get("degraded_note"):
            errors.append(f"{role}: cannot both resolve a path and declare a degradation")
    if status == "BLOCKED_PRECHECK":
        if not record.get("missing"):
            errors.append("BLOCKED_PRECHECK requires a populated missing list")
        if not missing_master:
            errors.append("BLOCKED_PRECHECK must name the unmet mandatory asset, not a tail frame or storyboard alone")
    for grids in manifest:
        if grids.get("role") == "storyboard" and grids.get("path") and not grids.get("storyboard_grids_confirmed"):
            errors.append("storyboard grids and reading order must be confirmed before it is used")
    return errors


def validate_preflight(record: dict) -> list[str]:
    return schema_errors(record) + policy_errors(record)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python -m production_control.preflight_gate <preflight.json>")
        return 2
    record = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    errors = validate_preflight(record)
    print(json.dumps({"status": "PASS" if not errors else "BLOCKED_PRECHECK", "errors": errors}, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
