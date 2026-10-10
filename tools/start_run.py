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

from production_control import execution_contract, orchestrator, final_submission, run_index  # noqa: E402


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
    parser.add_argument("--task-id", required=True, help="本次生产任务 ID")
    parser.add_argument("--version", required=True, help="当前待执行版本，例如 v1")
    parser.add_argument("--execution-model", required=True,
                        help="执行模型声明；不代表已认证的真实会话身份")
    parser.add_argument("--production-level", required=True, choices=["L1", "L2"])
    parser.add_argument("--image-assets-required", action=argparse.BooleanOptionalAction, required=True,
                        help="本次是否需要新生/修复图片资产；未使用就传 --no-image-assets-required")
    parser.add_argument("--storyboard-required", action=argparse.BooleanOptionalAction, required=True,
                        help="本次是否需要完整故事本；L1 无需时传 --no-storyboard-required")
    parser.add_argument("--provider", choices=["runninghub", "xiaoyunque", "libtv"], default="",
                        help="可选：选定一个 G6 平台；不传表示当前 RUN 未进入平台提交")
    parser.add_argument("--goal", choices=["prompt", "video"], default="prompt",
                        help="prompt 任务止于 G5；video 任务必须选定平台并规划 G6-S10..S12")
    parser.add_argument("--target-mode", action="store_true",
                        help="目标模式任务：加入目标模式专属协议读取范围")
    parser.add_argument('--confirmed-assets', default='', help='已确认资产清单 JSON；建卡同时保存内容寻址快照')
    args = parser.parse_args(argv)

    chain_path = Path(args.chain)
    if not chain_path.is_file():
        raise SystemExit(f"找不到技能链：{chain_path}")
    chain = json.loads(chain_path.read_text(encoding="utf-8"))
    contract_id = resolve_contract_id(args.contract) if args.contract else args.task_id
    try:
        contract = execution_contract.build_contract(
            chain=chain, project_root=args.project_root, run_id=args.run,
            task_id=args.task_id, segment=args.segment or args.run,
            version=args.version, execution_model=args.execution_model,
            production_level=args.production_level,
            image_assets_required=args.image_assets_required,
            storyboard_required=args.storyboard_required, provider=args.provider,
            target_mode=args.target_mode,
            video_submission_requested=(args.goal == "video"),
        )
    except execution_contract.ContractError as exc:
        raise SystemExit(f"无法建立执行合同：{exc}") from exc
    contract["contract_id"] = contract_id
    if args.confirmed_assets:
        root = Path(args.project_root).resolve()
        if run_index.run_path(root, args.run).exists():
            raise SystemExit('RUN_ALREADY_EXISTS: restore existing RUN; do not recreate asset versions')
        manifest = json.loads(Path(args.confirmed_assets).read_text(encoding='utf-8'))
        contract['confirmed_asset_snapshots'] = final_submission.freeze_assets(
            manifest, root / 'workflow' / 'asset_snapshots' / args.run, [root])

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
        contract=contract,
    )

    root = Path(args.project_root)
    steps = state.get("pipeline") or []
    print()
    print(f"已开始：{args.run}  {args.title or args.segment or ''}".rstrip())
    print(f"  轨迹：{root / 'workflow' / 'runs' / (args.run + '.json')}")
    applicable = sum(1 for item in contract["steps"] if item["applicable"])
    not_applicable = len(contract["steps"]) - applicable
    print(f"  执行合同：{args.task_id} · {args.version} · 执行模型声明 {args.execution_model} "
          f"→ QA 路由 {contract['qa_model']}（会话身份未认证）")
    print(f"  本次适用 {applicable} 个注册步骤，不适用 {not_applicable} 个；平台提交授权：未授予")
    print(f"  流水线 {len(steps)} 个不同 Skill，当前停止在：{steps[0] if steps else '（空）'}")
    for item in contract["steps"]:
        if item["applicable"]:
            print(f"    {item['id']} {item['skill']}：适用")
        else:
            print(f"    {item['id']} {item['skill']}：本次不适用（{item['reason']}）")
    print()
    print("执行清单已写入 RUN 轨迹。当前控制台不会自动调用 Hermes/Codex Skill；")
    print(f"  先查看本 Gate 的精确读取清单：python tools\\protocol_attestation.py --plan "
          f"--project-root \"{root}\" --run-id {args.run}")
    print(f"  阅读后提交证明：python tools\\protocol_attestation.py <证明.json> "
          f"--project-root \"{root}\" --run-id {args.run}")
    print("  证明 PASS 后才允许该 Gate 的正式事件写入；进入新 Gate 后按新范围重新证明。")
    print("执行 Agent 按合同完成产物后，由路由 QA GPT 审核并写入轨迹。")
    print("每个适用步骤完成后，证据文件要先落盘：")
    print(f'  python tools\\append_event.py "{root}" ^')
    print(f"    --run {args.run} --step <skill> --protocol <协议文件> \\")
    print("    --evidence <相对项目的文件路径> --outcome COMPLETED")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
