"""Serve the run report locally so the refresh button returns current state.

A static HTML file cannot read the project folder - browsers block it. Serving
from 127.0.0.1 removes that limit: every request re-reads workflow/run_index.json
and the segment files, so refreshing always shows what is actually on disk, even
mid-run.

    python -m production_control.run_server <项目目录> [--port 8765] [--no-open]

Routes:
    /                  episode overview (re-rendered per request)
    /data              the same view as JSON
    /run/<run_id>      one segment, step by step
    /run/<run_id>/data that segment as JSON

Binds to 127.0.0.1 only. Standard library only.
"""
from __future__ import annotations

import json
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

from . import run_index
from .run_report import (
    build_report,
    render_html,
    render_project_html,
    render_project_text,
    render_text,
    summarize_project,
)


def current_view(project_root: str | Path, *, with_details: bool = True) -> dict:
    """Read the project from disk and build the overview. No caching, on purpose.

    Merges two sources: the segment trace files (state) and the user's segment
    list (names). Filling in the list on the page immediately shows the rows.
    """
    root = Path(project_root)
    index = run_index.load_index(root)
    index = run_index.sync_index(root, index)
    document = run_index.load_segments(root)
    if document.get("segments"):
        index = run_index.apply_segments(index, document)
    view = summarize_project(index, root, with_details=with_details)
    view["segments"] = document.get("segments", [])
    view["segments_source"] = str(run_index.segments_path(root))
    return view


