"""Fail-closed G5 Skill audit bound to the current prompt and inputs.

Evidence files are execution records, not authenticated identity proofs. This
module verifies their presence, readability, digest, and declared bindings.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

AUDITS_DIRNAME = "skill_audits"
CHECKER_VERSION = "2.0.0"

REQUIRED_SKILLS = {
    "h3": {"h3-prompt-writing"},
    "seedance_2.5": {"seedance-shot-design"},
    "seedance_2.0": {"seedance-20", "seedance-prompt"},
}
SUPPORTED_MODES = {
    "h3": {"T2VA", "I2VA", "FL2VA", "L2VA", "REF2VA"},
    "seedance_2.5": {"T2V", "I2V", "V2V", "R2V", "FLF2V", "STANDARD_GENERATION",
                     "ULTRA_LONG", "EXTENSION", "EDIT", "SPATIAL_VIEWPOINT",
                     "AUDIO_EDIT", "CREATIVE_TRANSFER", "GREEN_SCREEN", "WHITE_MODEL",
                     "SEAMLESS_TRANSITION", "STORYBOARD"},
    "seedance_2.0": {"T2V", "I2V", "V2V", "R2V", "FLF2V"},
}
MODEL_ALIASES = {
    "h3": "h3", "minimax h3": "h3", "mini max h3": "h3", "rh_h3": "h3",
    "seedance 2.5": "seedance_2.5", "seedance_2.5": "seedance_2.5",
    "seedance2.5": "seedance_2.5", "seedance v2.5": "seedance_2.5",
    "seedance 2.0": "seedance_2.0", "seedance_2.0": "seedance_2.0",
    "seedance2.0": "seedance_2.0", "seedance v2.0": "seedance_2.0",
}
VALID_SKILL_STATUS = {"PASS", "FAIL", "UNCERTAIN", "NOT_RUN"}
REQUIRED_PROMPT_SECTIONS = (
    "mode", "reference_role_map", "primary_intent", "subject_tags",
    "single_primary_action", "start_state", "timeline", "end_state",
    "primary_camera_move", "character_action_assignment", "physical_outcome",
    "sound", "keep", "prohibit", "asset_role_alignment",
)

ERROR_CODES = (
    "SKILL_NOT_RUN", "SKILL_STATUS_INVALID", "SKILL_GATE_FAIL",
    "SKILL_EVIDENCE_MISSING", "SKILL_EVIDENCE_INVALID", "SKILL_MODEL_UNKNOWN",
    "SKILL_MODEL_MISMATCH", "SKILL_REQUIRED_MISSING", "SKILL_INPUT_MISMATCH",
    "PROMPT_CONTENT_MISMATCH", "INDEPENDENT_QA_REQUIRED", "ASSET_GATE_NOT_READY",
    "PLATFORM_NODE_CREATED_BUT_NOT_PRODUCTION_READY",
)


def audits_dir(project_root: str | Path) -> Path:
    return Path(project_root) / "workflow" / AUDITS_DIRNAME


def audit_path(project_root: str | Path, unit_id: str) -> Path:
    return audits_dir(project_root) / f"{unit_id}_skill_audit.json"


def load_audit(project_root: str | Path, unit_id: str) -> dict:
    """Read one audit record; malformed or missing records fail closed downstream."""
    return _read_json(audit_path(project_root, unit_id))


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _canonical_model(value: object) -> str:
    name = re.sub(r"\s+", " ", str(value or "").strip().lower())
    return MODEL_ALIASES.get(name, "")


def _safe_file(root: Path, relative: object) -> Path | None:
    text = str(relative or "").strip()
    if not text:
        return None
    candidate = Path(text)
    if candidate.is_absolute():
        return None
    resolved_root = root.resolve()
    try:
        resolved = (root / candidate).resolve(strict=True)
        resolved.relative_to(resolved_root)
    except (OSError, ValueError):
        return None
    return resolved if resolved.is_file() else None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _problem(errors: list[str], codes: list[str], code: str, message: str) -> None:
    codes.append(code)
    errors.append(message)


def _verify_evidence(root: Path, audit: dict, skill: dict,
                     errors: list[str], codes: list[str]) -> None:
    ref = skill.get("evidence")
    if not isinstance(ref, dict) or not ref.get("path") or not ref.get("sha256"):
        _problem(errors, codes, "SKILL_EVIDENCE_MISSING",
                 f"{skill.get('id', '?')} 缺少可读取的证据文件路径或 SHA-256")
        return
    path = _safe_file(root, ref.get("path"))
    if path is None:
        _problem(errors, codes, "SKILL_EVIDENCE_INVALID",
                 f"{skill.get('id', '?')} 证据文件不存在、不可读或越出项目目录")
        return
    try:
        actual_digest = _sha256(path)
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        _problem(errors, codes, "SKILL_EVIDENCE_INVALID",
                 f"{skill.get('id', '?')} 证据文件不可读取或不是有效 JSON")
        return
    if actual_digest.lower() != str(ref.get("sha256", "")).lower():
        _problem(errors, codes, "SKILL_EVIDENCE_INVALID",
                 f"{skill.get('id', '?')} 证据文件哈希不匹配")
        return
    if not isinstance(record, dict) or record.get("status") != "PASS":
        _problem(errors, codes, "SKILL_EVIDENCE_INVALID",
                 f"{skill.get('id', '?')} 证据记录没有 PASS 执行结果")
        return
    expected = {
        "unit_id": audit.get("unit_id"), "skill_id": skill.get("id"),
        "model": audit.get("model"), "model_version": audit.get("model_version"),
        "mode": audit.get("mode"), "prompt_sha256": audit.get("prompt_sha256"),
        "input_hashes": audit.get("input_hashes"),
    }
    mismatches = [key for key, value in expected.items() if record.get(key) != value]
    if mismatches:
        _problem(errors, codes, "SKILL_EVIDENCE_INVALID",
                 f"{skill.get('id', '?')} 执行证据未绑定当前单元/Prompt/输入：{', '.join(mismatches)}")


def evaluate(audit: dict, project_root: str | Path | None = None,
             expected_unit_id: str | None = None) -> dict:
    """Evaluate an audit document; PASS is possible only with verified bindings."""
    errors: list[str] = []
    codes: list[str] = []
    if not isinstance(audit, dict):
        audit = {}
        _problem(errors, codes, "SKILL_STATUS_INVALID", "审计文档结构无效")
    if expected_unit_id is not None and audit.get("unit_id") != expected_unit_id:
        _problem(errors, codes, "SKILL_INPUT_MISMATCH",
                 f"审计生产单元 {audit.get('unit_id')!r} 与当前单元 {expected_unit_id!r} 不一致")
    raw_skills = audit.get("skills")
    skills = raw_skills if isinstance(raw_skills, list) else []
    if audit.get("overall") != "PASS":
        _problem(errors, codes, "SKILL_GATE_FAIL",
                 f"审计声明 overall={audit.get('overall')!r}，必须精确为 PASS")
    if not skills:
        _problem(errors, codes, "SKILL_NOT_RUN", "skills 清单为空或格式无效：不得放行")
    for entry in skills:
        if not isinstance(entry, dict):
            _problem(errors, codes, "SKILL_STATUS_INVALID", "Skill 条目不是对象，缺少合法 status")
            continue
        sid = str(entry.get("id") or "?")
        status = entry.get("status")
        if not isinstance(status, str) or status not in VALID_SKILL_STATUS:
            _problem(errors, codes, "SKILL_STATUS_INVALID",
                     f"{sid} 的 status 缺失或非法：{status!r}")
        elif status == "NOT_RUN":
            _problem(errors, codes, "SKILL_NOT_RUN", f"{sid} 尚未执行")
        elif status in {"FAIL", "UNCERTAIN"}:
            _problem(errors, codes, "SKILL_GATE_FAIL", f"{sid} 状态为 {status}，不得通过")
        elif status == "PASS":
            if project_root is None:
                _problem(errors, codes, "SKILL_EVIDENCE_INVALID", f"{sid} 未提供项目根目录，无法核验证据")
            else:
                _verify_evidence(Path(project_root), audit, entry, errors, codes)

    if audit.get("errors"):
        for item in audit["errors"] if isinstance(audit["errors"], list) else [audit["errors"]]:
            errors.append(str(item))
            codes.append("SKILL_GATE_FAIL")
    if audit.get("codes"):
        for code in audit["codes"] if isinstance(audit["codes"], list) else [audit["codes"]]:
            codes.append(str(code))
            errors.append(f"输入审计声明了阻断码：{code}")

    root = Path(project_root) if project_root is not None else None
    model = audit.get("model", "")
    model_key = _canonical_model(model)
    required = REQUIRED_SKILLS.get(model_key)
    if not required:
        _problem(errors, codes, "SKILL_MODEL_UNKNOWN", f"模型未登记或别名冲突，拒绝猜测放行：{model!r}")
    else:
        contract_path = _safe_file(root, audit.get("contract_path")) if root else None
        if contract_path is None:
            _problem(errors, codes, "SKILL_MODEL_MISMATCH", "缺少当前合同文件或合同路径不可核验")
        else:
            contract = _read_json(contract_path)
            contract_model = _canonical_model(contract.get("model"))
            if (contract.get("unit_id") != audit.get("unit_id")
                    or contract_model != model_key
                    or str(contract.get("model_version", "")) != str(audit.get("model_version", ""))):
                _problem(errors, codes, "SKILL_MODEL_MISMATCH", "审计模型/版本/单元与当前合同不一致")
        observed = {str(s.get("id", "")) for s in skills if isinstance(s, dict)}
        missing = required - observed
        if missing:
            _problem(errors, codes, "SKILL_REQUIRED_MISSING",
                     "缺少模型匹配的 Prompt Skill：" + ", ".join(sorted(missing)))
        foreign = {
            "h3": observed & {"seedance-shot-design", "seedance-20", "seedance-prompt"},
            "seedance_2.5": observed & {"h3-prompt-writing", "seedance-20", "seedance-prompt"},
            "seedance_2.0": observed & {"h3-prompt-writing", "seedance-shot-design"},
        }[model_key]
        if foreign:
            _problem(errors, codes, "SKILL_MODEL_MISMATCH",
                     f"审计包含其他模型专用 Skill：{', '.join(sorted(foreign))}")
        mode = re.sub(r"[\s-]+", "_", str(audit.get("mode", "")).strip()).upper()
        if mode not in SUPPORTED_MODES[model_key]:
            _problem(errors, codes, "SKILL_INPUT_MISMATCH",
                     f"输入模式 {audit.get('mode')!r} 与模型 {model!r} 的已登记模式不匹配")

    if root is None:
        _problem(errors, codes, "SKILL_INPUT_MISMATCH", "未提供项目根目录，无法绑定当前输入")
    else:
        prompt_path = _safe_file(root, audit.get("prompt_path"))
        if prompt_path is None:
            _problem(errors, codes, "PROMPT_CONTENT_MISMATCH", "Prompt 文件不存在、不可读或路径越界")
        else:
            try:
                prompt_bytes = prompt_path.read_bytes()
                if _sha256(prompt_path) != str(audit.get("prompt_sha256", "")).lower():
                    _problem(errors, codes, "PROMPT_CONTENT_MISMATCH", "Prompt 内容哈希不匹配；仅改版本名不能复用审计")
                prompt_text = prompt_bytes.decode("utf-8")
                if prompt_path.suffix.lower() == ".json":
                    prompt_doc = json.loads(prompt_text)
                    if (not isinstance(prompt_doc, dict)
                            or prompt_doc.get("unit_id") != audit.get("unit_id")
                            or prompt_doc.get("mode") != audit.get("mode")):
                        _problem(errors, codes, "SKILL_INPUT_MISMATCH", "JSON Prompt 单元或输入模式与审计不一致")
            except (OSError, UnicodeError, json.JSONDecodeError):
                _problem(errors, codes, "SKILL_INPUT_MISMATCH", "Prompt 内容不可读或 JSON Prompt 格式无效")
        input_hashes = audit.get("input_hashes")
        if not isinstance(input_hashes, dict) or not input_hashes:
            _problem(errors, codes, "SKILL_INPUT_MISMATCH", "未记录任何相关输入文件哈希")
        else:
            for relpath, wanted_hash in input_hashes.items():
                input_file = _safe_file(root, relpath)
                if input_file is None or _sha256(input_file).lower() != str(wanted_hash).lower():
                    _problem(errors, codes, "SKILL_INPUT_MISMATCH", f"输入不存在/不可读/哈希变化：{relpath}")

    ok = bool(skills) and not errors and not codes and all(
        isinstance(s, dict) and s.get("status") == "PASS" for s in skills
    )
    return {
        "unit_id": audit.get("unit_id", ""), "model": model,
        "prompt_id": audit.get("prompt_id", ""), "prompt_version": audit.get("prompt_version", ""),
        "skill_audit_id": audit.get("skill_audit_id", ""), "skill_count": len(skills),
        "overall": "PASS" if ok else "SKILL_GATE_BLOCKED", "ok": ok,
        "codes": list(dict.fromkeys(codes)), "errors": errors,
        "checker_version": CHECKER_VERSION, "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }


def check_prompt_sections(prompt: dict | str, model: str = "") -> list[str]:
    model_key = _canonical_model(model) if model else ""
    if model_key == "h3":
        # H3 has its own T2VA/I2VA/FL2VA/L2VA/Ref2VA prompt contract.
        return []
    if model and model_key not in {"seedance_2.0", "seedance_2.5"}:
        return ["unsupported_model"]
    present = set(prompt) if isinstance(prompt, dict) else set()
    text = prompt if isinstance(prompt, str) else json.dumps(prompt, ensure_ascii=False)
    return [section for section in REQUIRED_PROMPT_SECTIONS
            if section not in present and section.replace("_", "") not in text.replace("_", "").lower()]


def check_node_binding(audit: dict, node: dict) -> list[str]:
    problems = []
    for field in ("prompt_version", "model", "mode"):
        wanted = str(audit.get(field, "")).strip()
        actual = str(node.get(field, node.get("modeType", "") if field == "mode" else "")).strip()
        matches = (_canonical_model(wanted) == _canonical_model(actual) if field == "model"
                   else wanted.casefold() == actual.casefold())
        if not wanted or not actual or not matches:
            problems.append(f"PROMPT_CONTENT_MISMATCH: 节点缺少或不匹配 {field}（审计={wanted or '缺失'}，节点={actual or '缺失'}）")
    wanted_version = str(audit.get("model_version", "")).strip()
    actual_version = str(node.get("model_version", "")).strip()
    if wanted_version and wanted_version != actual_version:
        problems.append(f"PROMPT_CONTENT_MISMATCH: 节点缺少或不匹配 model_version（审计={wanted_version}，节点={actual_version or '缺失'}）")
    return problems


def _audit_verdict_ok(verdict: object) -> bool:
    return (isinstance(verdict, dict) and verdict.get("ok") is True
            and verdict.get("overall") == "PASS"
            and not verdict.get("errors") and not verdict.get("codes"))


def node_readiness(audit_verdict: dict, qa_verdict: dict, asset_gate_ok: bool,
                   node: dict, prompt: dict | str) -> dict:
    """Require independent QA separately; Skill execution cannot stand in for it."""
    audit_ok = _audit_verdict_ok(audit_verdict)
    qa_ok = (isinstance(qa_verdict, dict) and qa_verdict.get("overall") == "PASS"
             and not qa_verdict.get("errors") and not qa_verdict.get("codes"))
    bound_model = str((audit_verdict or {}).get("model", "")) if isinstance(audit_verdict, dict) else ""
    missing_sections = check_prompt_sections(prompt, bound_model)
    binding = check_node_binding(node.get("audit", {}) or {}, node)
    ready = bool(audit_ok and qa_ok and asset_gate_ok and not missing_sections and not binding)
    codes = []
    if not ready:
        if not audit_ok:
            codes.extend(audit_verdict.get("codes", []) if isinstance(audit_verdict, dict) else ["SKILL_GATE_FAIL"])
            if not codes:
                codes.append("SKILL_GATE_FAIL")
        if not qa_ok:
            codes.append("INDEPENDENT_QA_REQUIRED")
        if not asset_gate_ok:
            codes.append("ASSET_GATE_NOT_READY")
        if missing_sections:
            codes.append("SKILL_GATE_FAIL")
        if binding:
            codes.append("SKILL_MODEL_MISMATCH")
        if node.get("platform_node_status") == "CREATED":
            codes.append("PLATFORM_NODE_CREATED_BUT_NOT_PRODUCTION_READY")
    return {"platform_node_status": node.get("platform_node_status", "UNKNOWN"),
            "production_readiness": "PRODUCTION_READY" if ready else "FAIL", "ready": ready,
            "missing_prompt_sections": missing_sections, "binding_problems": binding,
            "codes": list(dict.fromkeys(codes))}


def load_audits(project_root: str | Path) -> list[dict]:
    folder = audits_dir(project_root)
    if not folder.is_dir():
        return []
    rows = []
    for file in sorted(folder.glob("*_skill_audit.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        verdict = evaluate(_read_json(file), project_root, file.name.removesuffix("_skill_audit.json"))
        verdict["file"] = str(file)
        rows.append(verdict)
    return rows
