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
