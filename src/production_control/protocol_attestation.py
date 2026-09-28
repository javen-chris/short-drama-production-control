"""Verify a Gate-scoped protocol read proof bound to a RUN contract.

Three independent checks, all of which must pass:

1. Fingerprint - the attestation quotes the manifest fingerprint, so it was
   produced against a known protocol state, not an old one.
2. Read proof - common safety rules plus the current Gate's applicable protocol
   refs must match the manifest and on-disk hashes.
3. Challenges - the manifest carries questions whose answers are stored only as
   hashes; a correct answer cannot be copied from the manifest, it has to come
   from the documents themselves.

Schema-passing alone is never content QA: a structurally valid attestation with
wrong hashes or wrong answers is REJECTED.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from . import protocol_fingerprint
from . import run_state

ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = ROOT / "schemas"

MANIFEST_DEFAULT = Path(r"D:\AIGC短剧本地工作流规则及协议\短剧制作核心协议\protocol_manifest.json")


def schema_errors(attestation: dict) -> list[str]:
    schema = json.loads((SCHEMAS / "protocol_attestation.schema.json").read_text(encoding="utf-8"))
    return [e.message for e in Draft202012Validator(schema).iter_errors(attestation)]


def _normalize(answer: str) -> str:
    return " ".join(answer.split()).strip().lower()


def scoped_protocols(contract: dict, scope_gate: str) -> tuple[set[str], set[str], list[str]]:
    """Return required paths, gate-only paths, and the stable current gate."""
    current_id = contract.get("current_step_id", "")
    current = next((item for item in contract.get("steps", []) if item.get("id") == current_id), None)
    if not current or not current.get("applicable"):
        raise ValueError("RUN 合同没有可用的当前步骤")
    gates = current.get("gate", [])
    expected_gate = gates[0] if gates else ""
    if not expected_gate or scope_gate != expected_gate:
        raise ValueError(f"scope_gate 必须是当前合同步骤的 Gate：{expected_gate or '未登记'}")
    gate_steps = [item for item in contract.get("steps", [])
                  if item.get("applicable") and scope_gate in item.get("gate", [])]
    gate_refs = {ref["path"] for item in gate_steps for ref in item.get("protocol_refs", [])}
    required = set(protocol_fingerprint.REQUIRED_CORE_FILES) | gate_refs
    if contract.get("target_mode"):
        required.update(protocol_fingerprint.TARGET_MODE_PROTOCOL_FILES)
    return required, gate_refs, [item["id"] for item in gate_steps]


def _required_challenge_ids(task_id: str, scope_gate: str, gate_refs: set[str], manifest: dict,
                           *, include_common: bool = True) -> set[str]:
    challenges = manifest.get("challenges", [])
    required = ({item["id"] for item in challenges if item.get("id") == "protocol-version"}
                if include_common else set())
    candidates = [item for item in challenges
                  if item.get("id") != "protocol-version"
                  and gate_refs.intersection(item.get("protocol_refs", []))]
    if candidates:
        seed = hashlib.sha256(f"{task_id}:{scope_gate}".encode("utf-8")).digest()
        required.add(candidates[int.from_bytes(seed[:4], "big") % len(candidates)]["id"])
    return required


def _valid_prior_attestations(contract: dict, manifest: dict,
                              prior_attestations: list[dict] | None) -> list[dict]:
    return [item for item in (prior_attestations or [])
            if item.get("status") == "PASS"
            and item.get("run_id") == contract.get("run_id")
            and item.get("task_id") == contract.get("task_id")
            and item.get("contract_id") == contract.get("contract_id")
            and item.get("manifest_fingerprint") == manifest.get("fingerprint")]


def build_attestation_plan(contract: dict, manifest: dict,
                           prior_attestations: list[dict] | None = None) -> dict:
    current = next((item for item in contract.get("steps", [])
                    if item.get("id") == contract.get("current_step_id")), None)
    if not current or not current.get("applicable") or not current.get("gate"):
        raise ValueError("RUN 合同没有可用的当前 Gate")
    gate = current["gate"][0]
    required, gate_refs, covered = scoped_protocols(contract, gate)
    hashes = {item.get("path"): item.get("sha256") for item in manifest.get("files", [])}
    prior = _valid_prior_attestations(contract, manifest, prior_attestations)
    prior_paths = {path for item in prior for path in item.get("protocol_paths", [])}
    missing = sorted(required - hashes.keys())
    if missing:
        raise ValueError("协议清单缺少当前范围文件：" + ", ".join(missing))
    challenges = {item["id"]: item for item in manifest.get("challenges", [])}
    prior_challenges = {challenge for item in prior for challenge in item.get("challenge_ids", [])}
    challenge_ids = _required_challenge_ids(
        contract.get("task_id", ""), gate, gate_refs, manifest,
        include_common="protocol-version" not in prior_challenges,
    )
    challenge_plan = []
    for challenge_id in sorted(challenge_ids):
        if challenge_id not in challenges:
            raise ValueError(f"协议清单缺少当前范围挑战题：{challenge_id}")
        challenge_plan.append({"id": challenge_id, "prompt": challenges[challenge_id]["prompt"]})
    return {
        "status": "PLAN_NOT_PROOF",
        "message": "以下是本 Gate 的读取清单，不代表 Agent 已经读取；读完后再填写并提交证明。",
        "run_id": contract["run_id"], "task_id": contract["task_id"],
        "contract_id": contract["contract_id"], "scope_gate": gate,
        "covered_step_ids": covered, "manifest_fingerprint": manifest["fingerprint"],
        "protocols_to_read": [{"path": path, "sha256": hashes[path]}
                              for path in sorted(required - prior_paths)],
        "already_verified_protocols": sorted(required & prior_paths),
        "challenge_questions": challenge_plan,
    }


def verify_attestation(attestation: dict, manifest: dict, protocol_root: str | Path,
                       contract: dict | None = None,
                       prior_attestations: list[dict] | None = None) -> list[str]:
    errors = schema_errors(attestation)
    if errors:
        return errors

    if attestation.get("manifest_fingerprint") != manifest.get("fingerprint"):
        errors.append("manifest_fingerprint does not match; regenerate the attestation against the current protocol")

    if not contract:
        return errors + ["RUN execution contract is required to determine the minimum protocol scope"]
    for field in ("run_id", "task_id", "contract_id"):
        if attestation.get(field) != contract.get(field):
            errors.append(f"{field} does not match the RUN execution contract")
    try:
        required_paths, gate_refs, covered_steps = scoped_protocols(contract, attestation.get("scope_gate", ""))
    except ValueError as exc:
        return errors + [str(exc)]
    attested_step_ids = set(attestation.get("covered_step_ids", []))
    if not set(covered_steps).issubset(attested_step_ids):
        errors.append("covered_step_ids do not cover all applicable steps in the current Gate")

    prior = _valid_prior_attestations(contract, manifest, prior_attestations)
    prior_paths = {path for item in prior for path in item.get("protocol_paths", [])}
    prior_challenges = {challenge for item in prior for challenge in item.get("challenge_ids", [])}
    new_required_paths = required_paths - prior_paths
    declared = {entry.get("path"): entry.get("sha256") for entry in attestation.get("read_files", [])}
    manifest_files = {entry.get("path"): entry.get("sha256") for entry in manifest.get("files", [])}
    for rel in sorted(new_required_paths):
        expected = manifest_files.get(rel)
        if expected is None:
            errors.append(f"{rel}: required protocol missing from manifest; regenerate")
            continue
        quoted = declared.get(rel)
        if quoted is None:
            errors.append(f"required file not declared as read for {attestation.get('scope_gate')}: {rel}")
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

    answers = attestation.get("answers", [])
    answered = {item.get("id"): item.get("answer", "") for item in answers}
    expected_ids = _required_challenge_ids(
        contract.get("task_id", ""), attestation.get("scope_gate", ""), gate_refs, manifest,
        include_common="protocol-version" not in prior_challenges,
    )
    for challenge_id in sorted(expected_ids):
        challenge = next((item for item in manifest.get("challenges", [])
                          if item.get("id") == challenge_id), None)
        if challenge is None:
            errors.append(f"required challenge missing from manifest: {challenge_id}")
            continue
        answer = answered.get(challenge["id"])
        if answer is None:
            errors.append(f"challenge unanswered: {challenge['id']}")
            continue
        digest = hashlib.sha256(_normalize(answer).encode("utf-8")).hexdigest()
        if digest != challenge.get("answer_sha256"):
            errors.append(f"challenge {challenge['id']}: wrong answer")
    return errors


def verdict(attestation: dict, manifest: dict, protocol_root: str | Path,
            contract: dict | None = None,
            prior_attestations: list[dict] | None = None) -> dict:
    errors = verify_attestation(attestation, manifest, protocol_root, contract, prior_attestations)
    return {"status": "PASS" if not errors else "REJECTED", "errors": errors}


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify and attach a Gate-scoped protocol read proof to a RUN.")
    parser.add_argument("attestation", nargs="?", help="PROTOCOL_ATTESTATION JSON file")
    parser.add_argument("--plan", action="store_true", help="只显示当前 Gate 需读文件与挑战题，不产生证明")
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    if not MANIFEST_DEFAULT.is_file():
        print("protocol manifest not found; run tools/protocol_fingerprint.py generate first")
        return 2
    manifest = json.loads(MANIFEST_DEFAULT.read_text(encoding="utf-8"))
    run_path = Path(args.project_root) / "workflow" / "runs" / f"{args.run_id}.json"
    if not run_path.is_file():
        print(f"RUN not found: {run_path}")
        return 2
    state = json.loads(run_path.read_text(encoding="utf-8"))
    contract = state.get("execution_contract") or {}
    if contract.get("protocol_manifest_fingerprint") != manifest.get("fingerprint"):
        print(json.dumps({"status": "REJECTED", "errors": [
            "RUN contract protocol fingerprint is missing or stale; create a new RUN contract"
        ]}, ensure_ascii=False, indent=2))
        return 1
    if state.get("run_id") != args.run_id:
        print("RUN id does not match the trace file")
        return 2
    if args.plan:
        try:
            print(json.dumps(build_attestation_plan(contract, manifest, state.get("protocol_attestations", [])),
                              ensure_ascii=False, indent=2))
        except ValueError as exc:
            print(json.dumps({"status": "REJECTED", "errors": [str(exc)]}, ensure_ascii=False, indent=2))
            return 1
        return 0
    if not args.attestation:
        parser.error("提交校验时需要 attestation.json；预览读取范围请加 --plan")
    attestation = json.loads(Path(args.attestation).read_text(encoding="utf-8"))
    prior_attestations = state.get("protocol_attestations", [])
    result = verdict(attestation, manifest, manifest.get("protocol_root", MANIFEST_DEFAULT.parent),
                     contract, prior_attestations)
    if result["status"] == "PASS":
        required, gate_refs, covered = scoped_protocols(contract, attestation["scope_gate"])
        prior = _valid_prior_attestations(contract, manifest, prior_attestations)
        prior_paths = {path for item in prior for path in item.get("protocol_paths", [])}
        prior_challenges = {challenge for item in prior for challenge in item.get("challenge_ids", [])}
        challenge_ids = _required_challenge_ids(
            contract["task_id"], attestation["scope_gate"], gate_refs, manifest,
            include_common="protocol-version" not in prior_challenges,
        )
        record = {
            "status": "PASS", "attestation_id": attestation["attestation_id"],
            "run_id": contract["run_id"], "task_id": contract["task_id"],
            "contract_id": contract["contract_id"], "manifest_fingerprint": manifest["fingerprint"],
            "scope_gate": attestation["scope_gate"], "covered_step_ids": covered,
            "protocol_paths": sorted(prior_paths | required),
            "challenge_ids": sorted(prior_challenges | challenge_ids),
            "verified_at": attestation["declared_at"],
        }
        state["protocol_attestations"] = [*prior_attestations, record]
        state["protocol_attestation"] = record
        run_state.write_task(run_path, state)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
