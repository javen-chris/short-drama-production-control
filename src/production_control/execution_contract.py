"""Build a per-run execution contract from the canonical Skill registry.

This creates an auditable work order; it does not dispatch an Agent or prove
the identity of a model session.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from . import qa_policy


class ContractError(ValueError):
    """The requested run cannot be turned into a safe execution contract."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_contract(*, chain: dict, project_root: str | Path, run_id: str,
                   task_id: str, segment: str, version: str, execution_model: str,
                   production_level: str, image_assets_required: bool,
                   storyboard_required: bool, provider: str = "",
                   protocol_root: str | Path | None = None) -> dict:
    """Resolve applicable steps and pin their referenced protocol files."""
    required = {
        "project_root": str(project_root), "run_id": run_id, "task_id": task_id,
        "segment": segment, "version": version, "execution_model": execution_model,
    }
    missing = [key for key, value in required.items() if not str(value).strip()]
    if missing:
        raise ContractError("执行合同缺少必填项：" + ", ".join(missing))
    if production_level not in {"L1", "L2"}:
        raise ContractError("production_level 只能是 L1 或 L2")
    route = qa_policy.qa_model_for_execution(execution_model)
    if not route:
        raise ContractError(f"未登记执行模型 {execution_model!r}，拒绝猜测 QA 路由")

    providers = {item.get("provider") for item in chain.get("steps", []) if item.get("alternative_group")}
    if provider and provider not in providers:
        raise ContractError(f"平台 {provider!r} 不在注册表的三选一 adapter 中：{sorted(providers)}")

    root = Path(project_root)
    if not root.is_dir():
        raise ContractError(f"项目目录不存在或不是目录：{root}")
    authority_value = str(protocol_root or chain.get("authority", "")).strip()
    if not authority_value:
        raise ContractError("技能注册表没有权威协议入口路径")
    authority = Path(authority_value).parent
    if not authority.is_dir():
        raise ContractError("找不到权威本地协议目录；请检查注册表 authority 路径")
    steps: list[dict] = []
    seen_ids: set[str] = set()
    for item in chain.get("steps", []):
        step_id, skill = item.get("id"), item.get("skill")
        if not step_id or not skill or step_id in seen_ids:
            raise ContractError("技能注册表存在缺少稳定 ID/Skill 或重复 ID 的步骤")
        seen_ids.add(step_id)
        applicable, reason, mode = True, "本次任务适用", ""
        condition = (item.get("applicability") or {}).get("kind", "")
        if condition == "requires_image_assets" and not image_assets_required:
            applicable, reason = False, "资产路由确认无需新生或返修图片资产"
        if condition == "storyboard_or_key_state":
            mode = ("key_state_only" if production_level == "L1" and not storyboard_required
                    else "full_storyboard")
            reason = ("L1 仅做关键状态规划，不要求完整故事本"
                      if mode == "key_state_only" else "本次制作级别/资产风险要求完整故事本")
        if item.get("alternative_group") == "submit-adapter":
            applicable = bool(provider) and item.get("provider") == provider
            reason = (f"本次选择 {provider}，其余平台不适用" if provider
                      else "本次 RUN 尚未进入平台提交；未选择平台")
        if condition == "generated_video_present" and not provider:
            applicable = False
            reason = "本次 RUN 未进入视频生成；成片 QA 需在有真实成片证据的 RUN 中执行"

        refs = []
        for relative in (item.get("protocol_refs", []) if applicable else []):
            target = authority / relative
            if not target.is_file():
                raise ContractError(f"步骤 {step_id} 引用的协议文件不存在：{target}")
            refs.append({"path": relative, "sha256": sha256_file(target)})
        if applicable and not refs:
            raise ContractError(f"适用步骤 {step_id} 没有登记必读协议文件")

        steps.append({
            "id": step_id, "skill": skill, "gate": item.get("gate", []),
            "name_zh": item.get("name_zh", ""), "applicable": applicable,
            "disposition": "pending" if applicable else "not_applicable",
            "reason": reason, "mode": mode, "protocol_refs": refs,
            "approval": item.get("approval", ""),
            "alternative_group": item.get("alternative_group", ""),
            "provider": item.get("provider", ""),
        })

    applicable_steps = [step for step in steps if step["applicable"]]
    if not applicable_steps:
        raise ContractError("执行合同没有任何适用步骤")
    return {
        "contract_version": "1.0",
        "project_root": str(root.resolve()), "run_id": run_id, "contract_id": task_id,
        "task_id": task_id,
        "protocol_root": str(authority.resolve()),
        "segment": segment, "version": version, "execution_model": execution_model,
        "qa_model": route, "model_identity": "declared_unverified",
        "production_level": production_level,
        "image_assets_required": image_assets_required,
        "storyboard_required": production_level == "L2" or storyboard_required,
        "selected_provider": provider or None,
        "provider_authorized": False,
        "steps": steps,
        "current_step_id": applicable_steps[0]["id"],
        "current_owner": "producer",
        "next_action": f"按 {applicable_steps[0]['id']} {applicable_steps[0]['skill']} 执行并产出证据；由 {route} 独立 QA",
    }


def contract_step(contract: dict, step_id: str) -> dict | None:
    return next((item for item in contract.get("steps", []) if item.get("id") == step_id), None)
