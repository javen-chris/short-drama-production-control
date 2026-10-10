"""Record an explicit user authorization for the one paid G6 submission.

The CLI does not authenticate who typed the statement; it binds the statement,
its evidence file hash, selected provider, RUN and contract in an append-only
authorization record for audit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from production_control import run_index, run_state, step_registry  # noqa: E402


def authorize(project_root: str | Path, run_id: str, evidence: str, statement: str) -> dict:
    root = Path(project_root)
    path = run_index.run_path(root, run_id)
    if not path.is_file():
        raise FileNotFoundError(f"RUN not found: {path}")
    state = run_state.read_task(path)
    contract = state.get("execution_contract") or {}
    submit_step = step_registry.by_id("S11")
    evidence_path = root / evidence
    if not evidence_path.is_file():
        raise FileNotFoundError(f"authorization evidence file not found: {evidence_path}")
    if not statement.strip():
        raise ValueError("授权原句不能为空")
    if not submit_step or contract.get("current_step_id") != submit_step.id:
        raise ValueError("当前合同未处于 G6-S11，拒绝预先或跨步骤写入提交授权")
    if contract.get("current_owner") != "user":
        raise ValueError("合同没有等待用户授权；拒绝写入越权授权")
    if not contract.get("video_submission_requested") or not contract.get("selected_provider"):
        raise ValueError("合同不是已选择唯一平台的视频生成目标")
    if contract.get("provider_task_id") or contract.get('submission_attempts_used', 0) or int(contract.get("submission_count") or 0) >= int(contract.get("max_submissions") or 1):
        raise ValueError("本合同已提交或提交额度已用尽；不能再次授权提交")
    if contract.get("provider_authorized"):
        raise ValueError("本 RUN 已记录提交授权；不接受重复授权记录")
    digest = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    record = {
        "scope": "single_video_submission", "provider": contract["selected_provider"],
        "authorized_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "statement": statement.strip(), "evidence": evidence.replace("\\", "/"),
        "evidence_sha256": digest, "max_submissions": 1,
        "run_id": run_id, "contract_id": contract.get("contract_id", ""),
        "authentication": "声明与证据绑定；CLI 不认证当前会话身份",
    }
    contract["submission_authorization"] = record
    contract["provider_authorized"] = True
    contract["current_owner"] = "executor"
    contract["next_action"] = "只允许按授权平台提交一次并记录真实 Task ID"
    state.setdefault("submission_authorizations", []).append(record)
    state["updated_at"] = record["authorized_at"]
    run_state.write_task(path, state)
    index = run_index.load_index(root)
    run_index.register_run(index, state, make_active=True)
    run_index.save_index(root, index)
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description="记录当前用户对 G6-S11 单次提交的明确授权")
    parser.add_argument("project_root")
    parser.add_argument("--run", required=True)
    parser.add_argument("--statement", required=True, help="本次授权的原句或精确摘要")
    parser.add_argument("--evidence", required=True, help="授权证据文件，相对项目根目录")
    args = parser.parse_args()
    try:
        print(json.dumps(authorize(args.project_root, args.run, args.evidence, args.statement), ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, PermissionError) as exc:
        print(f"授权记录失败：{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
