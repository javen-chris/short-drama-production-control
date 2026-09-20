"""Verify that an agent actually read the current core protocol.

Three independent checks, all of which must pass:

1. Fingerprint - the attestation quotes the manifest fingerprint, so it was
   produced against a known protocol state, not an old one.
2. Read proof - every core file must be declared with the exact sha256 from the
   manifest, and the on-disk file must still hash to the same value.
3. Challenges - the manifest carries questions whose answers are stored only as
   hashes; a correct answer cannot be copied from the manifest, it has to come
   from the documents themselves.

Schema-passing alone is never content QA: a structurally valid attestation with
wrong hashes or wrong answers is REJECTED.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = ROOT / "schemas"

MANIFEST_DEFAULT = Path(r"D:\AIGC短剧本地工作流规则及协议\短剧制作核心协议\protocol_manifest.json")


def schema_errors(attestation: dict) -> list[str]:
    schema = json.loads((SCHEMAS / "protocol_attestation.schema.json").read_text(encoding="utf-8"))
    return [e.message for e in Draft202012Validator(schema).iter_errors(attestation)]


def _normalize(answer: str) -> str:
    return " ".join(answer.split()).strip().lower()


def verify_attestation(attestation: dict, manifest: dict, protocol_root: str | Path) -> list[str]:
    errors = schema_errors(attestation)
    if errors:
        return errors

    if attestation.get("manifest_fingerprint") != manifest.get("fingerprint"):
        errors.append("manifest_fingerprint does not match; regenerate the attestation against the current protocol")

    declared = {entry.get("path"): entry.get("sha256") for entry in attestation.get("read_files", [])}
    for entry in manifest.get("files", []):
        rel, expected = entry["path"], entry["sha256"]
        quoted = declared.get(rel)
        if quoted is None:
            errors.append(f"core file not declared as read: {rel}")
            continue
        if quoted != expected:
            errors.append(f"{rel}: declared sha256 does not match the manifest")
            continue
        target = Path(protocol_root) / rel
        if not target.is_file():
            errors.append(f"{rel}: file missing on disk")
        else:
            digest = hashlib.sha256()
            with target.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            if digest.hexdigest() != expected:
                errors.append(f"{rel}: file changed since the manifest was generated; regenerate the manifest")

    answered = {item.get("id"): item.get("answer", "") for item in attestation.get("answers", [])}
    for challenge in manifest.get("challenges", []):
        answer = answered.get(challenge["id"])
        if answer is None:
            errors.append(f"challenge unanswered: {challenge['id']}")
            continue
        digest = hashlib.sha256(_normalize(answer).encode("utf-8")).hexdigest()
        if digest != challenge.get("answer_sha256"):
            errors.append(f"challenge {challenge['id']}: wrong answer")
    return errors


def verdict(attestation: dict, manifest: dict, protocol_root: str | Path) -> dict:
    errors = verify_attestation(attestation, manifest, protocol_root)
    return {"status": "PASS" if not errors else "REJECTED", "errors": errors}


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python -m production_control.protocol_attestation <attestation.json>")
        return 2
    attestation = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    if not MANIFEST_DEFAULT.is_file():
        print("protocol manifest not found; run tools/protocol_fingerprint.py generate first")
        return 2
    manifest = json.loads(MANIFEST_DEFAULT.read_text(encoding="utf-8"))
    result = verdict(attestation, manifest, manifest.get("protocol_root", MANIFEST_DEFAULT.parent))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
