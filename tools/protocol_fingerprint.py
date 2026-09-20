"""Generate the protocol manifest that read-attestation is checked against.

The manifest pins every core protocol file to its sha256 and carries challenge
questions whose expected answers are stored only as salted-hash digests, so an
agent cannot copy answers out of the manifest - it has to actually read the
documents to answer them.

Usage:
    python tools/protocol_fingerprint.py generate [--root DIR] [--seed N]
    python tools/protocol_fingerprint.py check    [--root DIR]

`generate` writes protocol_manifest.json next to the protocol documents.
`check` re-verifies that no core file drifted after generation.
Standard library only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_ROOT = r"D:\AIGC短剧本地工作流规则及协议\短剧制作核心协议"

# Every file an agent must claim (and prove) it read before producing anything.
REQUIRED_CORE_FILES = [
    "00_自动化生产唯一入口.md",
    "核心自动化生产包/01_核心总则.md",
    "核心自动化生产包/02_任务路由与Gate.md",
    "核心自动化生产包/03_生产与资产规则.md",
    "核心自动化生产包/04_专项规则.md",
    "11_目标模式自动建卡与连续执行规则.md",
    "13_模型执行前硬门禁.md",
    "14_RH生图渠道与GPT通道现状.md",
    "16_生图渠道规则.md",
]

# Answers are normalized (trimmed, lowercased) before hashing.
CHALLENGE_BANK = [
    {"id": "image-model", "prompt": "本协议下生图唯一允许的图像模型是什么？", "expected": "gpt-image-2"},
    {"id": "image-fallback", "prompt": "订阅额度耗尽且已授权时的生图兜底通道枚举值是什么？", "expected": "gpt_image2_runninghub_workflow"},
    {"id": "degraded-route", "prompt": "复杂风险但未授权制作故事本时，生产单元走的路线枚举值是什么？", "expected": "degraded_direct"},
    {"id": "master-gate", "prompt": "角色/场景/道具 MASTER 缺失时，生产停在哪个 Gate？（如 G5）", "expected": "g3"},
    {"id": "tail-frame-blocking", "prompt": "首尾帧未授权制作时是否阻断生产？（是/否）", "expected": "否"},
    {"id": "max-submissions", "prompt": "一份合同授权的付费视频提交最多几次？（数字）", "expected": "1"},
]

CHALLENGE_SAMPLE = 3


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize(answer: str) -> str:
    return " ".join(answer.split()).strip().lower()


def build_manifest(root: Path, *, seed: int | None = None, files: list[str] | None = None,
                   bank: list[dict] | None = None) -> dict:
    root = Path(root)
    file_list = files if files is not None else REQUIRED_CORE_FILES
    bank = bank if bank is not None else CHALLENGE_BANK
    entries = []
    for rel in file_list:
        target = root / rel
        if not target.is_file():
            raise SystemExit(f"missing protocol file: {target}")
        entries.append({"path": rel, "sha256": sha256_file(target), "bytes": target.stat().st_size})
    fingerprint = hashlib.sha256(
        "\n".join(f"{e['path']}:{e['sha256']}" for e in entries).encode("utf-8")
    ).hexdigest()
    picks = random.Random(seed).sample(bank, min(CHALLENGE_SAMPLE, len(bank)))
    challenges = [
        {
            "id": item["id"],
            "prompt": item["prompt"],
            "answer_sha256": hashlib.sha256(normalize(item["expected"]).encode("utf-8")).hexdigest(),
        }
        for item in picks
    ]
    return {
        "manifest_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "protocol_root": str(root),
        "files": entries,
        "fingerprint": fingerprint,
        "challenges": challenges,
    }


def manifest_path(root: Path) -> Path:
    return Path(root) / "protocol_manifest.json"


def check(root: Path) -> list[str]:
    path = manifest_path(root)
    if not path.is_file():
        return [f"manifest not found: {path} (run generate first)"]
    manifest = json.loads(path.read_text(encoding="utf-8"))
    errors: list[str] = []
    for entry in manifest.get("files", []):
        target = Path(root) / entry["path"]
        if not target.is_file():
            errors.append(f"{entry['path']}: file missing")
        elif sha256_file(target) != entry["sha256"]:
            errors.append(f"{entry['path']}: changed since the manifest was generated - regenerate")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["generate", "check"])
    parser.add_argument("--root", default=DEFAULT_ROOT)
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()
    root = Path(args.root)
    if args.command == "generate":
        manifest = build_manifest(root, seed=args.seed)
        out = manifest_path(root)
        out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"manifest written: {out}")
        print(f"fingerprint: {manifest['fingerprint']}")
        print("challenges:")
        for item in manifest["challenges"]:
            print(f"  - {item['id']}: {item['prompt']}")
        return 0
    errors = check(root)
    if errors:
        print("DRIFTED:")
        for line in errors:
            print(f"  - {line}")
        return 1
    print("manifest matches the protocol documents")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
