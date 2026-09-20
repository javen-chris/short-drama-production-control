"""Validate that the source-controlled Skill chain is complete and ordered."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILLS = ROOT / "skills"


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

    for step in data.get("steps", []):
        name = step.get("skill", "")
        declared.add(name)
        if name not in available:
            errors.append(f"missing Skill: {name}")
        for dependency in step.get("after", []):
            if dependency not in declared:
                errors.append(f"{name}: dependency not declared earlier: {dependency}")
        after_any = step.get("after_any", [])
        if after_any and not any(dependency in declared for dependency in after_any):
            errors.append(f"{name}: no after_any dependency declared earlier")
        for dependency in after_any:
            if dependency not in available:
                errors.append(f"{name}: missing after_any Skill: {dependency}")

    required = {
        "short-drama-production-router", "short-drama-script-breakdown",
        "short-drama-script-reviewer", "short-drama-scene-continuity",
        "short-drama-asset-router", "short-drama-image-generator", "short-drama-storyboard-planner",
        "short-drama-prompt-compiler", "short-drama-production-qa",
        "runninghub-local-adapter", "xiaoyunque-local-adapter",
        "libtv-local-adapter",
    }
    errors.extend(f"undeclared required Skill: {name}" for name in sorted(required - declared))
    return errors


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else SKILLS / "skill-chain.json"
    errors = validate_chain(path)
    print(json.dumps({"status": "PASS" if not errors else "FAIL", "errors": errors}, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
