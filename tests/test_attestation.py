import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from production_control.protocol_attestation import (_required_challenge_ids, build_attestation_plan,
                                                    scoped_protocols, verdict)
from production_control.protocol_fingerprint import build_manifest, check_links, find_references
from production_control import protocol_fingerprint

GATE_FILES = ["09_脚本优化与分镜拆解规范_v3.0.md", "10_镜头设计规范_v3.0.md"]
CORE = [*protocol_fingerprint.REQUIRED_CORE_FILES, *GATE_FILES]
BANK = [
    {"id": "protocol-version", "prompt": "协议版本？", "expected": "3.0",
     "protocol_refs": ["15_协议读取与合规证明_v3.0.md"]},
    {"id": "script-visible-change", "prompt": "节奏变化？", "expected": "可见变化",
     "protocol_refs": [GATE_FILES[0]]},
    {"id": "shot-language", "prompt": "镜头原则？", "expected": "服务画面",
     "protocol_refs": [GATE_FILES[1]]},
]


def _make_root(tmp_path):
    for name in CORE:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"# {name}\n规则正文", encoding="utf-8")
    return build_manifest(tmp_path, seed=7, files=CORE, bank=BANK)


def _contract(manifest):
    hashes = {item["path"]: item["sha256"] for item in manifest["files"]}
    return {
        "run_id": "RUN-1", "task_id": "TASK-1", "contract_id": "CONTRACT-1",
        "current_step_id": "S02", "target_mode": False,
        "steps": [
            {"id": "S02", "applicable": True, "gate": ["G1"],
             "protocol_refs": [{"path": GATE_FILES[0], "sha256": hashes[GATE_FILES[0]]}]},
            {"id": "S03", "applicable": True, "gate": ["G1"],
             "protocol_refs": [{"path": GATE_FILES[0], "sha256": hashes[GATE_FILES[0]]}]},
            {"id": "S04", "applicable": True, "gate": ["G2"],
             "protocol_refs": [{"path": GATE_FILES[1], "sha256": hashes[GATE_FILES[1]]}]},
        ],
    }


def _attestation(tmp_path, manifest, contract, *, answers=None, hash_override=None, fingerprint=None, drop=None):
    required, gate_refs, covered = scoped_protocols(contract, "G1")
    reads = []
    for rel in sorted(required):
        if rel == drop:
            continue
        expected = next(item["sha256"] for item in manifest["files"] if item["path"] == rel)
        sha = hash_override if hash_override else expected
        reads.append({"path": rel, "sha256": sha})
    challenge_ids = _required_challenge_ids(contract["task_id"], "G1", gate_refs, manifest)
    expected_answers = {item["id"]: item["expected"] for item in BANK}
    return {
        "attestation_id": "ATT-1",
        "task_id": contract["task_id"], "run_id": contract["run_id"],
        "contract_id": contract["contract_id"], "scope_gate": "G1",
        "covered_step_ids": covered,
        "agent": "codex",
        "manifest_fingerprint": fingerprint or manifest["fingerprint"],
        "read_files": reads,
        "answers": answers if answers is not None else [
            {"id": challenge_id, "answer": expected_answers[challenge_id]}
            for challenge_id in sorted(challenge_ids)
        ],
        "declared_at": "2026-09-20T17:00:00+08:00",
    }


