"""Atomic JSON task state persistence."""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path

def write_task(path: str | Path, state: dict) -> None:
    target=Path(path); target.parent.mkdir(parents=True, exist_ok=True); state={**state,"updated_at":datetime.now(timezone.utc).isoformat()}
    tmp=target.with_suffix(target.suffix+".tmp"); tmp.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding="utf-8"); tmp.replace(target)

def read_task(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))

