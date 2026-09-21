"""Start one segment run, so its trace exists before the first step is taken.

Every other tool assumes the trace is already there: append_event records into
it, run_report reads it, the board renders it. Nothing could create one, which
meant starting a new project meant hand-writing Python. Now it does not.

    python tools/start_run.py "<项目目录>" --run RUN-EP05-D2 --segment D2 ^
        --title "D2（除掉令点将）" --series 三国灵玺录 --episode EP05
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

CONSOLE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CONSOLE / "src"))

from production_control import orchestrator  # noqa: E402


def resolve_contract_id(value: str) -> str:
    """A contract id, or a path to a contract file whose id we adopt."""
    if not value:
        return "uncontracted"
    if value.endswith(".json"):
        path = Path(value)
        if not path.is_file():
            raise SystemExit(f"找不到合同文件：{path}")
        document = json.loads(path.read_text(encoding="utf-8"))
        found = document.get("contract_id") or document.get("id")
        if not found:
            raise SystemExit(f"合同文件里没有 contract_id：{path}")
        return str(found)
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="开始一段（一个故事本单元）的运行轨迹")
    parser.add_argument("project_root", help="项目根目录")
    parser.add_argument("--run", required=True, help="run_id，例如 RUN-EP05-D2")
    parser.add_argument("--segment", default="", help="段号，例如 D2（缺省就用 run_id）")
    parser.add_argument("--title", default="", help="给人看的段名，例如 D2（除掉令点将）")
    parser.add_argument("--series", default="", help="剧名")
    parser.add_argument("--episode", default="", help="集号，例如 EP05")
    parser.add_argument("--chain", default=str(CONSOLE / "skills" / "skill-chain.json"),
                        help="技能链声明（默认用仓库自带的 skill-chain.json）")
    parser.add_argument("--contract", default="", help="contract_id，或合同 JSON 的路径")
    args = parser.parse_args(argv)

    chain_path = Path(args.chain)
    if not chain_path.is_file():
        raise SystemExit(f"找不到技能链：{chain_path}")
    chain = json.loads(chain_path.read_text(encoding="utf-8"))
    contract_id = resolve_contract_id(args.contract)

    state = orchestrator.start(
        None,
        chain,
        args.run,
        contract_id,
        project_root=args.project_root,
        segment=args.segment,
        segment_title=args.title,
        series=args.series,
        episode=args.episode,
    )

    root = Path(args.project_root)
    steps = state.get("pipeline") or []
    print()
    print(f"已开始：{args.run}  {args.title or args.segment or ''}".rstrip())
    print(f"  轨迹：{root / 'workflow' / 'runs' / (args.run + '.json')}")
    print(f"  流水线 {len(steps)} 步，当前停止在：{steps[0] if steps else '（空）'}")
    print()
    print("接下来每完成一步就记一次（证据文件要先落盘）：")
    print(f'  python tools\\append_event.py "{root}" ^')
    print(f"    --run {args.run} --step <skill> --protocol <协议文件> \\")
    print("    --evidence <相对项目的文件路径> --outcome COMPLETED")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
