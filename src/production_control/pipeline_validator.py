"""Validate the object chain before a provider payload can exist."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = ROOT / "schemas"


def validate_file(data: dict, schema_name: str) -> list[str]:
    schema = json.loads((SCHEMAS / schema_name).read_text(encoding="utf-8"))
    return [e.message for e in Draft202012Validator(schema).iter_errors(data)]


def validate_chain(bundle: dict) -> list[str]:
    errors: list[str] = []
    for key, schema in (("script", "script_breakdown.schema.json"), ("shots", "shot_unit.schema.json"), ("production_units", "production_unit.schema.json"), ("asset_decisions", "asset_decision.schema.json")):
        values = bundle.get(key, []) if key != "script" else [bundle.get(key, {})]
        for value in values:
            errors.extend(f"{key}: {message}" for message in validate_file(value, schema))
    script_id = bundle.get("script", {}).get("script_id")
    if bundle.get("script", {}).get("status") != "PASS":
        errors.append("script must be PASS before downstream objects")
    if any(shot.get("script_id") != script_id for shot in bundle.get("shots", [])):
        errors.append("every shot must reference the same script_id")
    shot_ids = {shot.get("shot_id") for shot in bundle.get("shots", [])}
    for unit in bundle.get("production_units", []):
        if not set(unit.get("shot_ids", [])).issubset(shot_ids):
            errors.append(f"{unit.get('production_unit_id')}: unknown shot_id")
    unit_ids = {unit.get("production_unit_id") for unit in bundle.get("production_units", [])}
    for decision in bundle.get("asset_decisions", []):
        if decision.get("production_unit_id") not in unit_ids:
            errors.append(f"{decision.get('production_unit_id')}: asset decision has no production unit")
    return errors


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python -m production_control.pipeline_validator <pipeline-bundle.json>")
        return 2
    bundle = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    errors = validate_chain(bundle)
    print(json.dumps({"status": "PASS" if not errors else "BLOCKED_PRECHECK", "errors": errors}, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())

