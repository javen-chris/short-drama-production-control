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

from . import run_index
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
    return {
        "run_id": state.get("run_id", ""),
        "contract_id": state.get("contract_id", ""),
        "segment": state.get("segment", ""),
        "segment_title": state.get("segment_title", ""),
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
    "WAITING_APPROVAL": "等待批准",
    "PAUSED_EXCEPTION": "已挂起",
    "BLOCKED": "已阻断",
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
            candidate = root / (row.get("path") or "")
            if candidate.is_file():
                try:
                    item["detail"] = summarize(json.loads(candidate.read_text(encoding="utf-8")))
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


def render_project_html(view: dict, *, live: bool = False) -> str:
    """Episode-wide page: every segment on one screen, expandable to per-step detail.

    live=True is served by run_server: the page re-reads disk on every request, so
    the refresh button and auto-refresh always show current state. A static export
    (live=False) is a snapshot and says so.
    """
    counts = view["counts"]
    cards = "".join(
        f'<div class="card"><div class="k">{label}</div><div class="v">{value}</div></div>'
        for label, value in (
            ("段数", counts["total"]),
            ("已完成", counts["completed"]),
            ("进行中", counts["running"]),
            ("等待批准", counts["waiting"]),
            ("挂起 / 阻断", counts["blocked"]),
            ("未开始", counts["not_started"]),
        )
    )

    active = next((r for r in view["runs"] if r["active"]), None)
    if active:
        active_name = active.get("segment_title") or active.get("segment") or active.get("run_id", "")
        active_line = (
            f"<strong>{escape(active_name)}</strong> "
            f'<span class="dim">{escape(active["run_id"])} · {escape(active["state_label"])} · '
            f'{escape(active.get("current_step", "") or "-")}</span>'
        )
    else:
        active_line = '<span class="dim">尚无进行中的段</span>'
    live_hint = "实时模式：每次刷新都重新读取磁盘上的最新状态" if live else "静态快照：数据为生成时状态，需重新运行命令才会更新"
    auto_checked = "checked" if live else ""

    reporting = view.get("reporting") or reporting_state(view.get("idle_minutes"))
    heartbeat = heartbeat_block(reporting, view.get("newest_event_at", ""))
    state_card = project_state_block(view.get("project_state") or {})
    heading = " · ".join(x for x in (view["series"], view["episode"]) if x) or view["project"]
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
        detail = ""
        if row.get("detail"):
            detail = (
                '<details class="more"><summary>展开该段逐步明细（'
                f"{row['detail']['progress']['completed']}/{row['detail']['progress']['total']} 步）</summary>"
                f"{''.join(_steps_html(row['detail']))}</details>"
            )
        decision = (
            f'<div class="reason">待决定：{escape(row.get("pending_decision", ""))}</div>'
            if row.get("pending_decision")
            else ""
        )
        rows.append(
            f"""
      <tr class="{'active' if row['active'] else ''}">
        <td class="rid">{'▶ ' if row['active'] else ''}<code>{escape(row.get('run_id',''))}</code>
          {f'<div class="title">{escape(row.get("segment_title",""))}</div>' if row.get("segment_title") else ''}</td>
        <td>{_badge(row.get('status','') or '', row['state_label'])}</td>
        <td><div class="bar"><i style="width:{row['percent']}%"></i></div><span class="dim">{row['percent']}%</span></td>
        <td><code class="dim">{escape(row.get('current_step','') or '-')}</code>{decision}</td>
        <td class="dim">{escape(row.get('last_event_at','') or '-')}</td>
      </tr>
      <tr class="detailrow"><td colspan="5">{detail}</td></tr>"""
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
  footer {{ margin-top:28px; color:var(--muted); font-size:12px; }}
  code {{ font-family: ui-monospace, Consolas, monospace; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>{escape(heading)} 运行总表</h1>
  <div class="sub">
    项目 <code>{escape(view['project'])}</code> · 系列 {escape(view['series'] or '-')} · 集 {escape(view['episode'] or '-')}
  </div>

  <div class="toolbar">{toolbar_controls}
    <span class="dim">本次渲染：{escape(view['generated_at'])}</span>
  </div>

  {heartbeat}

  <div class="cards">{cards}</div>

  <div class="now">当前进行到：{active_line}</div>
  {stale}
  {state_card}

  <table>
    <thead><tr><th>段 / 运行</th><th>状态</th><th>进度</th><th>当前步骤 / 待决定</th><th>最后事件</th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>

  {editor}

  <footer>
    数据来源：<code>{escape(view['data_source'] or 'workflow/run_index.json')}</code> ·
    索引更新：{escape(view['index_updated_at'] or '-')} · 最新段落事件：{escape(view['newest_event_at'] or '-')}<br>
    {'实时模式由本地服务提供；真实磁盘状态以 workflow/runs/ 下的段落文件为准。' if live else '刷新方式：重新执行渲染命令（无缓存，始终反映磁盘上的最新状态）。'}
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
  </script>
"""
        if live
        else """
  <div class="toolbar">
    <span>这是<b>静态快照</b>：切换段落与刷新按钮不会生效（静态文件没有后端，点了会报 AccessDenied）。</span>
  </div>
  <div class="toolbar">
    <span class="dim">要看实时进度并在段之间来回切换，双击 <code>启动-运行总表.cmd</code>，
      或运行：<code>python tools\\render_run_report.py &lt;项目目录&gt; --serve</code></span>
  </div>
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
    pending = "".join(f"<li><code>{escape(s)}</code></li>" for s in summary["pending"])
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
    heartbeat = heartbeat_block(meta.get("reporting") or {}, meta.get("newest_event_at", ""))
    state_card = project_state_block(meta.get("project_state") or {})

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
  <h1>{escape(segment_title)}</h1>
  <div class="sub">
    项目 <code>{escape(meta.get('project') or '-')}</code>
    · 系列 {escape(meta.get('series') or '-')} · 集 {escape(meta.get('episode') or '-')}
    · 段 <code>{escape(summary.get('segment') or summary['run_id'])}</code>
    · 运行 <code>{escape(summary['run_id'])}</code>
  </div>

  {toolbar}

  {heartbeat}
  {state_card}

  <div class="cards">
    <div class="card"><div class="k">状态</div><div class="v">{escape(summary['status'] or '-')}</div></div>
    <div class="card"><div class="k">进度</div><div class="v">{summary['progress']['completed']} / {summary['progress']['total']}</div>
      <div class="bar"><i style="width:{progress_pct}%"></i></div></div>
    <div class="card"><div class="k">合规</div><div class="v">{escape(compliance['status'])}</div></div>
    <div class="card"><div class="k">当前步骤</div><div class="v" style="font-size:14px">{escape(summary['current_step'] or '-')}</div></div>
  </div>

  {halt}
  {not_started_block}

  <h2>协议读取与执行过程（{len(summary['steps'])} 步）</h2>
  {''.join(rows)}

  {problem_block}
  {pending_block}

  <footer>
    {'全部段一览与段清单：<a href="/overview">/overview</a> · ' if live else ''}
    数据来源：<code>workflow/runs/{escape(summary['run_id'])}.json</code> · 渲染于 {escape(summary['generated_at'])}
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
