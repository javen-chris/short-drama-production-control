"""Thin CLI wrapper: the real implementation lives in the installable package.

Keeping it here preserves the documented command
    python tools/protocol_fingerprint.py generate
while letting tests and CI import production_control.protocol_fingerprint
without depending on the caller's working directory.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from production_control.protocol_fingerprint import (  # noqa: E402
    CHALLENGE_BANK,
    CHALLENGE_SAMPLE,
    DEFAULT_ROOT,
    REQUIRED_CORE_FILES,
    build_manifest,
    check,
    generate,
    main,
    manifest_path,
    normalize,
    sha256_file,
)

__all__ = [
    "CHALLENGE_BANK",
    "CHALLENGE_SAMPLE",
    "DEFAULT_ROOT",
    "REQUIRED_CORE_FILES",
    "build_manifest",
    "check",
    "generate",
    "main",
    "manifest_path",
    "normalize",
    "sha256_file",
]


if __name__ == "__main__":
    raise SystemExit(main())
