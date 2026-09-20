import hashlib
import json

from production_control.protocol_attestation import verdict
from tools.protocol_fingerprint import build_manifest

CORE = ["00_入口.md", "01_总则.md"]
BANK = [
    {"id": "image-model", "prompt": "唯一生图模型？", "expected": "gpt-image-2"},
    {"id": "master-gate", "prompt": "缺 MASTER 停在哪个 Gate？", "expected": "G3"},
]


def _make_root(tmp_path):
    for name in CORE:
        (tmp_path / name).write_text(f"# {name}\n规则正文", encoding="utf-8")
    return build_manifest(tmp_path, seed=7, files=CORE, bank=BANK)


def _attestation(tmp_path, manifest, *, answers=None, hash_override=None, fingerprint=None, drop=None):
    reads = []
    for entry in manifest["files"]:
        if entry["path"] == drop:
            continue
        sha = hash_override if hash_override else entry["sha256"]
        reads.append({"path": entry["path"], "sha256": sha})
    return {
        "attestation_id": "ATT-1",
        "task_id": "TASK-1",
        "agent": "codex",
        "manifest_fingerprint": fingerprint or manifest["fingerprint"],
        "read_files": reads,
        "answers": answers if answers is not None else [{"id": "image-model", "answer": "GPT-Image-2"}, {"id": "master-gate", "answer": "g3"}],
        "declared_at": "2026-09-20T17:00:00+08:00",
    }


def test_honest_attestation_passes(tmp_path):
    manifest = _make_root(tmp_path)
    result = verdict(_attestation(tmp_path, manifest), manifest, tmp_path)
    assert result == {"status": "PASS", "errors": []}


def test_forged_hash_is_rejected(tmp_path):
    manifest = _make_root(tmp_path)
    fake = "0" * 64
    result = verdict(_attestation(tmp_path, manifest, hash_override=fake), manifest, tmp_path)
    assert result["status"] == "REJECTED"
    assert any("declared sha256" in e for e in result["errors"])


def test_unread_file_is_rejected(tmp_path):
    manifest = _make_root(tmp_path)
    result = verdict(_attestation(tmp_path, manifest, drop="01_总则.md"), manifest, tmp_path)
    assert any("not declared as read" in e for e in result["errors"])


def test_wrong_answer_is_rejected_even_with_correct_hashes(tmp_path):
    manifest = _make_root(tmp_path)
    result = verdict(_attestation(tmp_path, manifest, answers=[{"id": "image-model", "answer": "sd-xl"}, {"id": "master-gate", "answer": "g3"}]), manifest, tmp_path)
    assert any("wrong answer" in e for e in result["errors"])


def test_answers_cannot_be_copied_from_the_manifest(tmp_path):
    manifest = _make_root(tmp_path)
    dumped = json.dumps(manifest)
    for challenge in manifest["challenges"]:
        assert challenge["answer_sha256"] not in dumped or hashlib.sha256(challenge["answer_sha256"].encode()).hexdigest()
    assert all("answer" not in c or "answer_sha256" in c for c in manifest["challenges"])
    assert not any(c.get("expected") for c in manifest["challenges"])


def test_old_manifest_fingerprint_is_rejected(tmp_path):
    manifest = _make_root(tmp_path)
    result = verdict(_attestation(tmp_path, manifest, fingerprint="a" * 64), manifest, tmp_path)
    assert any("manifest_fingerprint" in e for e in result["errors"])


def test_file_drift_after_manifest_generation_is_rejected(tmp_path):
    manifest = _make_root(tmp_path)
    (tmp_path / "01_总则.md").write_text("# 01_总则.md\n规则被修改了", encoding="utf-8")
    result = verdict(_attestation(tmp_path, manifest), manifest, tmp_path)
    assert any("changed since the manifest" in e for e in result["errors"])
