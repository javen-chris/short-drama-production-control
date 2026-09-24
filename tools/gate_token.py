"""Check the pre-node asset gate, and issue the token that proves it passed.

    python tools/gate_token.py <项目目录> --unit A1 --gate G5
    python tools/gate_token.py <项目目录> --unit A1 --gate G5 --issue

Without --issue this only reports. With --issue it writes
workflow/gates/<gate>_<unit>.token.json, and only when the gate really passes:
the declared set in production_contract.json must equal the bound set in
workflow/bound_assets.json, matched on (role, sha256), every item read back.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from production_control.gate_token import evaluate, issue, load_tokens  # noqa: E402


def render(verdict: dict) -> str:
    lines = [
        f"门禁 {verdict['gate']} · 单元 {verdict['unit_id'] or '-'}",
        f"  声明 {verdict['declared_count']} 项 · 已绑定 {verdict['bound_count']} 项",
    ]
    diffs = verdict["diffs"]
    labels = {"missing": "合同声明但平台未绑定",
              "hash_mismatch": "职责对上但文件对不上",
              "unverified": "已上传但未回读确认",
              "undeclared": "绑了合同没声明的东西"}
    for kind in ("missing", "hash_mismatch", "unverified", "undeclared"):
        items = diffs.get(kind) or []
        if not items:
            continue
        lines.append(f"  ✗ {labels[kind]}（{len(items)}）")
        for item in items[:10]:
            lines.append(f"      - {json.dumps(item, ensure_ascii=False)}")
    lines.append("  ✅ 通过：声明集合 == 绑定集合" if verdict["ok"] else "  ❌ 未通过：不得创建视频节点")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="建节点前置门禁：数量与职责的集合比对（20 号协议 §四）")
    parser.add_argument("project", help="项目目录")
    parser.add_argument("--unit", default="", help="生产单元，如 A1")
    parser.add_argument("--gate", default="G5", help="门禁名，默认 G5")
    parser.add_argument("--issue", action="store_true", help="通过时落盘令牌")
    parser.add_argument("--list", action="store_true", help="列出已有令牌及其是否仍有效")
    args = parser.parse_args()

    if args.list:
        rows = load_tokens(args.project)
        if not rows:
            print("（还没有任何门禁令牌）")
            return 0
        for row in rows:
            mark = "✅" if row.get("still_valid") else "❌"
            print(f"{mark} {row.get('gate')}_{row.get('unit_id')} · "
                  f"声明 {row.get('declared_count')} / 绑定 {row.get('bound_count')} · "
                  f"{row.get('evaluated_at', '')[:19]}"
                  + (f" · {row.get('stale_reason','')}" if not row.get("still_valid") else ""))
        return 0

    verdict = evaluate(args.project, args.unit, args.gate)
    print(render(verdict))
    if not args.issue:
        return 0 if verdict["ok"] else 1
    ok, path, verdict = issue(args.project, args.unit, args.gate)
    if ok:
        print(f"令牌已写入：{path}")
        return 0
    print("未通过，不写令牌——没有令牌就不得创建视频节点。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
