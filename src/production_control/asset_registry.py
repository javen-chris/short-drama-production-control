"""Asset registry: pin MASTER identity to a real file and its hash.

This closes the gap where contract asset paths were free-form strings that no
checker ever opened. Every referenced must exist in the registry, be APPROVED,
carry the same role, and match its recorded sha256.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

from .provenance import sha256_file

ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = ROOT / "schemas"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_registry(registry: dict) -> list[str]:
    schema = load_json(SCHEMAS / "asset_registry.schema.json")
    errors = [e.message for e in Draft202012Validator(schema).iter_errors(registry)]
    for asset in registry.get("assets", []):
        if asset.get("status") == "APPROVED" and not asset.get("qa_evidence"):
            errors.append(f"{asset.get('asset_id')}: APPROVED assets need qa_evidence")
        if asset.get("role", "").endswith("master") and not asset.get("image_channel"):
            errors.append(f"{asset.get('asset_id')}: image channels must be recorded for MASTER assets")
    by_id: dict[str, dict] = {}
    for asset in registry.get("assets", []):
        asset_id = asset.get("asset_id")
        if asset_id in by_id:
            errors.append(f"duplicate asset_id: {asset_id}")
        by_id[asset_id] = asset
    return errors


def check_contract_assets(registry: dict, assets: list[dict], *, verify_files: bool = True) -> list[str]:
    """Verify that every contract asset resolves to an approved registry entry."""
    errors: list[str] = []
    entries = {asset.get("path"): asset for asset in registry.get("assets", [])}
    for asset in assets:
        path = asset.get("path", "")
        entry = entries.get(path)
        if entry is None:
            errors.append(f"{path}: not found in the asset registry")
            continue
        if entry.get("role") != asset.get("role"):
            errors.append(f"{path}: registry role is {entry.get('role')}, contract expects {asset.get('role')}")
        if entry.get("status") != "APPROVED":
            errors.append(f"{path}: registry status is {entry.get('status')}, only APPROVED may be used")
        if verify_files:
            target = Path(path)
            if not target.is_file():
                errors.append(f"{path}: file does not exist")
                continue
            expected = entry.get("sha256")
            if not expected:
                errors.append(f"{path}: registry entry has no sha256 baseline")
                continue
            actual = sha256_file(target)
            if actual != expected:
                errors.append(f"{path}: sha256 mismatch (registry {expected[:12]}..., file {actual[:12]}...)")
    return errors


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: python -m production_control.asset_registry <asset_registry.json> <production_contract.json>")
        return 2
    registry = load_json(Path(sys.argv[1]))
    contract = load_json(Path(sys.argv[2]))
    errors = validate_registry(registry) + check_contract_assets(registry, contract.get("assets", []))
    print(json.dumps({"status": "PASS" if not errors else "BLOCKED_PRECHECK", "errors": errors}, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