def test_honest_attestation_passes(tmp_path):
    manifest = _make_root(tmp_path)
    contract = _contract(manifest)
    attestation = _attestation(tmp_path, manifest, contract)
    schema = json.loads((Path(__file__).resolve().parents[1]
                         / "schemas" / "protocol_attestation.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(attestation)
    result = verdict(attestation, manifest, tmp_path, contract)
    assert result == {"status": "PASS", "errors": []}


def test_forged_hash_is_rejected(tmp_path):
    manifest = _make_root(tmp_path)
    contract = _contract(manifest)
    fake = "0" * 64
    result = verdict(_attestation(tmp_path, manifest, contract, hash_override=fake), manifest, tmp_path, contract)
    assert result["status"] == "REJECTED"
    assert any("declared sha256" in e for e in result["errors"])


def test_unread_file_is_rejected(tmp_path):
    manifest = _make_root(tmp_path)
    contract = _contract(manifest)
    result = verdict(_attestation(tmp_path, manifest, contract, drop=GATE_FILES[0]), manifest, tmp_path, contract)
    assert any("not declared as read" in e for e in result["errors"])


def test_wrong_answer_is_rejected_even_with_correct_hashes(tmp_path):
    manifest = _make_root(tmp_path)
    contract = _contract(manifest)
    wrong = _attestation(tmp_path, manifest, contract)["answers"]
    wrong[0]["answer"] = "wrong"
    result = verdict(_attestation(tmp_path, manifest, contract, answers=wrong), manifest, tmp_path, contract)
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
    contract = _contract(manifest)
    result = verdict(_attestation(tmp_path, manifest, contract, fingerprint="a" * 64), manifest, tmp_path, contract)
    assert any("manifest_fingerprint" in e for e in result["errors"])


def test_file_drift_after_manifest_generation_is_rejected(tmp_path):
    manifest = _make_root(tmp_path)
    contract = _contract(manifest)
    (tmp_path / GATE_FILES[0]).write_text("# 规则被修改了", encoding="utf-8")
    result = verdict(_attestation(tmp_path, manifest, contract), manifest, tmp_path, contract)
    assert any("changed since the manifest" in e for e in result["errors"])


def test_references_are_discovered_including_nested_paths():
    text = "见 `16_生图渠道规则_v3.0.md` 与 `核心自动化生产包/02_任务路由与Gate_v3.0.md`。"
    found = find_references(text)
    assert "16_生图渠道规则_v3.0.md" in found
    assert any(item.endswith("02_任务路由与Gate_v3.0.md") for item in found)


def test_broken_reference_is_reported_after_a_rename(tmp_path):
    (tmp_path / "16_生图渠道规则_v3.0.md").write_text("# 新名字的文档", encoding="utf-8")
    (tmp_path / "00_入口.md").write_text("# 入口\n见 `16_生图渠道规则.md`。", encoding="utf-8")
    errors = check_links(tmp_path)
    assert len(errors) == 1
    assert "16_生图渠道规则.md" in errors[0]


def test_intact_references_pass(tmp_path):
    (tmp_path / "16_生图渠道规则_v3.0.md").write_text("# 文档", encoding="utf-8")
    (tmp_path / "00_入口.md").write_text("# 入口\n见 `16_生图渠道规则_v3.0.md`。", encoding="utf-8")
    assert check_links(tmp_path) == []


def test_version_history_is_exempt_because_it_names_retired_files(tmp_path):
    (tmp_path / "00_入口_v3.0.md").write_text("# 入口", encoding="utf-8")
    (tmp_path / "VERSION.md").write_text("# 版本\n原 13_故事本图片与视频生成参考资产选择准则.md 已重编号。", encoding="utf-8")
    assert check_links(tmp_path) == []
    assert check_links(tmp_path, skip=set()) != []


def test_challenge_bank_covers_the_current_rulings():
    from production_control.protocol_fingerprint import CHALLENGE_BANK

    ids = {item["id"] for item in CHALLENGE_BANK}
    assert {"image-model", "image-unauthorized", "tail-frame-blocking", "protocol-version"} <= ids
    assert {"script-visible-change", "script-revision-limit"} <= ids
    answers = {item["id"]: item["expected"] for item in CHALLENGE_BANK}
    assert answers["image-model"] == "gpt-image-2"
    assert answers["image-unauthorized"] == "否"
    assert answers["protocol-version"] == "3.0"
    assert answers["script-visible-change"] == "可见变化"
    assert answers["script-revision-limit"] == "1"


def test_script_quality_protocol_is_scoped_to_its_registered_gate():
    assert "09_脚本优化与分镜拆解规范_v3.0.md" not in protocol_fingerprint.REQUIRED_CORE_FILES
    assert "09_脚本优化与分镜拆解规范_v3.0.md" in protocol_fingerprint.registered_protocol_files()


def test_unrelated_gate_documents_are_not_required_for_current_scope(tmp_path):
    manifest = _make_root(tmp_path)
    contract = _contract(manifest)
    required, _, _ = scoped_protocols(contract, "G1")
    assert GATE_FILES[0] in required
    assert GATE_FILES[1] not in required
    assert "16_生图渠道规则_v3.0.md" not in required


def test_plan_is_explicitly_not_a_read_proof_and_excludes_unrelated_gate_files(tmp_path):
    manifest = _make_root(tmp_path)
    plan = build_attestation_plan(_contract(manifest), manifest)
    paths = {item["path"] for item in plan["protocols_to_read"]}
    assert plan["status"] == "PLAN_NOT_PROOF"
    assert GATE_FILES[0] in paths
    assert GATE_FILES[1] not in paths
    assert "16_生图渠道规则_v3.0.md" not in paths
    assert plan["challenge_questions"]


def test_next_gate_reuses_proven_common_rules_but_requires_its_own_protocol(tmp_path):
    manifest = _make_root(tmp_path)
    contract = _contract(manifest)
    g1_refs = {GATE_FILES[0]}
    g1_challenges = _required_challenge_ids("TASK-1", "G1", g1_refs, manifest)
    prior = [{
        "status": "PASS", "run_id": "RUN-1", "task_id": "TASK-1",
        "contract_id": "CONTRACT-1", "manifest_fingerprint": manifest["fingerprint"],
        "protocol_paths": sorted(set(protocol_fingerprint.REQUIRED_CORE_FILES) | g1_refs),
        "challenge_ids": sorted(g1_challenges),
    }]
    contract["current_step_id"] = "S04"
    plan = build_attestation_plan(contract, manifest, prior)
    paths = {item["path"] for item in plan["protocols_to_read"]}
    assert paths == {GATE_FILES[1]}
    assert set(plan["already_verified_protocols"]) == set(protocol_fingerprint.REQUIRED_CORE_FILES)
    assert all(item["id"] != "protocol-version" for item in plan["challenge_questions"])
    assert [item["id"] for item in plan["challenge_questions"]] == ["shot-language"]


def test_attestation_cannot_claim_a_different_gate_or_contract(tmp_path):
    manifest = _make_root(tmp_path)
    contract = _contract(manifest)
    proof = _attestation(tmp_path, manifest, contract)
    proof["scope_gate"] = "G6"
    result = verdict(proof, manifest, tmp_path, contract)
    assert result["status"] == "REJECTED"
