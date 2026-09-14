from __future__ import annotations
import re
from pathlib import Path
SECRET=re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*['\"][^'\"]+['\"]")
MEDIA={".mp4",".mov",".mkv",".wav",".mp3",".png",".jpg",".jpeg",".webp"}
def scan(root: str|Path)->list[str]:
    errors=[]
    for p in Path(root).rglob("*"):
        if not p.is_file() or ".git" in p.parts: continue
        if p.suffix.lower() in MEDIA: errors.append(f"media file tracked: {p.relative_to(root)}")
        if p.suffix.lower() in {".py",".json",".yml",".yaml",".md",".toml"}:
            try:
                if SECRET.search(p.read_text(encoding="utf-8")): errors.append(f"possible secret: {p.relative_to(root)}")
            except UnicodeDecodeError: pass
    return errors

