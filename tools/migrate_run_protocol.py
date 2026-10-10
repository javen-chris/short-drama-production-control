"""Migrate an existing RUN contract to the current protocol fingerprint in place.

No production event, budget, approval, task id, or prior attestation is removed.
A fresh scoped attestation is still required before the current stage continues.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from production_control import protocol_fingerprint, protocol_versions, run_index  # noqa: E402


def migrate(project_root: str | Path, run_id: str, *, confirmed_paths: list[str] | None = None,
            confirmation_evidence: str = '', inspect_only: bool = False) -> dict:
    root = Path(project_root)
    run_path = run_index.run_path(root, run_id)
    if not run_path.is_file():
        raise FileNotFoundError(f"RUN not found: {run_path}")
    state = json.loads(run_path.read_text(encoding="utf-8"))
    if state.get("run_id") != run_id:
        raise ValueError("RUN id does not match trace filename")
    contract = state.get("execution_contract")
    if not isinstance(contract, dict):
        raise ValueError("RUN has no execution_contract; migration cannot safely infer scope")
    protocol_root = Path(contract.get("protocol_root") or protocol_fingerprint.DEFAULT_ROOT)
    manifest_path = protocol_fingerprint.manifest_path(protocol_root)
    if not manifest_path.is_file():
        raise FileNotFoundError(f"protocol manifest missing: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    drift = protocol_fingerprint.check(protocol_root, paths=protocol_versions.scoped_paths(contract, current_only=False))
    if drift:
        raise ValueError("current protocol manifest is not valid: " + "; ".join(drift))
    hashes = {entry["path"]: entry["sha256"] for entry in manifest.get("files", [])}
    refreshed = []
    for step in contract.get("steps", []):
        if not step.get("applicable"):
            continue
        for ref in step.get("protocol_refs", []):
            path = ref.get("path", "")
            if path not in hashes:
                raise ValueError(f"applicable step protocol is missing from manifest: {path}")
            if ref.get("sha256") != hashes[path]:
                refreshed.append(path)
    old = contract.get("protocol_manifest_fingerprint", "")
    if old == manifest.get("fingerprint") and not refreshed:
        return {"status": "CURRENT", "run_id": run_id, "fingerprint": old}

    impact = protocol_versions.impact_report(contract, protocol_root, manifest)
    if inspect_only:
        return {"status": "DIFF_ONLY", "run_id": run_id, **impact}
    required = set(impact['confirmation_required_paths'])
    evidence_path = root / confirmation_evidence
    if required and (not required.issubset(set(confirmed_paths or [])) or not confirmation_evidence
                     or not evidence_path.is_file()):
        raise ValueError('PROTOCOL_CHANGE_CONFIRMATION_REQUIRED: inspect --inspect diff, then record confirmed paths '
                         'and existing confirmation evidence; missing: ' + ', '.join(sorted(required)))

    # Validate the full update in memory before writing anything.
    for step in contract.get("steps", []):
        for ref in step.get("protocol_refs", []):
            if ref.get("path") in hashes:
                ref["sha256"] = hashes[ref["path"]]
    record = {
        "from_fingerprint": old,
        "to_fingerprint": manifest["fingerprint"],
        "changed_protocol_paths": sorted(c['path'] for c in impact['changes']),
        "migrated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "current_step_id": contract.get("current_step_id", ""),
        "preserved_event_count": len(state.get("events", [])),
        "preserved_submission_count": sum(1 for e in state.get("events", [])
                                           if e.get("outcome") == "TASK_SUBMITTED"),
        "preserved_attestation_count": len(state.get("protocol_attestations", [])),
        "manifest_path": str(manifest_path),
        "impact_report": impact,
        "confirmed_paths": sorted(confirmed_paths or []),
        "confirmation_evidence": confirmation_evidence,
        "confirmation_evidence_sha256": protocol_fingerprint.sha256_file(evidence_path) if required else None,
    }
    contract["protocol_manifest_fingerprint"] = manifest["fingerprint"]
    contract['protocol_snapshot_hashes'] = hashes
    # Proofs and QA remain historical. Only explicitly affected current proofs
    # are invalidated; no event or paid submission is removed.
    current = state.get('protocol_attestation') or {}
    affected = {c['path'] for c in impact['changes'] if c['scope'] == 'current'}
    if affected.intersection(current.get('protocol_paths', [])):
        state['protocol_attestation'] = {**current, 'status': 'STALE', 'invalidated_paths': sorted(affected)}
    if affected:
        state.setdefault('protocol_invalidations', []).append({
            'paths': sorted(affected), 'at': record['migrated_at'],
            'affected_step_ids': [s['id'] for s in contract.get('steps', [])
                                  if affected.intersection(r['path'] for r in s.get('protocol_refs', []))],
            'paid_task_preserved': contract.get('provider_task_id'),
        })
    state.setdefault("protocol_migrations", []).append(record)
    state["updated_at"] = record["migrated_at"]
    temp = run_path.with_suffix(run_path.suffix + ".migrating")
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(run_path)
    index = run_index.load_index(root)
    run_index.register_run(index, state, make_active=state.get("status") in {
        "RUNNING", "WAITING_APPROVAL", "PAUSED_EXCEPTION", "BLOCKED", "SUBMITTED_IN_PROGRESS"})
    run_index.save_index(root, index)
    return {"status": "MIGRATED", "run_id": run_id, **record}


def main() -> int:
    parser = argparse.ArgumentParser(description="在原 RUN 内迁移协议指纹与步骤协议哈希")
    parser.add_argument("project_root")
    parser.add_argument("--run", required=True)
    parser.add_argument('--inspect', action='store_true', help='Show text diff and scope; do not change RUN')
    parser.add_argument('--confirmed-path', action='append', default=[])
    parser.add_argument('--confirmation-evidence', default='')
    args = parser.parse_args()
    try:
        print(json.dumps(migrate(args.project_root, args.run, confirmed_paths=args.confirmed_path,
                                confirmation_evidence=args.confirmation_evidence,
                                inspect_only=args.inspect), ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError) as exc:
        print(json.dumps({"status": "REJECTED", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
