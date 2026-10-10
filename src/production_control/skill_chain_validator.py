"""Validate that the source-controlled Skill chain is complete and ordered.

This used to carry a hardcoded set of the twelve required Skill names, which
meant the very list the chain declares existed twice and could disagree with
itself. The check is now structural - unique ids, every Gate covered, a QA step
present - so it verifies the shape of the chain rather than re-asserting names
that are already written down in the same file.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILLS = ROOT / "skills"

#: G0 is non-blocking project intake; production ends at G6 task monitoring.
REQUIRED_GATES = ("G0", "G1", "G2", "G3", "G4", "G5", "G6")


def validate_chain(path: Path = SKILLS / "skill-chain.json") -> list[str]:
    errors: list[str] = []
    data = json.loads(path.read_text(encoding="utf-8"))
    available: set[str] = set()
    declared: set[str] = set()
    for skill_file in SKILLS.glob("*/SKILL.md"):
        lines = skill_file.read_text(encoding="utf-8").splitlines()
        names = [line.split(":", 1)[1].strip() for line in lines[:8] if line.startswith("name:")]
        if len(names) != 1:
            errors.append(f"{skill_file.parent.name}: expected one frontmatter name")
            continue
        if names[0] != skill_file.parent.name:
            errors.append(f"{skill_file.parent.name}: frontmatter name is {names[0]}")
        available.add(names[0])

    seen_ids: dict[str, str] = {}
    gates: set[str] = set()
    modes: list[str] = []
    for step in data.get("steps", []):
        name = step.get("skill", "")
        declared.add(name)
        if name not in available:
            errors.append(f"missing Skill: {name}")

        step_id = (step.get("id") or "").strip()
        if not step_id:
            errors.append(f"{name}: no id - the id is the join key, it cannot be blank")
        elif step_id in seen_ids:
            errors.append(f"{step_id}: duplicate id, also used by {seen_ids[step_id]}")
        else:
            seen_ids[step_id] = name
        if not step.get("gate"):
            errors.append(f"{name}: declares no Gate")
        for provider, refs in (step.get("provider_protocol_refs") or {}).items():
            if provider not in {"runninghub", "xiaoyunque", "libtv"}:
                errors.append(f"{name}: unknown provider_protocol_refs key {provider}")
            if not isinstance(refs, list) or not all(isinstance(ref, str) and ref for ref in refs):
                errors.append(f"{name}: provider protocol refs must be non-empty path lists")
        gates.update(step.get("gate", []) or [])
        if step.get("mode"):
            modes.append(step["mode"])

        for dependency in step.get("after", []):
            if dependency not in declared:
                errors.append(f"{name}: dependency not declared earlier: {dependency}")
        after_any = step.get("after_any", [])
        if after_any and not any(dependency in declared for dependency in after_any):
            errors.append(f"{name}: no after_any dependency declared earlier")
        for dependency in after_any:
            if dependency not in available:
                errors.append(f"{name}: missing after_any Skill: {dependency}")

    check_ids: set[str] = set()
    activity_owner: dict[str, str] = {}
    for check in data.get("gate_checks", []) or []:
        check_id = check.get("id", "")
        if not check_id or check_id in check_ids:
            errors.append(f"duplicate or missing Gate check id: {check_id}")
        check_ids.add(check_id)
        if check.get("gate") not in {"G1", "G2", "G3", "G4", "G5", "G6"}:
            errors.append(f"{check_id}: invalid Gate")
        if check.get("kind") not in {"required", "rework", "exception", "change"}:
            errors.append(f"{check_id}: invalid kind")
        for activity in check.get("activity_names", []) or []:
            if activity in activity_owner:
                errors.append(f"{activity}: duplicate activity mapping in {activity_owner[activity]} and {check_id}")
            activity_owner[activity] = check_id

    missing_gates = [g for g in REQUIRED_GATES if g not in gates]
    errors.extend(f"no step declares Gate {g}" for g in missing_gates)
    if "pre_generation" not in modes:
        errors.append("no pre-generation QA step declared: G5 must have an independent review")
    if "post_generation" in modes:
        errors.append("post-generation QA is not part of the production chain")
    for step in data.get("steps", []):
        display_id = step.get("display_id", "")
        if not display_id.startswith("G") or "-S" not in display_id:
            errors.append(f"{step.get('id')}: missing display_id in Gx-Snn format")
    return errors


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else SKILLS / "skill-chain.json"
    errors = validate_chain(path)
    print(json.dumps({"status": "PASS" if not errors else "FAIL", "errors": errors}, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
