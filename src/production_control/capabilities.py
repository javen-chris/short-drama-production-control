"""Provider and image-channel capabilities.

The built-in tables are the fallback. `capabilities/providers.json` is the
auditable source of truth once it is present, and is schema-validated so a
stale or hand-edited manifest fails loudly instead of silently changing limits.
"""
from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

IMAGE_MODEL = "gpt-image-2"

IMAGE_CAPABILITIES = {
 "gpt_image2_local_subscription": {"channel": "gpt_image2_local_subscription", "model": IMAGE_MODEL, "backends": ["web", "codex"], "quota": "chatgpt_subscription", "cash_cost": 0, "max_references": 4, "parallel": False, "fallback": "gpt_image2_runninghub_workflow", "note": "本机 Hermes/Codex Agent 调用 GPT 前台；--project= 与 --keep-conversation 必带，参考图需轻量化"},
 "gpt_image2_runninghub_workflow": {"channel": "gpt_image2_runninghub_workflow", "model": IMAGE_MODEL, "backends": ["runninghub"], "quota": "paid", "cash_cost_cny": 0.1, "max_references": 3, "parallel": True, "fallback": None, "workflow_id": "2100124476636753922", "note": "付费兜底；必须走 runninghub_app.py 封装，务必先取得明确授权并记录单张成本"}
}

CAPABILITIES={
 "runninghub":{"provider":"runninghub","submission":"api","supports_prompt":True,"supports_keyframe":True,"supports_storyboard_composite":True,"max_resolution":"720p-test","status_polling":True},
 "xiaoyunque":{"provider":"xiaoyunque","submission":"api_or_mcp","supports_prompt":True,"supports_keyframe":True,"supports_storyboard_composite":True,"max_resolution":"provider-dependent","status_polling":True},
 "libtv":{"provider":"libtv","submission":"api_or_mcp","supports_prompt":True,"supports_keyframe":True,"supports_storyboard_composite":True,"max_resolution":"provider-dependent","status_polling":True}
}

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "capabilities" / "providers.json"
CAPABILITY_SCHEMA = ROOT / "schemas" / "provider_capability.schema.json"

_OVERRIDES: dict[str, dict] | None = None


def load_capabilities(path: str | Path = MANIFEST, *, reload: bool = False) -> dict[str, dict]:
    """Load and validate the capability manifest; fall back to the built-in table."""
    global _OVERRIDES
    target = Path(path)
    if not target.is_file():
        _OVERRIDES = {}
        return dict(CAPABILITIES)
    if _OVERRIDES is not None and not reload:
        return {**CAPABILITIES, **_OVERRIDES}
    manifest = json.loads(target.read_text(encoding="utf-8"))
    errors = validate_capabilities(manifest)
    if errors:
        raise ValueError("invalid capability manifest: " + "; ".join(errors))
    _OVERRIDES = {name: dict(record, provider=name) for name, record in manifest["providers"].items()}
    return {**CAPABILITIES, **_OVERRIDES}


def validate_capabilities(manifest: dict) -> list[str]:
    schema = json.loads(CAPABILITY_SCHEMA.read_text(encoding="utf-8"))
    errors = [e.message for e in Draft202012Validator(schema).iter_errors(manifest)]
    for name, record in manifest.get("providers", {}).items():
        if record.get("provider") != name:
            errors.append(f"{name}: provider field must match its key")
    return errors


def get_capability(provider: str) -> dict:
    table = load_capabilities()
    if provider not in table: raise ValueError(f"unsupported provider: {provider}")
    return table[provider].copy()

def get_image_capability(channel: str) -> dict:
    if channel not in IMAGE_CAPABILITIES: raise ValueError(f"unsupported image channel: {channel}")
    return IMAGE_CAPABILITIES[channel].copy()

