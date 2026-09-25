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
import os
import sys
from datetime import datetime, timezone
from html import escape
from pathlib import Path

from . import gate_map, gate_token, run_index, skill_audit, step_audit
from .outcomes import OUTCOME_LABELS
from .run_compliance import STEP_PROTOCOL_REQUIREMENTS, verify_run_compliance

# How long a project may go without a single reported step before the board calls
# it out. The board cannot force an agent to report, but it can make silence
# impossible to miss - which is the whole point of replacing log-reading.
STALE_MINUTES = int(os.environ.get("RUN_BOARD_STALE_MINUTES", "15"))


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


def summarize(state: dict, chain: dict | None = None, manifest: dict | None = None,
              project_root: str | Path | None = None) -> dict:
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
                "state_label": (
                    OUTCOME_LABELS.get(outcome)
                    or outcome
                    or ("未开始" if step not in completed else "已完成")
                ),
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
    reconciliation = step_audit.audit_run(state, project_root, chain)
    qa_passes = step_audit.audit_qa_passes(state, project_root)
    return {
        "run_id": state.get("run_id", ""),
        "contract_id": state.get("contract_id", ""),
        "segment": state.get("segment", ""),
        "segment_title": state.get("segment_title", ""),
        "status": state.get("status", ""),
        "pending_decision": state.get("pending_decision", ""),
        "current_step": state.get("current_step", ""),
        "progress": {"completed": step_accounting(state)["completed"],
                     "total": step_accounting(state)["total"]},
        "custom_steps": step_accounting(state)["custom_steps"],
        "steps": rendered,
        "pending": [s for s in steps if s not in completed],
        "compliance": compliance,
        "audit": reconciliation,
        "qa_passes": qa_passes,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def step_accounting(state: dict) -> dict:
    """How far along this run actually is.

    Progress used to be `completed_steps ∩ pipeline`, which silently reported
    zero whenever a window recorded its work under Gate names (G2-shot-confirm,
    G3-local-assets, G5-prompt) instead of the twelve skill names. EP03/A1 had
    finished seven steps and the board showed 0/12 - a run that was visibly
    moving looked untouched, which is worse than showing nothing.

    So count every completed step, and add the off-pipeline ones to the
    denominator so the percentage stays honest. The off-pipeline names are
    reported separately: they are worth seeing (they are how a window really
    worked) but they are also a compliance question.
    """
    pipeline = list(state.get("pipeline") or [])
    completed = [s for s in (state.get("completed_steps") or [])]
    custom = [s for s in completed if s not in pipeline]
    total = len(pipeline) + len(custom)
    return {"completed": len(completed), "total": total,
            "pipeline_total": len(pipeline), "custom_steps": custom}


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


def _badge(outcome: str, label: str) -> str:
    color = _STATUS_COLORS.get(outcome, "#6e7781")
    return f'<span class="badge" style="--c:{color}">{escape(label)}</span>'


def _steps_html(summary: dict) -> list[str]:
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
          {_badge(item['outcome'], item['state_label'])}
        </header>
        <div class="meta">{' · '.join(meta)}</div>
        {reason}
        <ul class="reads">{''.join(reads)}</ul>
      </section>"""
        )

    return rows


RUN_STATUS_LABELS = {
    "COMPLETED": "已完成",
    "SUBMITTED_FOR_QA": "已提交，等待 QA",
    "WAITING_APPROVAL": "等待批准",
    "PAUSED_EXCEPTION": "已挂起",
    "BLOCKED": "已阻断",
    "FAILED": "失败",
    "RUNNING": "进行中",
    "": "未开始",
}


def minutes_since(iso: str) -> int | None:
    """Whole minutes since an ISO timestamp, or None when there is no timestamp."""
    if not iso:
        return None
    text = iso.strip().replace("Z", "+00:00")
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return int((datetime.now(timezone.utc) - moment).total_seconds() // 60)


def reporting_state(idle_minutes: int | None, *, threshold: int = STALE_MINUTES,
                    started: int = 0) -> dict:
    """Is the agent still reporting, or has it gone quiet?

    `level` is one of: ok (recent report), stale (quiet too long), none (never
    reported anything), idle (nothing is running, so silence is expected).
    """
    threshold = threshold or STALE_MINUTES
    if idle_minutes is None:
        level = "none" if started else "idle"
        label = "还没有任何回传" if started else "无进行中的段"
        hint = ("Agent 尚未通过 append_event.py 回传任何一步。" if started
                else "当前没有进行中的段，无需回传。")
    elif idle_minutes <= threshold:
        level = "ok"
        label = "正常"
        hint = f"最近一次回传在 {idle_minutes} 分钟前（阈值 {threshold} 分钟）。"
    else:
        level = "stale"
        label = f"已 {idle_minutes} 分钟没有回传"
        hint = (f"超过 {threshold} 分钟没有新的步骤回传，疑似卡住或窗口已停。"
                "检查生产窗口是否还在跑，或让 Agent 用 append_event.py 补回报。")
    return {"level": level, "label": label, "hint": hint,
            "idle_minutes": idle_minutes, "stale_after_minutes": threshold}


def summarize_project(index: dict, project_root: str | Path | None = None, *, with_details: bool = True) -> dict:
    """Build the episode-wide view: one row per segment, optionally with detail."""
    root = Path(project_root) if project_root else None
    rows = []
    for row in index.get("runs", []) or []:
        item = dict(row)
        item["active"] = row.get("run_id") == index.get("active_run_id")
        item["state_label"] = RUN_STATUS_LABELS.get(row.get("status", "") or "", "未开始")
        progress = row.get("progress") or {}
        total = progress.get("total") or 0
        item["percent"] = 0 if not total else round(100 * (progress.get("completed") or 0) / total)
        item["detail"] = None
        if with_details and root:
            candidate = run_index.resolve_run_path(root, row.get("run_id", ""), row.get("path") or "")
            if candidate.is_file():
                try:
                    item["detail"] = summarize(json.loads(candidate.read_text(encoding="utf-8")),
                                               project_root=root)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    item["detail"] = None
        rows.append(item)

    counts = {"total": len(rows), "completed": 0, "running": 0, "waiting": 0, "blocked": 0, "not_started": 0}
    for row in rows:
        status = row.get("status") or ""
        started = bool(row.get("last_event_at")) or bool((row.get("progress") or {}).get("completed"))
        if status == "COMPLETED":
            counts["completed"] += 1
        elif status == "WAITING_APPROVAL":
            counts["waiting"] += 1
        elif status in {"PAUSED_EXCEPTION", "BLOCKED"}:
            counts["blocked"] += 1
        elif started:
            counts["running"] += 1
        else:
            counts["not_started"] += 1

    newest_event = max((row.get("last_event_at", "") or "" for row in rows), default="")
    index_time = index.get("updated_at", "") or ""
    source = ""
    if root:
        candidate = root / "workflow" / "run_index.json"
        if candidate.is_file():
            source = str(candidate)
    project_state = run_index.load_project_state(root) if root else {}
    if not newest_event and root and project_state:
        # The agent may only ever write its own status file. Treat that file as a
        # heartbeat too (by mtime, not by its date-only "updated" field), or a
        # project that is visibly moving still reads as "never reported".
        stamp = run_index.project_state_mtime(root)
        if stamp:
            newest_event = datetime.fromtimestamp(stamp, timezone.utc).isoformat()
    idle_minutes = minutes_since(newest_event)
    return {
        "project": index.get("project", ""),
        "series": index.get("series", ""),
        "episode": index.get("episode", ""),
        "active_run_id": index.get("active_run_id", ""),
        "runs": rows,
        "counts": counts,
        "data_source": source,
        "index_updated_at": index_time,
        "newest_event_at": newest_event,
        "stale": bool(newest_event and index_time and newest_event > index_time),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project_state": project_state,
        "gate_tokens": gate_token.load_tokens(root) if root else [],
        "skill_audits": skill_audit.load_audits(root) if root else [],
        "idle_minutes": idle_minutes,
        "reporting": reporting_state(idle_minutes, started=counts["running"] + counts["waiting"] + counts["blocked"]),
    }


def render_project_text(view: dict) -> str:
    lines = [f"项目 {view['project']}  系列 {view['series'] or '-'}  集 {view['episode'] or '-'}"]
    counts = view["counts"]
    lines.append(
        f"共 {counts['total']} 段：已完成 {counts['completed']} · 进行中 {counts['running']} · "
        f"等待批准 {counts['waiting']} · 挂起/阻断 {counts['blocked']} · 未开始 {counts['not_started']}"
    )
    active = next((r for r in view["runs"] if r["active"]), None)
    if active:
        lines.append(f"当前进行到：{active['run_id']}  {active.get('segment_title','')}  [{active['state_label']}]")
    else:
        lines.append("当前进行到：-")
    lines.append(f"数据来源：{view['data_source'] or '(未找到 run_index.json)'}    索引更新时间：{view['index_updated_at'] or '-'}")
    if view["stale"]:
        lines.append("⚠️ 索引比段落事件旧：先 run_index.sync 再渲染，否则看到的是旧状态")
    lines.append("")
    for row in view["runs"]:
        mark = "▶" if row["active"] else " "
        title = f"  {row.get('segment_title','')}" if row.get("segment_title") else ""
        lines.append(f"{mark} {row['run_id']}{title}  [{row['state_label']}]  {row['percent']}%  {row.get('current_step','') or ''}")
        if row.get("pending_decision"):
            lines.append(f"      待决定：{row['pending_decision']}")
        detail = row.get("detail")
        if detail:
            lines.append(f"      步骤 {detail['progress']['completed']}/{detail['progress']['total']} · 合规 {detail['compliance']['status']}")
            for error in detail["compliance"].get("errors", []):
                lines.append(f"        - {error}")
    return "\n".join(lines)


def heartbeat_block(reporting: dict, newest_event_at: str = "") -> str:
    """Is the agent still reporting? Shown on both the episode page and a segment.

    The board cannot force a window to report, but it can make silence loud. One
    block, same wording everywhere, so "is it still alive" is never a log-dig.
    """
    if not reporting:
        return ""
    return f"""
  <div class="heartbeat {reporting.get('level', 'idle')}">
    <div class="hbline">
      <strong>Agent 实时回传：{escape(reporting.get('label', ''))}</strong>
      <span class="dim">最后回传：{escape(newest_event_at or '从未回传')}</span>
    </div>
    <div class="dim">{escape(reporting.get('hint', ''))}</div>
    <div class="dim">回传契约：每完成一步必须 <code>append_event.py</code> 写入轨迹；
      被阻断 / 等待批准 / 挂起也要立刻回报，不允许只在最后写总结。</div>
  </div>"""


def project_state_block(state: dict) -> str:
    """What the producing window says about itself, read-only."""
    if not state:
        return ""
    facts = "".join(
        f"<span>{escape(key)}：<code>{escape(str(state[key]))}</code></span>"
        for key in ("stage", "status", "owner", "updated") if state.get(key)
    )
    blocks = [
        f'<div class="psbox"><h3>{escape(label)}</h3><ul>'
        + "".join(f"<li>{escape(str(item))}</li>" for item in (state.get(key) or []))
        + "</ul></div>"
        for key, label in (("blockers", "阻断项"), ("artifacts", "已产出文件")) if state.get(key)
    ]
    extras = "".join(
        f"<div class='psrow'><span>{escape(key)}</span>"
        f"<code>{escape(json.dumps(value, ensure_ascii=False))}</code></div>"
        for key, value in state.items()
        if key not in {"stage", "status", "owner", "updated", "blockers", "artifacts"}
        and isinstance(value, (dict, list))
    )
    return f"""
  <section class="pstate">
    <h2>生产窗口自报状态（workflow/project_state.json）</h2>
    <div class="sub">这个文件由生产窗口自己写；看板只读不写，用来兜底——
      即便它没有走 append_event 通道，你也能在这里看到它做到哪一步。</div>
    <div class="psfacts">{facts}</div>
    {''.join(blocks)}
    {extras}
  </section>"""


def gate_token_block(tokens: list[dict]) -> str:
    """Did the asset gate actually hold, or was it just written down?

    This is the block to look at before clicking generate: a green run with no
    token means the gate was skipped, not passed.
    """
    if not tokens:
        return """
  <section class="pstate">
    <h2>建节点前置门禁令牌（workflow/gates/）</h2>
    <div class="sub">令牌由 <code>tools/gate_token.py</code> 校验后产出，不由 Agent 手写。
      它比对的是<strong>合同声明集合 == 平台绑定集合</strong>（按 role + sha256 配对），
      不是"传够几张"。合同若被改动，令牌自动失效。</div>
    <div class="reason">⚠️ <strong>没有任何令牌</strong>——说明这段<strong>从未通过</strong>建节点前置门禁。
      门禁没通过不等于门禁通过了：空列表是"没走"，不是"没问题"。</div>
  </section>"""
    rows = []
    for token in tokens:
        ok = token.get("still_valid")
        rows.append(
            f"<tr><td><code>{escape(str(token.get('gate','')))}_{escape(str(token.get('unit_id','')))}</code></td>"
            f"<td>{'✅ 有效' if ok else '❌ ' + escape(token.get('stale_reason', '无效'))}</td>"
            f"<td>{token.get('declared_count', 0)} / {token.get('bound_count', 0)}</td>"
            f"<td class='dim'>{escape(str(token.get('evaluated_at', ''))[:19])}</td></tr>"
        )
    return f"""
  <section class="pstate">
    <h2>建节点前置门禁令牌（workflow/gates/）</h2>
    <div class="sub">令牌由 <code>tools/gate_token.py</code> 校验后产出，不由 Agent 手写。
      它比对的是<strong>合同声明集合 == 平台绑定集合</strong>（按 role + sha256 配对），
      不是"传够几张"。合同若被改动，令牌自动失效。</div>
    <table>
      <thead><tr><th>门禁 / 单元</th><th>状态</th><th>声明 / 已绑定</th><th>校验时间</th></tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
  </section>"""


def skill_audit_block(audits: list[dict]) -> str:
    """Did the prompt actually go through a Skill, or was it just written?

    EP03 shipped a batch of prompts nobody had audited. This block is here so
    that is visible before generate is clicked, not discovered afterwards.
    """
    if not audits:
        return """
  <section class="pstate">
    <h2>G5.1 模型 Skill 审计（workflow/skill_audits/）</h2>
    <div class="sub">未跑（<code>NOT_RUN</code>）、不确定（<code>UNCERTAIN</code>）、
      无证据的 PASS —— 一律按阻断处理，<strong>不允许先建节点再补 Skill</strong>。
      Prompt 改一句就要递增版本并重新审计。</div>
    <div class="reason">⚠️ <strong>没有任何审计记录</strong>——说明这批 Prompt
      <strong>从未跑过 Skill</strong>。这是 G5.1 最严重的状态：内容看起来写好了，
      但没有任何一项经过校验。</div>
  </section>"""
    rows = []
    for item in audits:
        ok = item.get("ok")
        rows.append(
            f"<tr><td><code>{escape(str(item.get('unit_id') or '-'))}</code></td>"
            f"<td>{'✅ SKILL_GATE_PASS' if ok else '❌ ' + escape(str(item.get('overall','')))}</td>"
            f"<td>{item.get('skill_count', 0)}</td>"
            f"<td><code>{escape(str(item.get('prompt_version') or '-'))}</code></td>"
            f"<td class='dim'>{escape('；'.join(item.get('errors', []))[:160])}</td></tr>"
        )
    return f"""
  <section class="pstate">
    <h2>G5.1 模型 Skill 审计（workflow/skill_audits/）</h2>
    <div class="sub">未跑（<code>NOT_RUN</code>）、不确定（<code>UNCERTAIN</code>）、
      无证据的 PASS —— 一律按阻断处理，<strong>不允许先建节点再补 Skill</strong>。
      Prompt 改一句就要递增版本并重新审计。</div>
    <table>
      <thead><tr><th>单元</th><th>判定</th><th>skill 项数</th><th>Prompt 版本</th><th>问题</th></tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
  </section>"""


def render_project_html(view: dict, *, live: bool = False) -> str:
    """Episode-wide page: every segment on one screen, expandable to per-step detail.

    live=True is served by run_server: the page re-reads disk on every request, so
    the refresh button and auto-refresh always show current state. A static export
    (live=False) is a snapshot and says so.
    """
    counts = view["counts"]
    live_hint = "实时模式：每次刷新都重新读取磁盘上的最新状态" if live else "静态快照：数据为生成时状态，需重新运行命令才会更新"
    auto_checked = "checked" if live else ""

    reporting = view.get("reporting") or reporting_state(view.get("idle_minutes"))
    heartbeat = heartbeat_block(reporting, view.get("newest_event_at", ""))
    heading = " · ".join(x for x in (view["series"], view["episode"]) if x) or view["project"]

    # One line instead of six cards: the numbers that change a decision, and
    # nothing else. Per-segment detail lives in the table below.
    tot_passed = sum((r.get("detail") or {}).get("qa_passes", {}).get("passed", 0) for r in view["runs"])
    tot_submitted = sum((r.get("detail") or {}).get("qa_passes", {}).get("submitted", 0) for r in view["runs"])
    active = next((r for r in view["runs"] if r["active"]), None)
    strip_bits = [
        f'段 <b>{counts["total"]}</b>',
        f'QA 通过 <b class="{"ok" if tot_passed else ""}">{tot_passed}</b> / 已提交 <b>{tot_submitted}</b>',
        f'进行中 <b>{counts["running"] + counts["waiting"]}</b>',
        f'阻断 <b class="{"stale" if counts["blocked"] else ""}">{counts["blocked"]}</b>',
        f'未开始 <b>{counts["not_started"]}</b>',
    ]
    if active:
        strip_bits.append("当前 <b>" + escape(active.get("segment_title") or active.get("segment")
                                             or active["run_id"]) + "</b>")
    strip_bits.append(f'最后回传 <b class="{escape(reporting.get("level") or "")}">'
                      f'{escape(reporting.get("label") or "从未回传")}</b>')
    strip = ' <span class="sep">·</span> '.join(strip_bits)

    # Global warnings only. The standalone gate-token / skill-audit / self-report
    # panels said the same thing three times over a mostly-empty page; their
    # conclusions now ride along per segment in the table.
    alerts = []
    if reporting.get("level") in ("stale", "none"):
        alerts.append(f'<li>{escape(reporting.get("label") or "")}——{escape(reporting.get("hint") or "")}</li>')
    state = view.get("project_state") or {}
    for key, label in (("blockers", "阻断项"),):
        for item in (state.get(key) or []):
            alerts.append(f"<li>{escape(label)}：{escape(str(item))}</li>")
    if not view.get("gate_tokens"):
        alerts.append("<li>门禁令牌：<strong>一条都没有</strong>——没有任何一段通过过建节点前置门禁。</li>")
    if not view.get("skill_audits"):
        alerts.append("<li>Skill 审计：<strong>一条都没有</strong>——没有任何 Prompt 跑过 G5.1 审计。</li>")
    alert_card = (
        f'<div class="problems"><h3>全局告警</h3><ul>{"".join(alerts)}</ul></div>'
        if alerts else ""
    )
    # A static export has no backend: any control that navigates or reloads would
    # fail (and look like a broken app). Only the live server gets real controls.
    toolbar_controls = (
        f"""
    <button type="button" onclick="location.reload()">🔄 立即刷新</button>
    <label><input type="checkbox" id="auto" {auto_checked}> 自动刷新（每 5 秒）</label>
    <span class="dim">{live_hint}</span>"""
        if live
        else """
    <span>这是<b>静态快照</b>：刷新与编辑控件在此不生效（静态文件没有后端）。
      要实时刷新、切换段落或录入段清单，请运行：
      <code>python tools\\render_run_report.py &lt;项目目录&gt; --serve</code></span>"""
    )

    segments_json = json.dumps(view.get("segments", []), ensure_ascii=False)
    meta_json = json.dumps(
        {"project": view.get("project", ""), "series": view.get("series", ""), "episode": view.get("episode", "")},
        ensure_ascii=False,
    )
    segments_source = view.get("segments_source", "workflow/segments.json")
    editor = (
        f"""
  <section class="editor">
    <h2>段清单 —— 在这里录入，保存后即为权威数据</h2>
    <div class="sub">
      保存写入 <code>{escape(segments_source)}</code>；Agent 启动每一段时读取同一份文件取段名，两边不会各叫一个名字。
    </div>
    <table id="segTable">
      <thead><tr><th style="width:90px">段号</th><th>段名（例：B-2A（物理格斗））</th><th>备注</th><th style="width:44px"></th></tr></thead>
      <tbody></tbody>
    </table>
    <div class="editorbar">
      <button type="button" onclick="addSeg()">+ 添加一段</button>
      <button type="button" class="primary" onclick="saveSegs()">保存段清单</button>
      <span id="segMsg" class="dim"></span>
    </div>
  </section>

  <script>
    var SEGS = {segments_json};
    var META = {meta_json};
    var tbody = document.querySelector('#segTable tbody');
    var msg = document.getElementById('segMsg');

    function renderSegs() {{
      tbody.innerHTML = SEGS.map(function (row, i) {{
        return '<tr>' +
          '<td><input value="' + (row.segment || '').replace(/"/g, '&quot;') + '" data-k="segment" data-i="' + i + '" placeholder="U01"></td>' +
          '<td><input value="' + (row.title || '').replace(/"/g, '&quot;') + '" data-k="title" data-i="' + i + '" placeholder="B-2A（物理格斗）"></td>' +
          '<td><input value="' + (row.note || '').replace(/"/g, '&quot;') + '" data-k="note" data-i="' + i + '"></td>' +
          '<td><button type="button" onclick="delSeg(' + i + ')">✕</button></td>' +
        '</tr>';
      }}).join('');
    }}

    function collect() {{
      var rows = {{}};
      document.querySelectorAll('#segTable input').forEach(function (input) {{
        var i = Number(input.dataset.i);
        rows[i] = rows[i] || {{ segment: '', title: '', note: '' }};
        rows[i][input.dataset.k] = input.value.trim();
      }});
      return Object.keys(rows).sort(function (a, b) {{ return a - b; }}).map(function (i) {{ return rows[i]; }});
    }}

    function addSeg() {{ SEGS = collect(); SEGS.push({{ segment: '', title: '', note: '' }}); renderSegs(); }}
    function delSeg(i) {{ SEGS = collect(); SEGS.splice(i, 1); renderSegs(); }}

    async function saveSegs() {{
      var payload = Object.assign({{}}, META, {{ segments: collect().filter(function (r) {{ return r.segment; }}) }});
      msg.textContent = '保存中…';
      try {{
        var res = await fetch('/api/segments', {{
          method: 'POST', headers: {{ 'Content-Type': 'application/json' }}, body: JSON.stringify(payload),
        }});
        var data = await res.json();
        if (data.ok) {{ msg.textContent = '已保存到 ' + data.path + '，正在刷新…'; setTimeout(function () {{ location.reload(); }}, 400); }}
        else {{ msg.textContent = '保存失败：' + data.error; }}
      }} catch (err) {{ msg.textContent = '保存失败：' + err; }}
    }}

    renderSegs();
  </script>
"""
        if live
        else """
  <section class="editor readonly">
    <h2>段清单（只读）</h2>
    <div class="sub">静态快照无法写回磁盘。要录入/修改段名，用实时模式：
      <code>python -m production_control.run_report &lt;项目目录&gt; --serve</code></div>
  </section>
"""
    )

    rows = []
    for row in view["runs"]:
        expand = ""
        if row.get("detail"):
            expand = (
                '<details class="more"><summary>逐步明细</summary>'
                f"{''.join(_steps_html(row['detail']))}</details>"
            )
        detail = row.get("detail") or {}
        audit = detail.get("audit") or {}
        counts_a = (audit.get("steps") or {}).get("counts") or {}
        passes = detail.get("qa_passes") or {}
        submitted, passed = passes.get("submitted", 0), passes.get("passed", 0)

        # How far the segment really got: passed over submitted. Nine steps
        # submitted and none passed is not 90% done, and the table must not let
        # it look that way.
        if submitted:
            cls = "ok" if passed == submitted else ("wait" if passed else "wait")
            qa_cell = f'<span class="vp {cls}">{passed} / {submitted}</span>'
            if passes.get("awaiting"):
                qa_cell += f'<div class="note">等待 QA {passes["awaiting"]}</div>'
            if passes.get("failed"):
                qa_cell += f'<div class="note bad">不通过 {passes["failed"]}</div>'
        else:
            qa_cell = '<span class="vp todo">0 / 0</span>'

        blockers = []
        if counts_a.get(step_audit.CLAIMED_NO_EVIDENCE):
            blockers.append(f'{counts_a[step_audit.CLAIMED_NO_EVIDENCE]} 步无实证')
        if counts_a.get(step_audit.NOT_CLAIMED):
            blockers.append(f'{counts_a[step_audit.NOT_CLAIMED]} 步未做')
        if counts_a.get(step_audit.CLAIMED_NO_READ):
            blockers.append(f'{counts_a[step_audit.CLAIMED_NO_READ]} 步未读协议')
        if counts_a.get(step_audit.EXTRA):
            blockers.append(f'{counts_a[step_audit.EXTRA]} 步在协议链外')
        if passes.get("awaiting"):
            blockers.append(f'{passes["awaiting"]} 步等待 QA')

        serious = counts_a.get(step_audit.CLAIMED_NO_EVIDENCE) or counts_a.get(step_audit.EXTRA)
        where = f'<code>{escape(row.get("current_step", "") or "-")}</code>'
        if row.get("pending_decision"):
            where += f'<div class="note">{escape(row["pending_decision"])}</div>'
        if blockers:
            where += (f'<div class="note{" bad" if serious else ""}">'
                      + " ｜ ".join(blockers) + "</div>")
        rows.append(
            f"""
      <tr class="{'active' if row['active'] else ''}">
        <td class="rid">{'▶ ' if row['active'] else ''}<code>{escape(row.get('segment', '') or row.get('run_id',''))}</code>
          {f'<div class="title">{escape(row.get("segment_title",""))}</div>' if row.get("segment_title") else ''}</td>
        <td>{_badge(row.get('status','') or '', row['state_label'])}</td>
        <td>{qa_cell}</td>
        <td>{where}</td>
        <td class="dim">{escape((row.get('last_event_at','') or '-')[:19])}</td>
      </tr>
      <tr class="detailrow"><td colspan="5">{expand}</td></tr>"""
        )

    stale = (
        '<div class="problems"><h2>索引可能过期</h2><ul><li>段落文件里有比索引更新的事件：先执行 '
        "<code>run_index.sync</code> 再渲染，否则看到的是旧状态。</li></ul></div>"
        if view["stale"]
        else ""
    )

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>项目运行总表 · {escape(view['project'])}</title>
<style>
  :root {{ color-scheme: light dark; --bg:#fff; --fg:#1f2328; --line:#d1d9e0; --muted:#59636e; --card:#f6f8fa; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#0d1117; --fg:#e6edf3; --line:#30363d; --muted:#9198a1; --card:#161b22; }}
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; padding:32px 20px 64px; background:var(--bg); color:var(--fg);
         font:15px/1.6 -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif; }}
  .wrap {{ max-width:1000px; margin:0 auto; }}
  h1 {{ font-size:20px; margin:0 0 4px; }}
  h2 {{ font-size:15px; margin:0 0 10px; }}
  h3 {{ font-size:15px; margin:0; }}
  .sub {{ color:var(--muted); font-size:13px; margin-bottom:20px; }}
  .cards {{ display:flex; gap:12px; flex-wrap:wrap; margin-bottom:20px; }}
  .card {{ flex:1 1 110px; background:var(--card); border:1px solid var(--line); border-radius:10px; padding:12px 14px; }}
  .card .k {{ color:var(--muted); font-size:12px; }}
  .card .v {{ font-size:18px; font-weight:600; margin-top:2px; }}
  table {{ width:100%; border-collapse:collapse; font-size:13.5px; }}
  th, td {{ text-align:left; padding:8px 10px; border-bottom:1px solid var(--line); vertical-align:top; }}
  th {{ color:var(--muted); font-weight:500; font-size:12px; }}
  tr.active td {{ background:rgba(9,105,218,.08); }}
  tr.detailrow td {{ padding:0 10px 12px; }}
  .rid {{ white-space:nowrap; }}
  .bar {{ height:6px; background:var(--line); border-radius:3px; overflow:hidden; min-width:80px; margin-bottom:2px; }}
  .bar > i {{ display:block; height:100%; background:#1a7f37; }}
  .badge {{ display:inline-block; padding:1px 8px; border-radius:999px; font-size:12px; color:#fff; background:var(--c,#6e7781); }}
  .dim {{ color:var(--muted); }}
  .step {{ border:1px solid var(--line); border-radius:10px; padding:10px 12px; margin:8px 0; }}
  .step.done {{ border-left:3px solid #1a7f37; }}
  .step header {{ display:flex; align-items:center; gap:8px; }}
  .dot {{ width:8px; height:8px; border-radius:50%; background:var(--c,#6e7781); flex:none; }}
  .meta {{ color:var(--muted); font-size:12.5px; margin:6px 0 4px; }}
  .reason {{ margin:6px 0; padding:6px 10px; background:var(--card); border-radius:6px; font-size:12.5px; }}
  .reads {{ list-style:none; margin:6px 0 0; padding:0; font-size:13px; }}
  .reads li {{ padding:2px 0 2px 18px; position:relative; }}
  .reads li::before {{ position:absolute; left:0; }}
  .reads li.ok::before {{ content:"✓"; color:#1a7f37; }}
  .reads li.miss::before {{ content:"✗"; color:#cf222e; }}
  .reads li.dim::before {{ content:"·"; color:var(--muted); }}
  .reads li.miss {{ color:#cf222e; }}
  .more summary {{ cursor:pointer; color:var(--muted); font-size:12.5px; }}
  .toolbar {{ display:flex; align-items:center; gap:14px; flex-wrap:wrap; margin-bottom:16px;
              padding:10px 14px; background:var(--card); border:1px solid var(--line); border-radius:10px; }}
  .toolbar button {{ font:inherit; font-size:13.5px; padding:5px 14px; border-radius:8px; cursor:pointer;
                     border:1px solid var(--line); background:var(--bg); color:var(--fg); }}
  .toolbar button:hover {{ border-color:var(--muted); }}
  .toolbar label {{ font-size:13px; color:var(--muted); display:flex; align-items:center; gap:6px; cursor:pointer; }}
  .title {{ color:var(--muted); font-size:12px; margin-top:2px; }}
  .now {{ font-size:13px; }}
  .now strong {{ font-size:14.5px; }}
  .editor {{ border:1px solid var(--line); border-radius:10px; padding:14px; margin-top:22px; background:var(--card); }}
  .editor h2 {{ margin-bottom:6px; }}
  .editor table {{ background:var(--bg); border-radius:8px; margin-top:10px; }}
  .editor input {{ width:100%; font:inherit; font-size:13.5px; padding:5px 8px; border:1px solid var(--line);
                   border-radius:6px; background:var(--bg); color:var(--fg); }}
  .editorbar {{ display:flex; align-items:center; gap:10px; margin-top:10px; flex-wrap:wrap; }}
  .editorbar button {{ font:inherit; font-size:13.5px; padding:5px 12px; border-radius:8px; cursor:pointer;
                       border:1px solid var(--line); background:var(--bg); color:var(--fg); }}
  .editorbar button.primary {{ background:#1f6feb; border-color:#1f6feb; color:#fff; font-weight:600; }}
  .editor.readonly {{ opacity:.85; }}
  .problems {{ background:var(--card); border:1px solid rgba(207,34,46,.5); border-radius:10px; padding:12px 14px; margin-bottom:16px; }}
  .heartbeat {{ border:1px solid var(--line); border-left:4px solid var(--hb,#6e7781); border-radius:10px;
                padding:10px 14px; margin-bottom:16px; background:var(--card); }}
  .heartbeat .hbline {{ display:flex; gap:12px; align-items:baseline; flex-wrap:wrap; }}
  .heartbeat.ok {{ --hb:#1a7f37; }}
  .heartbeat.stale {{ --hb:#cf222e; background:rgba(207,34,46,.10); }}
  .heartbeat.none {{ --hb:#bf8700; }}
  .heartbeat.idle {{ --hb:#6e7781; }}
  .heartbeat.stale strong {{ color:#cf222e; }}
  .heartbeat div {{ font-size:13px; }}
  .pstate {{ border:1px solid var(--line); border-radius:10px; padding:12px 14px; margin:16px 0; background:var(--card); }}
  .pstate h2 {{ margin-bottom:6px; }}
  .psfacts {{ display:flex; gap:14px; flex-wrap:wrap; font-size:13px; margin-bottom:8px; }}
  .psbox h3 {{ font-size:13px; margin-top:8px; color:var(--muted); }}
  .psbox ul {{ margin:4px 0 0; padding-left:20px; font-size:13px; }}
  .psrow {{ display:flex; gap:10px; font-size:12.5px; margin-top:4px; }}
  .psrow span {{ color:var(--muted); flex:none; }}
  .problems ul {{ margin:0; padding-left:20px; font-size:13.5px; }}
  .strip {{ border:1px solid var(--line); border-radius:10px; padding:10px 14px; margin-bottom:16px;
            background:var(--card); font-size:13.5px; }}
  .strip .sep {{ color:var(--muted); }}
  .strip b {{ font-weight:500; }}
  .strip b.ok {{ color:#1a7f37; }} .strip b.stale {{ color:#cf222e; }} .strip b.none {{ color:#bf8700; }}
  .strip .bad {{ color:#cf222e; }} .strip .warn {{ color:#bf8700; }}
  table td {{ vertical-align:top; }}
  .vp {{ font-weight:500; white-space:nowrap; }}
  .vp.ok {{ color:#1a7f37; }} .vp.bad {{ color:#cf222e; }}
  .vp.warn, .vp.wait {{ color:#bf8700; }} .vp.todo {{ color:var(--muted); }}
  .note {{ font-size:12px; color:var(--muted); margin-top:2px; }}
  .note.bad {{ color:#cf222e; }}
  details.more {{ margin-top:10px; }}
  details.more summary {{ cursor:pointer; color:var(--muted); font-size:13px; }}
  footer {{ margin-top:28px; color:var(--muted); font-size:12px; }}
  code {{ font-family: ui-monospace, Consolas, monospace; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>{escape(heading)} <span class="dim" style="font-size:13px;font-weight:400">运行总表</span></h1>
  <div class="sub">项目 <code>{escape(view['project'])}</code> · 集 {escape(view['episode'] or '-')}</div>

  <div class="toolbar">{toolbar_controls}
    <span class="dim">本次渲染：{escape(view['generated_at'])}</span>
  </div>

  <div class="strip">{strip}</div>
  {stale}

  <table>
    <thead><tr><th>段</th><th>状态</th><th>QA 通过</th><th>卡在哪</th><th>最后事件</th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>

  <details class="more">
    <summary>展开：段清单录入 / 全局告警</summary>
    {alert_card}
    {editor}
  </details>

  <footer>
    <code>{escape(view['data_source'] or 'workflow/run_index.json')}</code> ·
    索引更新 {escape(view['index_updated_at'] or '-')} · 最新事件 {escape(view['newest_event_at'] or '-')}
  </footer>
</div>
<script>
  var box = document.getElementById('auto');
  var timer = null;
  function applyAuto() {{
    if (timer) {{ clearTimeout(timer); timer = null; }}
    if (box && box.checked) {{ timer = setTimeout(function () {{ location.reload(); }}, 5000); }}
  }}
  if (box) {{ box.addEventListener('change', applyAuto); applyAuto(); }}
</script>
</body>
</html>
"""


def step_audit_block(summary: dict) -> str:
    """The reconciliation table: what was claimed against what can be proven.

    This answers "did it follow the protocol", as opposed to "did it say it
    followed the protocol". A row claiming COMPLETED whose evidence file is not
    on disk is the shape of every incident so far, and it should be visible
    without opening a single log.
    """
    audit = summary.get("audit") or {}
    steps = audit.get("steps") or {}
    rows_data = steps.get("rows") or []
    if not rows_data:
        return ""
    counts = steps.get("counts") or {}
    qa = audit.get("qa") or {}

    marks = {"OK": "OK", "CLAIMED_NO_EVIDENCE": "不通过", "CLAIMED_NO_READ": "不完整",
             "NOT_CLAIMED": "未做", "EXTRA": "额外"}

    def badge(verdict: str) -> str:
        cls = "ok" if verdict == step_audit.OK else "bad"
        return (f'<span class="verdict {cls}">{escape(marks.get(verdict, verdict))}'
                f'<span class="dim"> {escape(step_audit.VERDICT_LABELS.get(verdict, ""))}</span></span>')

    rows = []
    for row in rows_data:
        note = ""
        if row.get("missing_reads"):
            note = "未记录读取：" + "、".join(row["missing_reads"])
        elif row.get("verdict") == step_audit.CLAIMED_NO_EVIDENCE:
            note = "证据文件不存在：" + (row.get("evidence") or "未填写 evidence")
        elif not row.get("claimed"):
            note = "协议要求这一步，轨迹里没有它"
        step = row["step"]
        rows.append(
            f'<tr><td><span class="gate">{escape(gate_map.gate_badge(step) or "链外")}</span></td>'
            f"<td>{escape(gate_map.skill_label(step))}"
            f'<div class="sid">{escape(step)}</div></td>'
            f"<td>{badge(row['verdict'])}</td>"
            f"<td>{'是' if row.get('claimed') else '否'}</td>"
            f"<td class='dim'>{escape(row.get('evidence') or '-')}</td>"
            f"<td class='dim'>{escape((row.get('at') or '')[:19] or '-')}</td>"
            f"<td class='dim'>{escape(note)}</td></tr>"
        )

    pairs = "".join(
        f'<div class="dim">生产者 <code>{escape(r.get("producer_actor") or "未记录")}</code>'
        f'（{escape(r.get("producer_step") or "-")}） → QA '
        f'<code>{escape(r.get("qa_actor") or "未记录")}</code></div>'
        for r in (qa.get("rounds") or [])
    ) or '<div class="dim">轨迹里没有任何 QA 事件。</div>'
    qa_cls = "clean" if qa.get("independent") else "problems"
    qa_block = (
        f'<div class="{qa_cls}"><h3>QA 独立性：{escape(qa.get("label", ""))}</h3>'
        f'<div class="dim">协议要求 QA 由<strong>不同模型</strong>执行：同一模型自审不算 QA，'
        f'未记录执行模型也不算。</div>{pairs}</div>'
    )

    summary_line = " · ".join(
        f"{escape(step_audit.VERDICT_LABELS.get(k, k))} {v}" for k, v in counts.items()
    )
    audit_errors = audit.get("errors") or []
    error_block = (
        '<div class="problems"><h3>对账失败项（%d）</h3><ul>%s</ul></div>'
        % (len(audit_errors), "".join(f"<li>{escape(e)}</li>" for e in audit_errors))
        if audit_errors
        else '<div class="clean">对账通过：协议声明的每一步都有实证，且没有链外步骤。</div>'
    )
    return f"""
  <section class="pstate">
    <h2>协议步骤对账（协议声明 {steps.get('declared_total', 0)} 项）</h2>
    <div class="sub">这是「有没有按协议走」的答案，而不是「有没有说自己按协议走了」。
      <strong>声称完成但磁盘上没有证据的那一行，就是被跳过的那一步。</strong></div>
    <div class="dim">{summary_line}</div>
    {error_block}
    {qa_block}
    <table>
      <thead><tr><th>Gate</th><th>步骤</th><th>对账结论</th><th>自报</th><th>证据</th><th>时间</th><th>说明</th></tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
  </section>"""


def qa_gate_block(summary: dict) -> str:
    """Who signed off, and whether it was anyone other than the author.

    The board counts a step as passed only when a different model recorded the
    verdict. A producer's own COMPLETED is a claim, and shown as one - which is
    the difference between "it says it is done" and "it is done".
    """
    qa = summary.get("qa_passes") or {}
    rows_data = qa.get("rows") or []
    if not rows_data:
        return ""
    mark = {"QA_PASSED": "通过", "QA_FAILED": "不通过",
            "AWAITING_QA": "等待 QA", "NOT_SUBMITTED": "未提交"}
    cls = {"QA_PASSED": "ok", "QA_FAILED": "bad", "AWAITING_QA": "warn", "NOT_SUBMITTED": ""}
    rows = []
    for row in rows_data:
        state = row.get("state", "")
        step = row["step"]
        rows.append(
            f'<tr><td><span class="gate">{escape(gate_map.gate_badge(step) or "链外")}</span></td>'
            f"<td>{escape(gate_map.skill_label(step))}"
            f'<div class="sid">{escape(step)}</div></td>'
            f'<td><span class="verdict {cls.get(state, "")}">{escape(mark.get(state, state))}</span></td>'
            f"<td><code>{escape(row.get('producer_actor') or '-')}</code></td>"
            f"<td><code>{escape(row.get('qa_actor') or '-')}</code></td>"
            f"<td class='dim'>{escape((row.get('qa_at') or row.get('at') or '')[:19] or '-')}</td></tr>"
        )
    return f"""
  <section class="pstate">
    <h2>QA 写入权与独立性</h2>
    <div class="sub">生产模型<strong>只能提交</strong>（<code>SUBMITTED_FOR_QA</code>），
      <strong>无权写「通过」</strong>——写出 COMPLETED 会被拒绝（<code>WRITE_AUTHORITY_VIOLATION</code>）。
      通过只能由<strong>另一个模型</strong>经 <code>tools/qa_verdict.py</code> 写入。
      <strong>看板的「通过」只认后面这一种。</strong></div>
    <div class="pprogress">已提交 <b>{qa.get('submitted', 0)}</b> ·
      QA 通过 <b>{qa.get('passed', 0)}</b> ·
      等待 QA <b>{qa.get('awaiting', 0)}</b> ·
      QA 不通过 <b>{qa.get('failed', 0)}</b></div>
    <table>
      <thead><tr><th>Gate</th><th>步骤</th><th>QA 状态</th><th>生产模型</th><th>QA 模型</th><th>时间</th></tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
  </section>"""


#: Shared by both the live and the static page: filtering rows by verdict.
#: Filters, not sorts - the question is always "what is still outstanding", and a
#: filter answers it without reordering the protocol. The choice rides in the URL
#: hash so it survives the 5-second auto-reload.
_FILTER_SCRIPT = """
    var FILTERS = {
      all: function () { return true; },
      open: function (v) { return v === 'todo' || v === 'wait' || v === 'warn'; },
      ok: function (v) { return v === 'ok'; },
      bad: function (v) { return v === 'bad'; }
    };
    var rows = [].slice.call(document.querySelectorAll('#steps tbody tr.srow'));
    var empty = document.getElementById('empty');
    function applyFilter(name) {
      var test = FILTERS[name] || FILTERS.all;
      var shown = 0;
      rows.forEach(function (tr) {
        var show = test(tr.getAttribute('data-verdict'));
        tr.classList.toggle('hidden', !show);
        if (show) { shown++; }
      });
      if (empty) { empty.hidden = shown > 0; }
      [].forEach.call(document.querySelectorAll('.fbtn'), function (b) {
        b.classList.toggle('on', b.getAttribute('data-filter') === name);
      });
    }
    [].forEach.call(document.querySelectorAll('.fbtn'), function (b) {
      b.addEventListener('click', function () {
        var name = b.getAttribute('data-filter');
        applyFilter(name);
        location.hash = name;
      });
    });
    var current = location.hash.slice(1);
    if (current && FILTERS[current]) { applyFilter(current); }
"""


def _verdict_pill(step_row: dict, qa_row: dict) -> tuple[str, str]:
    """One word for where a step actually stands. This is the point of the page."""
    verdict = step_row.get("verdict")
    if verdict == step_audit.NOT_CLAIMED:
        return "未做", "todo"
    if verdict == step_audit.CLAIMED_NO_EVIDENCE:
        return "无实证", "bad"
    if verdict == step_audit.CLAIMED_NO_READ:
        return "未读协议", "warn"
    if verdict == step_audit.EXTRA:
        return "链外", "warn"
    if step_row.get("qa_failed") or qa_row.get("state") == "QA_FAILED":
        return "QA 不通过", "bad"
    if step_row.get("qa_passed"):
        return "通过", "ok"
    return "等待 QA", "wait"


def _step_row_html(row: dict) -> str:
    """One step, Gate first.

    The Gate is what the protocol calls this step, so it leads. The Skill id is
    still there but demoted to a tooltip and a footnote line - a person reading
    the board wants "G3 资产锁定 / 资产映射与最小必要路线", not
    `short-drama-asset-router`.
    """
    gate_cell = (
        f'<span class="gate">{escape(row["gate_letters"])}</span>'
        f'<div class="gname">{escape(row["gate_name"])}</div>'
        if row["gate_letters"] else '<span class="dim">链外</span>'
    )
    skill_cell = (
        f'<div class="sname">{escape(row["skill_name"])}'
        + ('<span class="alt" title="三个提交适配是三选一，本次只会用一个">三选一</span>'
           if row["alternative"] else "")
        + "</div>"
        f'<div class="sid" title="{escape(row["step"])}">{escape(row["step"])}</div>'
    )
    who = ""
    if row["producer"] or row["qa_actor"]:
        who = (f'<span class="who">{escape(row["producer"] or "—")}</span>'
               f'<span class="arrow">→</span>'
               f'<span class="who">{escape(row["qa_actor"] or "—")}</span>')
    else:
        who = '<span class="dim">—</span>'
    detail = ""
    if row["note"] or row["evidence"]:
        detail = (
            '<div class="detail">'
            + (f'<div class="note">{escape(row["note"])}</div>' if row["note"] else "")
            + (f'<div class="ev"><span class="evk">证据</span>'
               f'<code>{escape(row["evidence"])}</code></div>' if row["evidence"] else "")
            + (f'<div class="ev"><span class="evk">时间</span>'
               f'<code>{escape(row["at"][:19])}</code></div>' if row["at"] else "")
            + "</div>"
        )
    return (
        f'<tr class="srow {row["cls"]}" data-verdict="{escape(row["cls"])}">'
        f'<td class="cgate">{gate_cell}</td>'
        f'<td class="cskill">{skill_cell}{detail}</td>'
        f'<td class="cwho">{who}</td>'
        f'<td class="cvp"><span class="vp {row["cls"]}">{escape(row["label"])}</span></td>'
        "</tr>"
    )


def _unified_step_rows(summary: dict) -> list[dict]:
    """Merge the reconciliation and the QA verdict into one row per step.

    These were two tables saying overlapping things. A step's story is one line:
    was it done, by whom, was it proofed, by whom, and does anything back it up.
    Everything else on the page was noise around that line.

    Each row carries the Gate it belongs to and a Chinese name for the Skill,
    because the raw Skill id (`short-drama-production-router`) told the user
    nothing about where in the protocol they were. The Gate is the label the
    protocol itself uses, so that is what leads.
    """
    audit_rows = summary.get("audit", {}).get("steps", {}).get("rows") or []
    qa_rows = {row["step"]: row for row in (summary.get("qa_passes") or {}).get("rows") or []}
    out = []
    for row in audit_rows:
        step = row["step"]
        qa_row = qa_rows.get(step, {})
        label, cls = _verdict_pill(row, qa_row)
        note = ""
        if row.get("missing_reads"):
            note = "未记录读取：" + "、".join(row["missing_reads"])
        elif row["verdict"] == step_audit.CLAIMED_NO_EVIDENCE:
            note = "证据文件不存在"
        elif row["verdict"] == step_audit.EXTRA:
            note = "协议声明的链里没有这一步"
        elif row["verdict"] == step_audit.NOT_CLAIMED:
            note = "协议要求这一步，轨迹里没有它"
        gate_letters = gate_map.gates_for(step, row.get("modes"))
        out.append({
            "step": step,
            "gate_letters": gate_map.gate_badge(step, row.get("modes")),
            "gate": gate_map.annotated_gate(step, row.get("modes")) or row.get("gate", ""),
            "gate_name": gate_map.GATE_NAMES.get(gate_letters[0], "") if gate_letters else "",
            "skill_name": gate_map.skill_label(step),
            "alternative": gate_map.is_alternative(step),
            "producer": row.get("actor", ""), "qa_actor": qa_row.get("qa_actor", ""),
            "label": label, "cls": cls, "note": note,
            "evidence": row.get("evidence", ""), "at": row.get("at", ""),
        })
    return out


def render_html(summary: dict, *, live: bool = False, siblings: list[dict] | None = None,
                project_meta: dict | None = None, all_runs_link: str = "") -> str:
    """One segment, step by step: what it read, what it produced, where it is.

    This is the primary view when serving live - the user watching a run wants the
    segment in front of them, not a table of twenty. Other segments are reachable
    from the picker without leaving the page.
    """
    siblings = siblings or []
    meta = project_meta or {}
    segment_title = summary.get("segment_title") or summary.get("segment") or summary["run_id"]

    options = "".join(
        f'<option value="{escape(row.get("run_id",""))}"'
        f'{" selected" if row.get("run_id") == summary["run_id"] else ""}>'
        f'{escape(row.get("segment_title") or row.get("segment") or row.get("run_id",""))}'
        f'{" · " + escape(row.get("state_label") or "") if row.get("state_label") else ""}</option>'
        for row in siblings
    )
    toolbar = (
        f"""
  <div class="toolbar">
    <label>查看段：
      <select onchange="location.href='/?run='+encodeURIComponent(this.value)">{options}</select>
    </label>
    <button type="button" onclick="location.reload()">🔄 立即刷新</button>
    <label><input type="checkbox" id="auto" checked> 自动刷新（每 5 秒）</label>
    <span class="dim">刷新只重新读取磁盘上的轨迹，<strong>不会重启服务、不会清空进度</strong></span>
    <span class="dim">本次渲染：{escape(summary['generated_at'])}</span>
  </div>
  <script>
    var box = document.getElementById('auto');
    var timer = null;
    function applyAuto() {{
      if (timer) {{ clearTimeout(timer); timer = null; }}
      if (box && box.checked) {{ timer = setTimeout(function () {{ location.reload(); }}, 5000); }}
    }}
    if (box) {{ box.addEventListener('change', applyAuto); applyAuto(); }}
{_FILTER_SCRIPT}
</script>
"""
        if live
        else f"""
  <div class="toolbar">
    <span>这是<b>静态快照</b>：切换段落与刷新按钮不会生效（静态文件没有后端，点了会报 AccessDenied）。
      表格下方的筛选按钮仍然可用。</span>
  </div>
  <div class="toolbar">
    <span class="dim">要看实时进度并在段之间来回切换，双击 <code>启动-运行总表.cmd</code>，
      或运行：<code>python tools\\render_run_report.py &lt;项目目录&gt; --serve</code></span>
  </div>
  <script>
{_FILTER_SCRIPT}
  </script>
"""
    )

    rows = _steps_html(summary)
    compliance = summary["compliance"]
    problems = "".join(f"<li>{escape(e)}</li>" for e in compliance.get("errors", []))
    problem_block = (
        f'<div class="problems"><h2>合规问题（{len(compliance["errors"])}）</h2><ul>{problems}</ul></div>'
        if compliance.get("errors")
        else '<div class="clean">合规检查通过：每一步都记录了 Skill、证据与必需的协议读取。</div>'
    )
    pending = "".join(
        f"<li><b>{escape(gate_map.gate_badge(s) or '链外')}</b> "
        f"{escape(gate_map.skill_label(s))} <code>{escape(s)}</code></li>"
        for s in summary["pending"]
    )
    pending_block = f'<div class="pending"><h2>尚未执行（{len(summary["pending"])}）</h2><ul>{pending}</ul></div>' if summary["pending"] else ""
    halt = (
        f'<div class="halt"><strong>等待决定：</strong>{escape(summary["pending_decision"])}</div>'
        if summary.get("pending_decision")
        else ""
    )
    not_started_block = (
        f'<div class="notstarted"><h2>这一段还没有开始生产</h2>'
        f'<p>段清单里已经有 <code>{escape(summary["run_id"])}</code>，但轨迹文件 '
        f'<code>workflow/runs/{escape(summary["run_id"])}.json</code> 还没创建。'
        f'这不是错误——等 Agent 起这一段（<code>tools/start_run.py</code>）之后，'
        f'这里会自动出现逐步明细。</p></div>'
        if summary.get("not_started")
        else ""
    )
    progress_pct = 0 if not summary["progress"]["total"] else round(
        100 * summary["progress"]["completed"] / summary["progress"]["total"]
    )
    unified = _unified_step_rows(summary)
    declared_total = (summary.get("audit", {}).get("steps", {}) or {}).get("declared_total", 0)
    offchain = [r["step"] for r in unified if r["label"] == "链外"]
    offchain_total = len(offchain)
    total_rows = len(unified)
    passes = summary.get("qa_passes") or {}
    hb = meta.get("reporting") or {}
    hb_level = escape(hb.get("level") or "")
    strip_bits = [
        f'已提交 <b>{passes.get("submitted", 0)}</b>',
        f'QA 通过 <b class="{"ok" if passes.get("passed") else ""}">{passes.get("passed", 0)}</b>',
        f'等待 QA <b>{passes.get("awaiting", 0)}</b>',
    ]
    if passes.get("failed"):
        strip_bits.append(f'<span class="bad">QA 不通过 <b>{passes["failed"]}</b></span>')
    if offchain_total:
        strip_bits.append(f'<span class="warn">链外步骤 <b>{offchain_total}</b></span>')
    strip_bits.append(f'最后回传 <b class="{hb_level}">{escape(hb.get("label") or "从未回传")}</b>')
    strip = ' <span class="sep">·</span> '.join(strip_bits)

    rows_html = "".join(_step_row_html(r) for r in unified)
    offchain_note = (
        '<div class="quiet">链外步骤（协议未声明，已计入进度，需要确认是否替换了协议步骤）：'
        + "、".join(f"<code>{escape(s)}</code>" for s in offchain) + "</div>"
        if offchain else ""
    )
    status_cls = {"SUBMITTED_FOR_QA": "wait", "BLOCKED": "bad", "FAILED": "bad",
                  "COMPLETED": "ok", "WAITING_APPROVAL": "warn"}.get(summary["status"], "")

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
  .verdict {{ font-weight:600; }}
  .verdict.ok {{ color:#1a7f37; }}
  .verdict.bad {{ color:#cf222e; }}
  .verdict.warn {{ color:#bf8700; }}
  .pprogress {{ font-size:13.5px; margin:6px 0 10px; }}
  .strip {{ border:1px solid var(--line); border-radius:10px; padding:10px 14px; margin-bottom:16px;
            background:var(--card); font-size:13.5px; }}
  .strip .sep {{ color:var(--muted); }}
  .strip b.ok {{ color:#1a7f37; }} .strip b.stale {{ color:#cf222e; }} .strip b.none {{ color:#bf8700; }}
  .strip .bad {{ color:#cf222e; }} .strip .warn {{ color:#bf8700; }}
  .pill {{ font-size:12px; font-weight:400; padding:2px 8px; border-radius:999px;
           border:1px solid var(--line); color:var(--muted); vertical-align:middle; }}
  .pill.wait, .pill.warn {{ color:#bf8700; border-color:#bf8700; }}
  .pill.bad {{ color:#cf222e; border-color:#cf222e; }}
  .pill.ok {{ color:#1a7f37; border-color:#1a7f37; }}
  table.steps td {{ vertical-align:top; }}
  .tablehead {{ display:flex; gap:16px; align-items:flex-start; justify-content:space-between;
                flex-wrap:wrap; margin-bottom:10px; }}
  .tablehead .sub {{ margin-bottom:0; max-width:620px; }}
  .filters {{ display:flex; gap:6px; flex:none; }}
  .fbtn {{ font:inherit; font-size:12.5px; padding:4px 12px; border-radius:999px; cursor:pointer;
           border:1px solid var(--line); background:var(--bg); color:var(--muted); }}
  .fbtn:hover {{ border-color:var(--fg); color:var(--fg); }}
  .fbtn.on {{ background:var(--fg); border-color:var(--fg); color:var(--bg); font-weight:600; }}
  table.steps {{ width:100%; border-collapse:collapse; font-size:13.5px; }}
  table.steps th {{ text-align:left; font-weight:600; font-size:12px; color:var(--muted);
                    padding:0 12px 8px; border-bottom:1px solid var(--line); white-space:nowrap; }}
  table.steps td {{ padding:10px 12px; border-bottom:1px solid var(--line); }}
  table.steps tr.srow:hover {{ background:var(--card); }}
  table.steps tr.hidden {{ display:none; }}
  .cgate {{ width:132px; }} .cskill {{ }} .cwho {{ width:190px; }}
  .cvp {{ width:92px; text-align:right; }}
  .gate {{ font-weight:700; font-size:14px; letter-spacing:.3px; }}
  .gname {{ font-size:11.5px; color:var(--muted); margin-top:1px; }}
  .sname {{ font-weight:500; }}
  .alt {{ display:inline-block; margin-left:6px; padding:1px 6px; border-radius:999px; font-size:10.5px;
          font-weight:400; color:var(--muted); border:1px dashed var(--line); vertical-align:1px; }}
  .sid {{ font-size:11px; color:var(--muted); font-family:ui-monospace, Consolas, monospace;
          margin-top:1px; word-break:break-all; }}
  .who {{ font-family:ui-monospace, Consolas, monospace; font-size:12px; }}
  .arrow {{ color:var(--muted); margin:0 5px; font-size:11px; }}
  .detail {{ margin-top:5px; }}
  .ev {{ font-size:11.5px; color:var(--muted); margin-top:2px; }}
  .evk {{ display:inline-block; min-width:30px; }}
  .ev code {{ font-size:11.5px; word-break:break-all; }}
  .empty {{ padding:24px; text-align:center; color:var(--muted); font-size:13.5px; }}
  .vp {{ font-weight:500; white-space:nowrap; }}
  .vp.ok {{ color:#1a7f37; }} .vp.bad {{ color:#cf222e; }}
  .vp.warn, .vp.wait {{ color:#bf8700; }}
  .vp.todo {{ color:var(--muted); }}
  .note {{ font-size:12px; color:var(--muted); margin-top:2px; }}
  .evidence {{ font-size:12px; word-break:break-all; max-width:230px; }}
  .quiet {{ font-size:12.5px; color:var(--muted); margin:8px 0 16px; }}
  details.more {{ margin-top:22px; border-top:1px solid var(--line); padding-top:12px; }}
  details.more summary {{ cursor:pointer; color:var(--muted); font-size:13px; }}
  .verdict .dim {{ font-weight:400; }}
  .problems ul, .pending ul {{ margin:0; padding-left:20px; font-size:13.5px; }}
  .notstarted {{ margin-top:16px; padding:12px 14px; border-radius:10px; background:var(--card);
                 border:1px dashed var(--line); font-size:13.5px; }}
  .notstarted h2 {{ margin-bottom:6px; }}
  .heartbeat {{ border:1px solid var(--line); border-left:4px solid var(--hb,#6e7781); border-radius:10px;
                padding:10px 14px; margin-bottom:16px; background:var(--card); }}
  .heartbeat .hbline {{ display:flex; gap:12px; align-items:baseline; flex-wrap:wrap; }}
  .heartbeat.ok {{ --hb:#1a7f37; }}
  .heartbeat.stale {{ --hb:#cf222e; background:rgba(207,34,46,.10); }}
  .heartbeat.none {{ --hb:#bf8700; }}
  .heartbeat.idle {{ --hb:#6e7781; }}
  .heartbeat.stale strong {{ color:#cf222e; }}
  .heartbeat div {{ font-size:13px; }}
  .pstate {{ border:1px solid var(--line); border-radius:10px; padding:12px 14px; margin:16px 0; background:var(--card); }}
  .pstate h2 {{ margin-bottom:6px; }}
  .psfacts {{ display:flex; gap:14px; flex-wrap:wrap; font-size:13px; margin-bottom:8px; }}
  .psbox h3 {{ font-size:13px; margin-top:8px; color:var(--muted); }}
  .psbox ul {{ margin:4px 0 0; padding-left:20px; font-size:13px; }}
  .psrow {{ display:flex; gap:10px; font-size:12.5px; margin-top:4px; }}
  .psrow span {{ color:var(--muted); flex:none; }}
  .halt {{ margin-top:16px; padding:10px 14px; border-radius:10px; background:rgba(154,103,0,.12);
           border:1px solid rgba(154,103,0,.4); }}
  .toolbar {{ display:flex; align-items:center; gap:14px; flex-wrap:wrap; margin-bottom:16px;
              padding:10px 14px; background:var(--card); border:1px solid var(--line); border-radius:10px; }}
  .toolbar button {{ font:inherit; font-size:13.5px; padding:5px 14px; border-radius:8px; cursor:pointer;
                     border:1px solid var(--line); background:var(--bg); color:var(--fg); }}
  .toolbar select {{ font:inherit; font-size:13.5px; padding:4px 8px; border-radius:6px;
                     border:1px solid var(--line); background:var(--bg); color:var(--fg); max-width:320px; }}
  .toolbar label {{ font-size:13px; display:flex; align-items:center; gap:6px; }}
  footer {{ margin-top:28px; color:var(--muted); font-size:12px; }}
  code {{ font-family: ui-monospace, Consolas, monospace; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>{escape(segment_title)} <span class="pill {status_cls}">{escape(summary['status'] or '未开始')}</span></h1>
  <div class="sub">
    项目 <code>{escape(meta.get('project') or '-')}</code>
    · 集 {escape(meta.get('episode') or '-')} · 段 <code>{escape(summary.get('segment') or summary['run_id'])}</code>
    · 运行 <code>{escape(summary['run_id'])}</code>
  </div>

  {toolbar}

  <div class="strip">{strip}</div>

  {halt}
  {not_started_block}

  <div class="tablehead">
    <div>
      <h2>协议步骤 <span class="dim">G0–G8 · 声明 {declared_total} 项 · 链外 {offchain_total} 项</span></h2>
      <div class="sub">按 Gate 顺序看一行就够：<strong>Gate</strong> 是协议里的步骤名，
        <strong>步骤</strong>是执行它的 Skill，<strong>结论</strong>是它现在到底算不算完成。
        <strong>只有独立 QA 写过「通过」才算通过</strong>；生产模型的「已提交」不算。</div>
    </div>
    <div class="filters" role="group" aria-label="按结论过滤">
      <button type="button" class="fbtn on" data-filter="all">全部</button>
      <button type="button" class="fbtn" data-filter="open">待办</button>
      <button type="button" class="fbtn" data-filter="ok">已通过</button>
      <button type="button" class="fbtn" data-filter="bad">有风险</button>
    </div>
  </div>
  <table class="steps" id="steps">
    <thead><tr><th class="cgate">Gate</th><th class="cskill">步骤</th><th class="cwho">生产 → QA</th><th class="cvp">结论</th></tr></thead>
    <tbody>{rows_html}</tbody>
  </table>
  <div class="empty" id="empty" hidden>当前筛选下没有步骤。</div>
  {offchain_note}

  <details class="more">
    <summary>展开：合规检查 / 尚未执行 / 产出文件</summary>
    {problem_block}
    {pending_block}
  </details>

  <footer>
    {'全部段一览：<a href="/overview">/overview</a> · ' if live else ''}
    <code>workflow/runs/{escape(summary['run_id'])}.json</code> · 渲染于 {escape(summary['generated_at'])}
  </footer>
</div>
</body>
</html>
"""


def build_report(run_state_path: str | Path, chain: dict | None = None, manifest: dict | None = None) -> dict:
    run_file = Path(run_state_path)
    state = json.loads(run_file.read_text(encoding="utf-8"))
    if manifest is None:
        manifest_path = run_file.with_name("protocol_manifest.json")
        if manifest_path.is_file():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    # <project>/workflow/runs/<id>.json -> <project>
    project_root = run_file.parent.parent.parent if run_file.parent.name == "runs" else None
    return summarize(state, chain, manifest, project_root)


def resolve_input(path_str: str) -> tuple[str, Path | None, Path | None]:
    """Decide what the user pointed at: a project folder, an index, or one run.

    Accepting all three means there is one command to remember, and it always
    works whether you are looking at a segment or the whole episode.
    """
    path = Path(path_str)
    if path.is_dir():
        for candidate in (path / "workflow" / "run_index.json", path / "run_index.json",
                          path / "workflow" / "segments.json", path / "segments.json"):
            if candidate.is_file():
                return "project", candidate, candidate.parent.parent if candidate.parent.name == "workflow" else candidate.parent
        return "unknown", None, None
    if path.name in ("run_index.json", "segments.json"):
        root = path.parent.parent if path.parent.name == "workflow" else path.parent
        return "project", path, root
    if path.is_file():
        return "run", path, path.parent
    return "unknown", None, None


def main() -> int:
    import argparse

    from . import run_index

    parser = argparse.ArgumentParser(
        description="Render a readable report from a run_state.json, a run_index.json, or a project folder."
    )
    parser.add_argument("target", help="项目目录 / workflow/run_index.json / 单个 run_state.json")
    parser.add_argument("--html", help="write a self-contained HTML report to this path")
    parser.add_argument("--json", action="store_true", help="print the summary as JSON instead of text")
    parser.add_argument("--no-details", action="store_true", help="skip per-step detail for each segment")
    parser.add_argument("--serve", action="store_true",
                        help="启动本地实时服务（刷新按钮/自动刷新会重新读取磁盘）")
    parser.add_argument("--port", type=int, default=8765, help="--serve 使用的端口（默认 8765）")
    parser.add_argument("--no-open", action="store_true", help="--serve 时不自动打开浏览器")
    args = parser.parse_args()

    kind, target, root = resolve_input(args.target)
    if kind == "unknown":
        print(f"无法识别输入：{args.target}")
        print("可指向：项目目录、workflow/run_index.json、或某个 run_state.json")
        return 2

    if args.serve:
        from .run_server import serve

        project_root = root if kind == "project" else Path(args.target)
        httpd = serve(project_root, args.port, open_browser=not args.no_open)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n已停止。")
        finally:
            httpd.server_close()
        return 0

    if kind == "project":
        # One read path for every consumer: on-disk runs + the user's segment list.
        # Reading the index file directly was why the static export showed fewer
        # rows than the live page.
        index = run_index.project_index(root)
        view = summarize_project(index, root, with_details=not args.no_details)
        payload = view
        text = render_project_text(view)
        page = render_project_html(view)
    else:
        summary = build_report(target)
        payload = summary
        text = render_text(summary)
        page = render_html(summary)

    if args.html:
        out = Path(args.html)
        out.write_text(page, encoding="utf-8")
        print(f"html report written: {out}")
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif not args.html:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
