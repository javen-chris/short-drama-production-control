"""Thin CLI wrapper: render a human-readable report from a run_state.json.

    python tools/render_run_report.py <run_state.json> [--html report.html]
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from production_control.run_report import (  # noqa: E402
    build_report,
    main,
    render_html,
    render_project_html,
    render_project_text,
    render_text,
    resolve_input,
    summarize,
    summarize_project,
)

__all__ = [
    "build_report",
    "main",
    "render_html",
    "render_project_html",
    "render_project_text",
    "render_text",
    "resolve_input",
    "summarize",
    "summarize_project",
]


if __name__ == "__main__":
    raise SystemExit(main())
