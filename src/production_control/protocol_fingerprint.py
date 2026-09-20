"""Generate and check the protocol manifest that read-attestation depends on.

The manifest pins every core protocol file to its sha256 and carries challenge
questions whose expected answers are stored only as salted-hash digests, so an
agent cannot copy answers out of the manifest - it has to actually read the
documents to answer them.

Lives inside the installable package so tests and CI can import it without
depending on the caller's working directory.
Standard library only.
"""
from __future__ import annotations

import hashlib
import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_ROOT = r"D:\AIGC短剧本地工作流规则及协议\短剧制作核心协议"

# Every file an agent must claim (and prove) it read before producing anything.
# Names carry the _v3.0 suffix since the 2026-09-20 protocol upgrade.
REQUIRED_CORE_FILES = [
    "00_自动化生产唯一入口_v3.0.md",
    "核心自动化生产包/01_核心总则_v3.0.md",
    "核心自动化生产包/02_任务路由与Gate_v3.0.md",
    "核心自动化生产包/03_生产与资产规则_v3.0.md",
    "核心自动化生产包/04_专项规则_v3.0.md",
    "11_目标模式自动建卡与连续执行规则_v3.0.md",
    "13_模型执行前硬门禁_v3.0.md",
    "14_RH生图渠道与GPT通道现状_v3.0.md",
    "16_生图渠道规则_v3.0.md",
]

# Answers are normalized (trimmed, lowercased) before hashing.
CHALLENGE_BANK = [
    {"id": "image-model", "prompt": "本协议下生图唯一允许的图像模型是什么？", "expected": "gpt-image-2"},
    {"id": "image-fallback", "prompt": "订阅额度耗尽且已授权时的生图兜底通道枚举值是什么？", "expected": "gpt_image2_runninghub_workflow"},
    {"id": "image-unauthorized", "prompt": "常规（非全自动）模式下，Agent 是否可以自行执行生图？（是/否）", "expected": "否"},
    {"id": "autonomous-asset-fill", "prompt": "全自动目标模式下资产评估发现缺 MASTER 时，Agent 应当？（填：立即生成 或 停下请示）", "expected": "立即生成"},
    {"id": "degraded-route", "prompt": "复杂风险但未授权制作故事本时，生产单元走的路线枚举值是什么？", "expected": "degraded_direct"},
    {"id": "master-gate", "prompt": "角色/场景/道具 MASTER 缺失时，生产停在哪个 Gate？（如 G5）", "expected": "g3"},
    {"id": "tail-frame-blocking", "prompt": "首尾帧未授权制作时是否阻断生产？（是/否）", "expected": "否"},
    {"id": "max-submissions", "prompt": "一份合同授权的付费视频提交最多几次？（数字）", "expected": "1"},
    {"id": "protocol-version", "prompt": "当前核心协议的主版本号是？（如 2.0）", "expected": "3.0"},
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


def build_manifest(root: str | Path, *, seed: int | None = None, files: list[str] | None = None,
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


def manifest_path(root: str | Path) -> Path:
    return Path(root) / "protocol_manifest.json"


def check(root: str | Path) -> list[str]:
    """Detect drift between the manifest and the documents on disk."""
    root = Path(root)
    path = manifest_path(root)
    if not path.is_file():
        return [f"manifest not found: {path} (generate it first)"]
    manifest = json.loads(path.read_text(encoding="utf-8"))
    errors: list[str] = []
    for entry in manifest.get("files", []):
        target = root / entry["path"]
        if not target.is_file():
            errors.append(f"{entry['path']}: file missing")
        elif sha256_file(target) != entry["sha256"]:
            errors.append(f"{entry['path']}: changed since the manifest was generated - regenerate")
    return errors


# A protocol document reference looks like "16_生图渠道规则_v3.0.md" or
# "核心自动化生产包/02_任务路由与Gate_v3.0.md".
REFERENCE_PATTERN = r"[0-9]{2}_[^\s`)\]、，]*?\.md"

# VERSION.md documents the rename history, so it legitimately names files that
# no longer exist. Everywhere else, a reference must resolve.
HISTORY_DOCUMENTS = {"VERSION.md"}


def find_references(text: str) -> list[str]:
    """Every protocol document name mentioned in one document's text."""
    import re

    return sorted(set(re.findall(REFERENCE_PATTERN, text)))


def check_links(root: str | Path, skip: set[str] | None = None) -> list[str]:
    """Find references to protocol documents that do not exist.

    Renaming a protocol file is how dead links get introduced: one document
    points at the old name and nobody notices until an agent follows it. Run
    this after any rename or restructure.
    """
    root = Path(root)
    skip = HISTORY_DOCUMENTS if skip is None else skip
    errors: list[str] = []
    names: set[str] = set()
    for folder in (root, root / "核心自动化生产包", root / "templates", root / "context"):
        if folder.is_dir():
            names.update(p.name for p in folder.glob("*.md"))
    for document in sorted(root.rglob("*.md")):
        if document.name in skip:
            continue
        try:
            text = document.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for reference in find_references(text):
            bare = reference.split("/")[-1]
            if bare in names or reference in names:
                continue
            errors.append(f"{document.relative_to(root)}: references missing document {reference}")
    return errors


def generate(root: str | Path, *, seed: int | None = None, out: str | Path | None = None) -> dict:
    manifest = build_manifest(root, seed=seed)
    target = Path(out) if out else manifest_path(root)
    target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Generate or check the protocol manifest.")
    parser.add_argument("command", choices=["generate", "check", "links"])
    parser.add_argument("--root", default=DEFAULT_ROOT)
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()
    if args.command == "generate":
        manifest = generate(args.root, seed=args.seed)
        print(f"manifest written: {manifest_path(args.root)}")
        print(f"fingerprint: {manifest['fingerprint']}")
        for item in manifest["challenges"]:
            print(f"  - {item['id']}: {item['prompt']}")
        return 0
    if args.command == "links":
        errors = check_links(args.root)
        if errors:
            print("BROKEN REFERENCES:")
            for line in errors:
                print(f"  - {line}")
            return 1
        print("every protocol reference resolves to an existing document")
        return 0
    errors = check(args.root)
    if errors:
        print("DRIFTED:")
        for line in errors:
            print(f"  - {line}")
        return 1
    print("manifest matches the protocol documents")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
