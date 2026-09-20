"""Turn a run_state.json into something a human can actually read.

Two outputs from the same data:

- text: a plain summary for a terminal or for an agent to paste into chat
- html: a self-contained page (no external assets) showing, step by step, what
  ran, which Skill it was, which protocol documents it claimed to read, which of
  those were required, where the evidence is, and where it stopped.

The point is to answer "what did the model actually do at each step" without
digging through raw logs.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from html import escape
from pathlib import Path

from .run_compliance import STEP_PROTOCOL_REQUIREMENTS, verify_run_compliance

OUTCOME_LABELS = {
    "COMPLETED": "已完成",
    "WAITING_APPROVAL": "等待你批准",
    "PAUSED_EXCEPTION": "已挂起（异常）",
    "BLOCKED": "已阻断",
    "FAILED": "失败",
}


def _events_by_step(state: dict) -> dict[str, dict]:
    latest: dict[str, dict] = {}
    for event in state.get("events", []) or []:
        step = event.get("step")
        if step:
            latest[step] = event
    return latest


def _ref_map(event: dict) -> dict[str, str | None]:
    refs: dict[str, str | None] = {}
    for item in event.get("protocol_refs", []) or []:
        if isinstance(item, str):
            refs[item] = None
        elif isinstance(item, dict) and item.get("path"):
            refs[item["path"]] = item.get("sha256")
    return refs


def summarize(state: dict, chain: dict | None = None, manifest: dict | None = None) -> dict:
    """Build the intermediate structure both renderers consume."""
    steps = state.get("pipeline") or []
    completed = set(state.get("completed_steps", []) or [])
    events = _events_by_step(state)

    rendered = []
    for step in steps:
        event = events.get(step, {})
        outcome = event.get("outcome", "")
        refs = _ref_map(event)
        required = STEP_PROTOCOL_REQUIREMENTS.get(step, [])
        started = bool(event)
        reads = []
        for path in sorted(set(list(refs.keys()) + required)):
            if path in refs:
                status = "read"
            elif step in completed and path in required:
                # Only a finished step can be in violation of a required read.
                status = "missing"
            elif step in completed:
                status = "unrecorded"
            else:
                status = "pending"
            reads.append(
                {
                    "path": path,
                    "required": path in required,
                    "present": path in refs,
                    "status": status,
                    "sha256": refs.get(path),
                }
            )
        rendered.append(
            {
                "step": step,
                "outcome": outcome,
                "state_label": OUTCOME_LABELS.get(outcome, "未开始" if step not in completed else "已完成"),
                "at": event.get("at", ""),
                "skill_id": event.get("skill_id", ""),
                "validator": event.get("validator", ""),
                "attestation_id": event.get("attestation_id", ""),
                "evidence": event.get("evidence", ""),
                "reason": event.get("reason", ""),
                "reads": reads,
                "missing_required": [r["path"] for r in reads if r["status"] == "missing"],
                "done": step in completed,
                "started": started,
            }
        )

    compliance = verify_run_compliance(state, chain, manifest)
    return {
        "run_id": state.get("run_id", ""),
        "contract_id": state.get("contract_id", ""),
        "status": state.get("status", ""),
        "pending_decision": state.get("pending_decision", ""),
        "current_step": state.get("current_step", ""),
        "progress": {"completed": len(completed & set(steps)), "total": len(steps)},
        "steps": rendered,
        "pending": [s for s in steps if s not in completed],
        "compliance": compliance,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def render_text(summary: dict) -> str:
    lines: list[str] = []
    lines.append(f"运行 {summary['run_id']}（合同 {summary['contract_id']}）")
    lines.append(f"状态：{summary['status']}    进度：{summary['progress']['completed']}/{summary['progress']['total']} 步")
    if summary.get("pending_decision"):
        lines.append(f"等待决定：{summary['pending_decision']}")
    lines.append("")
    lines.append("步骤明细：")
    for item in summary["steps"]:
        mark = "✓" if item["done"] else "·"
        lines.append(f"  {mark} {item['step']}  [{item['state_label']}]")
        if item["at"]:
            lines.append(f"      时间：{item['at']}")
        if item["skill_id"]:
            lines.append(f"      Skill：{item['skill_id']}")
        if item["validator"]:
            lines.append(f"      校验器：{item['validator']}")
        if item["attestation_id"]:
            lines.append(f"      读取证明：{item['attestation_id']}")
        for read in item["reads"]:
            label = {
                "read": "已读",
                "missing": "未记录（这一步必须读）",
                "pending": "未开始（这一步需要读）",
                "unrecorded": "未记录",
            }[read["status"]]
            lines.append(f"      协议：{read['path']} — {label}")
        if item["evidence"]:
            lines.append(f"      证据：{item['evidence']}")
        if item["reason"]:
            lines.append(f"      原因：{item['reason']}")
        lines.append("")
    compliance = summary["compliance"]
    lines.append(f"合规检查：{compliance['status']}")
    for error in compliance.get("errors", []):
        lines.append(f"  - {error}")
    if summary["pending"]:
        lines.append("")
        lines.append("尚未执行的步骤：")
        for step in summary["pending"]:
            lines.append(f"  - {step}")
    return "\n".join(lines)


_STATUS_COLORS = {
    "COMPLETED": "#1a7f37",
    "WAITING_APPROVAL": "#9a6700",
    "PAUSED_EXCEPTION": "#bc4c00",
    "BLOCKED": "#cf222e",
    "FAILED": "#cf222e",
    "RUNNING": "#0969da",
}


def render_html(summary: dict) -> str:
    def badge(outcome: str, label: str) -> str:
        color = _STATUS_COLORS.get(outcome, "#6e7781")
        return f'<span class="badge" style="--c:{color}">{escape(label)}</span>'

    rows: list[str] = []
    for item in summary["steps"]:
        reads = []
        for read in item["reads"]:
            if read["status"] == "read":
                reads.append(f'<li class="ok">已读 <code>{escape(read["path"])}</code></li>')
            elif read["status"] == "missing":
                reads.append(f'<li class="miss">未记录（这一步必须读） <code>{escape(read["path"])}</code></li>')
            elif read["status"] == "pending":
                reads.append(f'<li class="dim">未开始 · 这一步需要读 <code>{escape(read["path"])}</code></li>')
            else:
                reads.append(f'<li class="dim">未记录 <code>{escape(read["path"])}</code></li>')
        meta = []
        if item["skill_id"]:
            meta.append(f"<span>Skill：<code>{escape(item['skill_id'])}</code></span>")
        if item["validator"]:
            meta.append(f"<span>校验器：<code>{escape(item['validator'])}</code></span>")
        if item["attestation_id"]:
            meta.append(f"<span>读取证明：<code>{escape(item['attestation_id'])}</code></span>")
        if item["evidence"]:
            meta.append(f"<span>证据：<code>{escape(item['evidence'])}</code></span>")
        if item["at"]:
            meta.append(f"<span class=\"dim\">{escape(item['at'])}</span>")
        reason = f'<p class="reason">{escape(item["reason"])}</p>' if item["reason"] else ""
        rows.append(
            f"""
      <section class="step {'done' if item['done'] else ''}">
        <header>
          <span class="dot" style="--c:{_STATUS_COLORS.get(item['outcome'], '#6e7781')}"></span>
          <h3>{escape(item['step'])}</h3>
          {badge(item['outcome'], item['state_label'])}
        </header>
        <div class="meta">{' · '.join(meta)}</div>
        {reason}
        <ul class="reads">{''.join(reads)}</ul>
      </section>"""
        )

    compliance = summary["compliance"]
    problems = "".join(f"<li>{escape(e)}</li>" for e in compliance.get("errors", []))
    problem_block = (
        f'<div class="problems"><h2>合规问题（{len(compliance["errors"])}）</h2><ul>{problems}</ul></div>'
        if compliance.get("errors")
        else '<div class="clean">合规检查通过：每一步都记录了 Skill、证据与必需的协议读取。</div>'
    )
    pending = "".join(f"<li><code>{escape(s)}</code></li>" for s in summary["pending"])
    pending_block = f'<div class="pending"><h2>尚未执行（{len(summary["pending"])}）</h2><ul>{pending}</ul></div>' if summary["pending"] else ""
    halt = (
        f'<div class="halt"><strong>等待决定：</strong>{escape(summary["pending_decision"])}</div>'
        if summary.get("pending_decision")
        else ""
    )
    progress_pct = 0 if not summary["progress"]["total"] else round(
        100 * summary["progress"]["completed"] / summary["progress"]["total"]
    )

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>生产线运行报告 · {escape(summary['run_id'])}</title>
<style>
  :root {{ color-scheme: light dark; --bg:#fff; --fg:#1f2328; --line:#d1d9e0; --muted:#59636e; --card:#f6f8fa; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#0d1117; --fg:#e6edf3; --line:#30363d; --muted:#9198a1; --card:#161b22; }}
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; padding:32px 20px 64px; background:var(--bg); color:var(--fg);
         font:15px/1.6 -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif; }}
  .wrap {{ max-width:900px; margin:0 auto; }}
  h1 {{ font-size:20px; margin:0 0 4px; }}
  h2 {{ font-size:15px; margin:0 0 10px; }}
  h3 {{ font-size:15px; margin:0; }}
  .sub {{ color:var(--muted); font-size:13px; margin-bottom:20px; }}
  .cards {{ display:flex; gap:12px; flex-wrap:wrap; margin-bottom:20px; }}
  .card {{ flex:1 1 160px; background:var(--card); border:1px solid var(--line); border-radius:10px; padding:12px 14px; }}
  .card .k {{ color:var(--muted); font-size:12px; }}
  .card .v {{ font-size:18px; font-weight:600; margin-top:2px; }}
  .bar {{ height:6px; background:var(--line); border-radius:3px; margin-top:8px; overflow:hidden; }}
  .bar > i {{ display:block; height:100%; background:#1a7f37; }}
  .badge {{ display:inline-block; padding:1px 8px; border-radius:999px; font-size:12px;
            color:#fff; background:var(--c,#6e7781); }}
  .step {{ border:1px solid var(--line); border-radius:10px; padding:12px 14px; margin-bottom:10px; }}
  .step.done {{ border-left:3px solid #1a7f37; }}
  .step header {{ display:flex; align-items:center; gap:8px; }}
  .dot {{ width:8px; height:8px; border-radius:50%; background:var(--c,#6e7781); flex:none; }}
  .step header h3 {{ flex:1; }}
  .meta {{ color:var(--muted); font-size:12.5px; margin:6px 0 4px; }}
  .meta code, .reads code, .pending code {{ font-size:12.5px; }}
  .reason {{ margin:6px 0; padding:6px 10px; background:var(--card); border-radius:6px; font-size:13px; }}
  .reads {{ list-style:none; margin:6px 0 0; padding:0; font-size:13px; }}
  .reads li {{ padding:2px 0 2px 18px; position:relative; }}
  .reads li::before {{ position:absolute; left:0; }}
  .reads li.ok::before {{ content:"✓"; color:#1a7f37; }}
  .reads li.miss::before {{ content:"✗"; color:#cf222e; }}
  .reads li.dim::before {{ content:"·"; color:var(--muted); }}
  .reads li.miss {{ color:#cf222e; }}
  .reads li.dim {{ color:var(--muted); }}
  .clean {{ background:rgba(26,127,55,.1); border:1px solid rgba(26,127,55,.4); border-radius:10px;
            padding:12px 14px; margin-top:16px; }}
  .problems, .pending {{ background:var(--card); border:1px solid var(--line); border-radius:10px;
                         padding:12px 14px; margin-top:16px; }}
  .problems {{ border-color:rgba(207,34,46,.5); }}
  .problems ul, .pending ul {{ margin:0; padding-left:20px; font-size:13.5px; }}
  .halt {{ margin-top:16px; padding:10px 14px; border-radius:10px; background:rgba(154,103,0,.12);
           border:1px solid rgba(154,103,0,.4); }}
  footer {{ margin-top:28px; color:var(--muted); font-size:12px; }}
  code {{ font-family: ui-monospace, Consolas, monospace; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>生产线运行报告</h1>
  <div class="sub">运行 <code>{escape(summary['run_id'])}</code> · 合同 <code>{escape(summary['contract_id'])}</code> · 生成于 {escape(summary['generated_at'])}</div>

  <div class="cards">
    <div class="card"><div class="k">状态</div><div class="v">{escape(summary['status'] or '-')}</div></div>
    <div class="card"><div class="k">进度</div><div class="v">{summary['progress']['completed']} / {summary['progress']['total']}</div>
      <div class="bar"><i style="width:{progress_pct}%"></i></div></div>
    <div class="card"><div class="k">合规</div><div class="v">{escape(compliance['status'])}</div></div>
    <div class="card"><div class="k">当前步骤</div><div class="v" style="font-size:14px">{escape(summary['current_step'] or '-')}</div></div>
  </div>

  {halt}

  <h2>步骤明细（{len(summary['steps'])} 步）</h2>
  {''.join(rows)}

  {problem_block}
  {pending_block}

  <footer>
    数据来源：<code>run_state.json</code>（编排器与 Skill 运行事件）。生成命令：
    <code>python -m production_control.run_report &lt;run_state.json&gt; --html report.html</code>
  </footer>
</div>
</body>
</html>
"""


def build_report(run_state_path: str | Path, chain: dict | None = None, manifest: dict | None = None) -> dict:
    state = json.loads(Path(run_state_path).read_text(encoding="utf-8"))
    if manifest is None:
        manifest_path = Path(run_state_path).with_name("protocol_manifest.json")
        if manifest_path.is_file():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return summarize(state, chain, manifest)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Render a human-readable report from run_state.json")
    parser.add_argument("run_state")
    parser.add_argument("--html", help="write a self-contained HTML report to this path")
    parser.add_argument("--json", action="store_true", help="print the summary as JSON instead of text")
    args = parser.parse_args()
    summary = build_report(args.run_state)
    if args.html:
        target = Path(args.html)
        target.write_text(render_html(summary), encoding="utf-8")
        print(f"html report written: {target}")
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    elif not args.html:
        print(render_text(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
