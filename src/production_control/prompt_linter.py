"""Lint the prompt unit independently of a chosen video provider."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = ROOT / "schemas"


def lint(unit: dict) -> list[str]:
    schema = json.loads((SCHEMAS / "prompt_unit.schema.json").read_text(encoding="utf-8"))
    errors = [error.message for error in Draft202012Validator(schema).iter_errors(unit)]
    skill = unit.get("skill_production", {})
    qa = unit.get("qa_review", {})
    script = unit.get("script_review", {})
    if not skill.get("skill_id"):
        errors.append("video prompts must be produced by a recorded Skill")
    if qa.get("status") != "PASS":
        errors.append("video prompt QA must be PASS before provider routing")
    if script.get("status") != "PASS":
        errors.append("script review must be PASS before provider routing")
    if unit.get("dialogue", {}).get("line_or_none") and unit.get("dialogue", {}).get("speaker") in {"", "none"}:
        errors.append("dialogue line requires one explicit speaker")
    return errors


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python -m production_control.prompt_linter <prompt_unit.json>")
        return 2
    unit = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    errors = lint(unit)
    print(json.dumps({"status": "PASS" if not errors else "FAIL", "errors": errors}, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
