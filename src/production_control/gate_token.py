"""Gate tokens: the difference between a gate that is written down and one that holds.

The EP03/A1 incident was not a platform failure. MCP worked, the scene image
uploaded and bound fine. What happened was that nine declared assets became one
bound asset, and nothing stopped it, because the asset check lived in prose at
"before submission" while the damage happened at "before creating the node".

Worse: "do not substitute one image for the rest" is unenforceable prose. Two
images pass it. Four images pass it. The only decidable rule is set equality
against a declared source of truth, and that source already exists:
`production_contract.json` -> `assets[]`, which the schema makes required with
minItems 1.

So a token records one thing: at this moment, the declared asset set and the
platform-bound asset set were equal, matched on (role, sha256), and every bound
item was read back. Nothing here trusts a self-written report; the comparison
is recomputed from the contract and the bound-asset record every time.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

GATES_DIRNAME = "gates"
CONTRACT_NAME = "production_contract.json"
BOUND_NAME = "bound_assets.json"
CHECKER_VERSION = "1.0.0"

# The four ways a declared set and a bound set can disagree.
DIFF_KINDS = ("missing", "hash_mismatch", "unverified", "undeclared")


def gates_dir(project_root: str | Path) -> Path:
    return Path(project_root) / "workflow" / GATES_DIRNAME


def contract_path(project_root: str | Path) -> Path:
    return Path(project_root) / "workflow" / CONTRACT_NAME


def bound_path(project_root: str | Path) -> Path:
    return Path(project_root) / "workflow" / BOUND_NAME


def token_path(project_root: str | Path, gate: str, unit_id: str) -> Path:
    return gates_dir(project_root) / f"{gate}_{unit_id}.token.json"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _read_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return document if isinstance(document, dict) else {}


def declared_assets(contract: dict) -> list[dict]:
    """What the contract says this unit needs. Empty means the gate cannot pass."""
    return [item for item in (contract.get("assets") or []) if isinstance(item, dict)]


def compare(declared: list[dict], bound: list[dict], *, project_root: str | Path | None = None) -> dict:
    """Set equality on (role, sha256) - not 'is the count high enough'."""
    root = Path(project_root) if project_root else None

    def key(item: dict) -> tuple[str, str]:
        return (str(item.get("role", "")).strip(), str(item.get("sha256", "")).strip())

    wanted: dict[tuple[str, str], dict] = {}
    for item in declared:
        sha = str(item.get("sha256", "")).strip()
        if not sha and root and item.get("path"):
            candidate = root / str(item["path"])
            if candidate.is_file():
                sha = sha256_file(candidate)
        wanted[key({"role": item.get("role"), "sha256": sha})] = item

    have: dict[tuple[str, str], dict] = {}
    for item in bound:
        have[key(item)] = item

    missing = [
        {"role": k[0], "sha256": k[1], "path": v.get("path", ""), "purpose": v.get("purpose", "")}
        for k, v in wanted.items() if k not in have
    ]
    undeclared = [
        {"role": k[0], "sha256": k[1], "node_id": v.get("node_id", "")}
        for k, v in have.items() if k not in wanted
    ]
    unverified = [
        {"role": k[0], "sha256": k[1], "node_id": v.get("node_id", "")}
        for k, v in have.items() if k in wanted and not v.get("verified")
    ]
    # role present but a different file: match on role only, report the swap.
    wanted_roles = {k[0] for k in wanted}
    have_roles = {k[0] for k in have}
    hash_mismatch = []
    for role in sorted(wanted_roles & have_roles):
        want_sha = {k[1] for k in wanted if k[0] == role}
        have_sha = {k[1] for k in have if k[0] == role}
        if not (want_sha & have_sha) and role not in {m["role"] for m in missing}:
            hash_mismatch.append({"role": role, "declared": sorted(want_sha), "bound": sorted(have_sha)})

    diffs = {"missing": missing, "hash_mismatch": hash_mismatch,
             "unverified": unverified, "undeclared": undeclared}
    return {
        "ok": not any(diffs.values()) and bool(wanted),
        "declared_count": len(wanted),
        "bound_count": len(have),
        "diffs": diffs,
    }


def evaluate(project_root: str | Path, unit_id: str, gate: str = "G5") -> dict:
    """Recompute the gate from disk. Never trust a previously written verdict."""
    root = Path(project_root)
    contract_path_ = contract_path(root)
    contract = _read_json(contract_path_)
    bound = _read_json(bound_path(root)).get("assets") or []
    declared = declared_assets(contract)
    verdict = compare(declared, bound, project_root=root)

    contract_sha = sha256_file(contract_path_) if contract_path_.is_file() else ""
    return {
        "gate": gate,
        "unit_id": unit_id,
        "ok": verdict["ok"],
        "declared_count": verdict["declared_count"],
        "bound_count": verdict["bound_count"],
        "diffs": verdict["diffs"],
        "contract_sha256": contract_sha,
        "checker_version": CHECKER_VERSION,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }


def issue(project_root: str | Path, unit_id: str, gate: str = "G5") -> tuple[bool, Path | None, dict]:
    """Write the token only if the gate actually passes. Refusing is the point."""
    root = Path(project_root)
    verdict = evaluate(root, unit_id, gate)
    if not verdict["ok"]:
        return False, None, verdict
    target = token_path(root, gate, unit_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(verdict, ensure_ascii=False, indent=2), encoding="utf-8")
    return True, target, verdict


def load_tokens(project_root: str | Path) -> list[dict]:
    """Every token on disk, newest first, each with whether it still holds."""
    folder = gates_dir(project_root)
    if not folder.is_dir():
        return []
    rows = []
    for file in sorted(folder.glob("*.token.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        token = _read_json(file)
        if not token:
            continue
        fresh = evaluate(Path(project_root), token.get("unit_id", ""), token.get("gate", "G5"))
        token["file"] = str(file)
        token["still_valid"] = bool(fresh["ok"]) and (
            fresh["contract_sha256"] == token.get("contract_sha256"))
        token["stale_reason"] = (
            "" if token["still_valid"]
            else ("合同已变更，令牌失效" if fresh["contract_sha256"] != token.get("contract_sha256")
                  else "资产绑定已发生变化，令牌失效")
        )
        rows.append(token)
    return rows


def token_for(project_root: str | Path, unit_id: str, gate: str = "G5") -> dict | None:
    for token in load_tokens(project_root):
        if token.get("unit_id") == unit_id and token.get("gate") == gate:
            return token
    return None
