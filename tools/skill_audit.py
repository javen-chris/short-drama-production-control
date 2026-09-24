"""G5.1 gate: check the Skill audit before a node or a prompt may move.

    python tools/skill_audit.py <项目目录> --unit A1
    python tools/skill_audit.py <项目目录> --list

Reads workflow/skill_audits/<unit>_skill_audit.json and decides SKILL_GATE_PASS
or SKILL_GATE_BLOCKED. NOT_RUN, UNCERTAIN, FAIL and PASS-without-evidence all
block. Nothing here degrades: SKILL_NOT_RUN may not be waived to build first
and audit later.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from production_control import skill_audit  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="G5.1 模型 Skill 审计门（21 号协议）")
    parser.add_argument("project", help="项目目录")
    parser.add_argument("--unit", default="", help="生产单元，如 A1")
    parser.add_argument("--list", action="store_true", help="列出已有审计及其判定")
    args = parser.parse_args()

    if args.list:
        rows = skill_audit.load_audits(args.project)
        if not rows:
            print("（还没有任何 Skill 审计报告）")
            return 1
        for row in rows:
            mark = "✅" if row["ok"] else "❌"
            print(f"{mark} {row.get('unit_id') or '-'} · {row['overall']} · "
                  f"skill {row['skill_count']} 项 · {row.get('prompt_version', '')} · "
                  f"{row.get('evaluated_at', '')[:19]}")
            for error in row["errors"]:
                print(f"      - {error}")
        return 0 if all(r["ok"] for r in rows) else 1

    root = Path(args.project)
    path = skill_audit.audit_path(root, args.unit)
    if not path.is_file():
        print(f"没有找到 Skill 审计报告：{path}")
        print("SKILL_NOT_RUN：不允许降级，不允许先建节点再补 Skill。")
        return 1

    verdict = skill_audit.evaluate(json.loads(path.read_text(encoding="utf-8")))
    print(f"单元 {verdict['unit_id'] or args.unit} · 模型 {verdict['model'] or '-'} · "
          f"Prompt {verdict['prompt_id'] or '-'} ({verdict['prompt_version'] or '-'})")
    print(f"  skill 项数：{verdict['skill_count']}")
    print(f"  判定：{verdict['overall']}")
    for error in verdict["errors"]:
        print(f"    ✗ {error}")
    if not verdict["ok"]:
        print("  禁止：创建视频节点 / 更新 Prompt / 连接参考资产 / 生成提交报告 / 点击生成")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