def make_handler(project_root: str | Path):
    root = Path(project_root)

    class Handler(BaseHTTPRequestHandler):
        server_version = "ShortDramaRunReport/1.0"

        def _send(self, code: int, content_type: str, payload: bytes) -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self) -> None:  # noqa: N802 - stdlib naming
            path = unquote(self.path.split("?", 1)[0])
            query = self.path.split("?", 1)[1] if "?" in self.path else ""
            requested = ""
            for part in query.split("&"):
                if part.startswith("run="):
                    requested = unquote(part[4:])
            try:
                if path in ("/", "/index.html"):
                    # Primary view: the segment in progress, or the one asked for.
                    view = current_view(root)
                    rows = {row["run_id"]: row for row in view["runs"]}
                    target = requested or view.get("active_run_id") or (view["runs"][0]["run_id"] if view["runs"] else "")
                    if not target:
                        self._send(200, "text/html; charset=utf-8",
                                   render_project_html(view, live=True).encode("utf-8"))
                        return
                    run_file = run_index.run_path(root, target)
                    if run_file.is_file():
                        summary = build_report(run_file)
                    else:
                        summary = {
                            "run_id": target, "contract_id": "", "segment": rows.get(target, {}).get("segment", ""),
                            "segment_title": rows.get(target, {}).get("segment_title", ""), "status": "",
                            "pending_decision": "", "current_step": "", "steps": [], "pending": [],
                            "progress": {"completed": 0, "total": 0},
                            "compliance": {"status": "NOT_STARTED", "errors": []},
                            "generated_at": view["generated_at"],
                        }
                    page = render_html(summary, live=True, siblings=view["runs"],
                                       project_meta={"project": view["project"], "series": view["series"],
                                                     "episode": view["episode"]})
                    self._send(200, "text/html; charset=utf-8", page.encode("utf-8"))
                elif path in ("/overview", "/all"):
                    html = render_project_html(current_view(root), live=True)
                    self._send(200, "text/html; charset=utf-8", html.encode("utf-8"))
                elif path == "/data":
                    body = json.dumps(current_view(root), ensure_ascii=False).encode("utf-8")
                    self._send(200, "application/json; charset=utf-8", body)
                elif path == "/api/segments":
                    document = run_index.load_segments(root)
                    body = json.dumps(document, ensure_ascii=False).encode("utf-8")
                    self._send(200, "application/json; charset=utf-8", body)
                elif path == "/text":
                    text = render_project_text(current_view(root)).encode("utf-8")
                    self._send(200, "text/plain; charset=utf-8", text)
                elif path.startswith("/run/"):
                    rest = path[len("/run/"):]
                    run_id, _, tail = rest.partition("/")
                    run_file = run_index.run_path(root, run_id)
                    if not run_file.is_file():
                        self._send(404, "text/plain; charset=utf-8", f"unknown run: {run_id}".encode("utf-8"))
                        return
                    if tail == "data":
                        summary = build_report(run_file)
                        self._send(200, "application/json; charset=utf-8",
                                   json.dumps(summary, ensure_ascii=False).encode("utf-8"))
                    else:
                        summary = build_report(run_file)
                        self._send(200, "text/html; charset=utf-8", render_html(summary).encode("utf-8"))
                elif path == "/health":
                    self._send(200, "application/json; charset=utf-8", b'{"status":"ok"}')
                else:
                    self._send(404, "text/plain; charset=utf-8", b"not found")
            except Exception as exc:  # keep the server alive; report the failure
                message = f"render failed: {exc}".encode("utf-8")
                self._send(500, "text/plain; charset=utf-8", message)

        def log_message(self, *args) -> None:  # quiet console
            return

        def do_POST(self) -> None:  # noqa: N802 - stdlib naming
            """Accept the user's segment list from the page.

            This is the one write path: the user edits names/notes on the page and
            saves, and the same file the agent reads is what gets written. Bound to
            127.0.0.1, so only this machine can reach it.
            """
            path = unquote(self.path.split("?", 1)[0])
            if path != "/api/segments":
                self._send(404, "text/plain; charset=utf-8", b"not found")
                return
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                document = json.loads(raw.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                payload = json.dumps({"ok": False, "error": f"JSON 解析失败：{exc}"}, ensure_ascii=False)
                self._send(400, "application/json; charset=utf-8", payload.encode("utf-8"))
                return
            try:
                saved = run_index.save_segments(root, document)
                index = run_index.load_index(root)
                index = run_index.sync_index(root, index)
                index = run_index.apply_segments(index, run_index.load_segments(root))
                run_index.save_index(root, index)
            except (ValueError, OSError) as exc:
                payload = json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
                self._send(400, "application/json; charset=utf-8", payload.encode("utf-8"))
                return
            payload = json.dumps(
                {"ok": True, "path": str(saved), "segments": run_index.load_segments(root)["segments"]},
                ensure_ascii=False,
            )
            self._send(200, "application/json; charset=utf-8", payload.encode("utf-8"))

    return Handler


def port_candidates(preferred: int, auto_port: bool = True) -> list[int]:
    """Ports to try, in order. 0 means 'any free port' and is never walked."""
    if not auto_port or preferred == 0:
        return [preferred]
    return [preferred] + list(range(preferred + 1, preferred + 11))


def serve(project_root: str | Path, port: int = 8765, *, open_browser: bool = True,
          auto_port: bool = True) -> ThreadingHTTPServer:
    """Start the local report server.

    auto_port walks forward if the preferred port is taken (a second window, or
    an earlier run left running), so double-clicking start twice still works
    instead of failing with "address already in use".
    """
    root = Path(project_root)
    if not (root / "workflow" / "run_index.json").is_file():
        raise SystemExit(
            f"没有找到 {root / 'workflow' / 'run_index.json'}：该项目还没有运行轨迹。"
            "先用编排器跑一段（orchestrator.start(project_root=...)）再来查看。"
        )
    candidates = port_candidates(port, auto_port)
    last_error: OSError | None = None
    httpd: ThreadingHTTPServer | None = None
    for candidate in candidates:
        try:
            httpd = ThreadingHTTPServer(("127.0.0.1", candidate), make_handler(root))
            port = candidate
            break
        except OSError as exc:
            last_error = exc
    if httpd is None:
        raise SystemExit(f"端口 {candidates[0]}–{candidates[-1]} 都被占用，无法启动：{last_error}")
    url = f"http://127.0.0.1:{port}/"
    print(f"运行总表（实时）：{url}")
    if port != candidates[0]:
        print(f"（{candidates[0]} 被占用，已自动改用 {port}）")
    print("刷新按钮与自动刷新都会重新读取磁盘；Ctrl+C 结束服务。")
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    return httpd


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Serve the run report locally (live refresh).")
    parser.add_argument("project_root")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-open", action="store_true", help="do not open a browser")
    args = parser.parse_args(argv)
    httpd = serve(args.project_root, args.port, open_browser=not args.no_open)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
