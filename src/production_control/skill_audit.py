"""G5.1: the gate that was missing between G5 and G6.

EP03 produced a batch of unusable video prompts that had never been through a
Skill. Nothing stopped them, because nothing between "a prompt exists in a
file" and "a node gets created" ever asked whether the Skill ran or what it
said. `prompt_linter` only checks that a `skill_id` is present - having an id
is not the same as having run it.

So this module is deliberately stubborn:

- NOT_RUN is not a to-do, it is a block.
- A PASS with no evidence is treated as not run.
- The audit is bound to a prompt version; editing a sentence invalidates it.
- A node may be CREATED on the platform and still not be production-ready.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

AUDITS_DIRNAME = "skill_audits"
CHECKER_VERSION = "1.0.0"

VALID_SKILL_STATUS = {"PASS", "FAIL", "UNCERTAIN", "NOT_RUN"}
BLOCKING_STATUS = {"FAIL", "UNCERTAIN", "NOT_RUN"}

# The minimum structure a Seedance-class video prompt must carry. One missing
# item means the prompt must not be reported as PASS.
REQUIRED_PROMPT_SECTIONS = (
    "mode",                      # I2V / R2V / mixed2video
    "reference_role_map",        # 参考图职责映射
    "primary_intent",            # 一个主意图
    "subject_tags",              # 主体标签
    "single_primary_action",     # 唯一主动作
    "start_state",               # 起始状态
    "timeline",                  # 时间轴
    "end_state",                 # 结束状态
    "primary_camera_move",       # 一个主镜头运动
    "character_action_assignment",  # 角色动作分配
    "physical_outcome",          # 物理动作结果
    "sound",                     # 声音
    "keep",                      # 保持项
    "prohibit",                  # 禁止项
    "asset_role_alignment",      # 资产职责与 Prompt 引用一致
)

ERROR_CODES = (
    "SKILL_NOT_RUN",
    "SKILL_GATE_FAIL",
    "SKILL_EVIDENCE_MISSING",
    "PROMPT_VERSION_MISMATCH",
    "ASSET_GATE_NOT_READY",
    "PLATFORM_NODE_CREATED_BUT_NOT_PRODUCTION_READY",
)


def audits_dir(project_root: str | Path) -> Path:
    return Path(project_root) / "workflow" / AUDITS_DIRNAME


def audit_path(project_root: str | Path, unit_id: str) -> Path:
    return audits_dir(project_root) / f"{unit_id}_skill_audit.json"


def _read_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return document if isinstance(document, dict) else {}


def evaluate(audit: dict) -> dict:
    """Decide the gate from one audit document. Empty audit = never ran."""
    errors: list[str] = []
    codes: list[str] = []
    skills = audit.get("skills") or []

    if not skills:
        codes.append("SKILL_NOT_RUN")
        errors.append("skills 为空：等同于没跑 Skill，不得放行")
    else:
        not_run = [s.get("id", "?") for s in skills if s.get("status") == "NOT_RUN"]
        failed = [s.get("id", "?") for s in skills if s.get("status") == "FAIL"]
        uncertain = [s.get("id", "?") for s in skills if s.get("status") == "UNCERTAIN"]
        evidence_free = [s.get("id", "?") for s in skills
                         if s.get("status") == "PASS" and not str(s.get("evidence", "")).strip()]
        unknown = [s.get("id", "?") for s in skills if s.get("status") not in VALID_SKILL_STATUS]

        if not_run:
            codes.append("SKILL_NOT_RUN")
            errors.append("以下 Skill 未运行：%s（不允许降级，不允许先建节点再补）" % "、".join(not_run))
        if failed:
            codes.append("SKILL_GATE_FAIL")
            errors.append("以下 Skill 判定 FAIL：%s" % "、".join(failed))
        if uncertain:
            codes.append("SKILL_GATE_FAIL")
            errors.append("以下 Skill 判定 UNCERTAIN：%s（不得当作通过）" % "、".join(uncertain))
        if evidence_free:
            codes.append("SKILL_EVIDENCE_MISSING")
            errors.append("以下 Skill 报 PASS 但没有证据：%s（无证据的 PASS 视为未跑）" % "、".join(evidence_free))
        if unknown:
            errors.append("以下 Skill 的 status 不是合法取值：%s" % "、".join(unknown))

    ok = not codes and bool(skills)
    return {
        "unit_id": audit.get("unit_id", ""),
        "model": audit.get("model", ""),
        "prompt_id": audit.get("prompt_id", ""),
        "prompt_version": audit.get("prompt_version", ""),
        "skill_audit_id": audit.get("skill_audit_id", ""),
        "skill_count": len(skills),
        "overall": "PASS" if ok else "SKILL_GATE_BLOCKED",
        "ok": ok,
        "codes": codes,
        "errors": errors,
        "checker_version": CHECKER_VERSION,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }


def check_prompt_sections(prompt: dict | str) -> list[str]:
    """Which of the fifteen minimum sections are missing."""
    if isinstance(prompt, str):
        present = set()
        text = prompt
    else:
        present = {key for key, value in prompt.items() if value not in (None, "", [], {})}
        text = json.dumps(prompt, ensure_ascii=False)
    missing = []
    for section in REQUIRED_PROMPT_SECTIONS:
        if section in present:
            continue
        # A structured dict may be absent while the section is written inline.
        if section.replace("_", "") in text.replace("_", "").lower():
            continue
        missing.append(section)
    return missing


def check_node_binding(audit: dict, node: dict) -> list[str]:
    """The audit must describe the exact prompt the node will run."""
    problems = []
    for field, label in (("prompt_version", "prompt_version"),
                         ("model", "model")):
        wanted = str(audit.get(field, "")).strip()
        actual = str(node.get(field, "")).strip()
        if wanted and actual and wanted != actual:
            problems.append(f"PROMPT_VERSION_MISMATCH: 审计 {label}={wanted!r} 但节点为 {actual!r}")
    audit_mode = str(audit.get("mode", "")).strip()
    node_mode = str(node.get("modeType", "") or node.get("mode", "")).strip()
    if audit_mode and node_mode and audit_mode != node_mode:
        problems.append(f"PROMPT_VERSION_MISMATCH: 审计 mode={audit_mode!r} 但节点 modeType={node_mode!r}")
    return problems


def node_readiness(audit_ok: bool, asset_gate_ok: bool, node: dict, prompt: dict | str) -> dict:
    """CREATED on the platform is not the same as ready to produce.

    MCP returning "operation completed" only sets platform_node_status. It says
    nothing about whether the prompt was ever audited or the assets bound.
    """
    missing_sections = check_prompt_sections(prompt)
    binding = check_node_binding(node.get("audit", {}) or {}, node)
    ready = bool(audit_ok and asset_gate_ok and not missing_sections and not binding)
    codes = []
    if not ready:
        if not audit_ok:
            codes.append("SKILL_NOT_RUN")
        if not asset_gate_ok:
            codes.append("ASSET_GATE_NOT_READY")
        if missing_sections:
            codes.append("SKILL_GATE_FAIL")
        if binding:
            codes.append("PROMPT_VERSION_MISMATCH")
        if node.get("platform_node_status") == "CREATED":
            codes.append("PLATFORM_NODE_CREATED_BUT_NOT_PRODUCTION_READY")
    return {
        "platform_node_status": node.get("platform_node_status", "UNKNOWN"),
        "production_readiness": "PRODUCTION_READY" if ready else "FAIL",
        "ready": ready,
        "missing_prompt_sections": missing_sections,
        "binding_problems": binding,
        "codes": codes,
    }


def load_audits(project_root: str | Path) -> list[dict]:
    folder = audits_dir(project_root)
    if not folder.is_dir():
        return []
    rows = []
    for file in sorted(folder.glob("*_skill_audit.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        verdict = evaluate(_read_json(file))
        verdict["file"] = str(file)
        rows.append(verdict)
    return rows
