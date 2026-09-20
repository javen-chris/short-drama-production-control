"""Audit a finished or paused run: did each step actually invoke its Skill and
read the protocol documents that govern it?

This is the runtime half of protocol compliance. Read attestation proves the
agent read the core protocol *before starting*; this proves every *step* named
the Skill that ran it and the documents it relied on. A run that completed
without those fields is not a compliant run - it is an untraceable one.
"""
from __future__ import annotations

from .orchestrator import plan_steps

# The documents each step is expected to have actually open. Kept explicit so a
# missing read is a named failure, not a vague "did not follow protocol".
# Protocol 3.0 (2026-09-20) added the _v3.0 file-name suffix.
STEP_PROTOCOL_REQUIREMENTS = {
    "short-drama-production-router": ["00_自动化生产唯一入口_v3.0.md", "核心自动化生产包/02_任务路由与Gate_v3.0.md"],
    "short-drama-script-breakdown": ["09_脚本优化与分镜拆解规范_v3.0.md"],
    "short-drama-script-reviewer": ["09_脚本优化与分镜拆解规范_v3.0.md"],
    "short-drama-scene-continuity": ["03_资产与连续性规则_v3.0.md"],
    "short-drama-asset-router": ["核心自动化生产包/03_生产与资产规则_v3.0.md"],
    "short-drama-image-generator": ["16_生图渠道规则_v3.0.md", "14_RH生图渠道与GPT通道现状_v3.0.md"],
    "short-drama-storyboard-planner": ["08_故事本生产与QA规范_v3.0.md", "12_真人短剧Prompt与故事本弹性标准_v3.0.md"],
    "short-drama-prompt-compiler": ["12_真人短剧Prompt与故事本弹性标准_v3.0.md"],
    "short-drama-production-qa": ["04_QA与文件治理_v3.0.md"],
    "runninghub-local-adapter": ["13_模型执行前硬门禁_v3.0.md", "19_视频提交前确认报告与授权范围规则_v3.0.md"],
    "xiaoyunque-local-adapter": ["13_模型执行前硬门禁_v3.0.md", "19_视频提交前确认报告与授权范围规则_v3.0.md"],
    "libtv-local-adapter": ["13_模型执行前硬门禁_v3.0.md", "19_视频提交前确认报告与授权范围规则_v3.0.md"],
}


def _last_completed_event(state: dict, step: str) -> dict | None:
    for event in reversed(state.get("events", [])):
        if event.get("step") == step and event.get("outcome") == "COMPLETED":
            return event
    return None


def _read_paths(event: dict) -> dict[str, str | None]:
    refs: dict[str, str | None] = {}
    for item in event.get("protocol_refs", []) or []:
        if isinstance(item, str):
            refs[item] = None
        elif isinstance(item, dict) and item.get("path"):
            refs[item["path"]] = item.get("sha256")
    return refs


def verify_run_compliance(state: dict, chain: dict | None = None, manifest: dict | None = None) -> dict:
    """Check every completed step for Skill identity, protocol reads, and evidence."""
    errors: list[str] = []
    steps = state.get("pipeline") or plan_steps(chain or {})
    completed = set(state.get("completed_steps", []))

    for step in steps:
        if step not in completed:
            continue
        event = _last_completed_event(state, step)
        if event is None:
            errors.append(f"{step}: marked completed but has no COMPLETED event")
            continue
        if not event.get("skill_id"):
            errors.append(f"{step}: event records no skill_id")
        elif event["skill_id"] != step:
            errors.append(f"{step}: event skill_id is {event['skill_id']}")
        if not event.get("evidence"):
            errors.append(f"{step}: event records no evidence path")
        refs = _read_paths(event)
        required = STEP_PROTOCOL_REQUIREMENTS.get(step, [])
        for path in required:
            if path not in refs:
                errors.append(f"{step}: did not record reading {path}")
        if manifest:
            by_path = {entry["path"]: entry["sha256"] for entry in manifest.get("files", [])}
            for path, digest in refs.items():
                if path in by_path and digest and digest != by_path[path]:
                    errors.append(f"{step}: {path} hash does not match the protocol manifest")

    covered = [s for s in steps if s in completed]
    return {
        "status": "PASS" if not errors else "NON_COMPLIANT",
        "run_id": state.get("run_id"),
        "completed_steps": covered,
        "pending_steps": [s for s in steps if s not in completed],
        "errors": errors,
    }


def compliance_gaps(state: dict, chain: dict | None = None) -> list[str]:
    """Steps that finished but left no trace of what they read."""
    result = verify_run_compliance(state, chain)
    return result["errors"]
