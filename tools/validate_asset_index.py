"""Validate an asset_index.json structure without scanning or copying media."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from production_control.asset_registry import validate_registry


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python tools/validate_asset_index.py <asset_index.json>")
        return 2
    path = Path(sys.argv[1])
    errors = validate_registry(json.loads(path.read_text(encoding="utf-8")))
    print(json.dumps({"status": "PASS" if not errors else "FAIL", "errors": errors}, ensure_ascii=False, indent=2))
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
