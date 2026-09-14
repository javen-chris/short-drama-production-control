"""Check camera-language variety across an ordered list of prompt units."""
from __future__ import annotations

import json
import sys
from pathlib import Path


def signature(unit: dict) -> tuple[str, ...]:
    shot = unit.get("shot_language", {})
    return tuple(shot.get(k, "") for k in ("scale", "angle", "movement", "screen_direction"))


def lint_sequence(units: list[dict]) -> list[str]:
    errors: list[str] = []
    for previous, current in zip(units, units[1:]):
        if signature(previous) == signature(current) and not current.get("repeat_reason"):
            errors.append(f"{current.get('unit_id', '?')}: repeated shot language needs repeat_reason")
    return errors


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python -m production_control.shot_language_linter <ordered-units.json>")
        return 2
    units = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    errors = lint_sequence(units)
    print(json.dumps({"status": "PASS" if not errors else "FAIL", "errors": errors}, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())

