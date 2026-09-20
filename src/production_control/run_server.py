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
    """Read the project from disk and build the overview. No caching, on purpose."""
    root = Path(project_root)
    index = run_index.load_index(root)
    index = run_index.sync_index(root, index)
    return summarize_project(index, root, with_details=with_details)


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
            try:
                if path in ("/", "/index.html"):
                    html = render_project_html(current_view(root), live=True)
                    self._send(200, "text/html; charset=utf-8", html.encode("utf-8"))
                elif path == "/data":
                    body = json.dumps(current_view(root), ensure_ascii=False).encode("utf-8")
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

    return Handler


def serve(project_root: str | Path, port: int = 8765, *, open_browser: bool = True) -> ThreadingHTTPServer:
    root = Path(project_root)
    if not (root / "workflow" / "run_index.json").is_file():
        raise SystemExit(
            f"没有找到 {root / 'workflow' / 'run_index.json'}：该项目还没有运行轨迹。"
            "先用编排器跑一段（orchestrator.start(project_root=...)）再来查看。"
        )
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(root))
    url = f"http://127.0.0.1:{port}/"
    print(f"运行总表（实时）：{url}")
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
