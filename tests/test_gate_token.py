"""The gate has to be decidable, not advisory.

EP03/A1 bound one asset out of nine. "Do not substitute one image for the rest"
does not stop that - two images pass it, four images pass it. What stops it is
set equality against the declared list in production_contract.json.
"""
import json
from pathlib import Path

from production_control import gate_token

CONTRACT = {
    "contract_id": "C1", "project": "龙骨列车", "segment": "A1", "current_gate": "G5",
    "provider": "libtv",
    "assets": [
        {"role": "scene_master", "path": "assets/取心室.png", "purpose": "lock space",
         "sha256": "s1"},
        {"role": "character_master", "path": "assets/小烬.png", "purpose": "lock identity",
         "sha256": "c1"},
        {"role": "prop_master", "path": "assets/押运箱.png", "purpose": "lock prop",
         "sha256": "p1"},
    ],
}


def _project(tmp_path: Path, contract: dict, bound: list[dict]) -> Path:
    root = tmp_path / "proj"
    (root / "workflow").mkdir(parents=True)
    (root / "workflow" / "production_contract.json").write_text(
        json.dumps(contract, ensure_ascii=False), encoding="utf-8")
    (root / "workflow" / "bound_assets.json").write_text(
        json.dumps({"unit_id": "A1", "assets": bound}, ensure_ascii=False), encoding="utf-8")
    return root


def _bound(role: str, sha: str, *, verified: bool = True) -> dict:
    return {"role": role, "sha256": sha, "node_id": f"n-{role}", "verified": verified}


def test_full_set_bound_passes_and_issues_a_token(tmp_path):
    root = _project(tmp_path, CONTRACT, [_bound("scene_master", "s1"),
                                         _bound("character_master", "c1"),
                                         _bound("prop_master", "p1")])
    verdict = gate_token.evaluate(root, "A1")
    assert verdict["ok"]
    assert verdict["declared_count"] == 3 and verdict["bound_count"] == 3

    ok, path, _ = gate_token.issue(root, "A1")
    assert ok and path.is_file()


def test_one_asset_out_of_three_is_refused(tmp_path):
    """The actual EP03/A1 shape: only the scene image was bound."""
    root = _project(tmp_path, CONTRACT, [_bound("scene_master", "s1")])
    verdict = gate_token.evaluate(root, "A1")
    assert not verdict["ok"]
    assert {d["role"] for d in verdict["diffs"]["missing"]} == {"character_master", "prop_master"}

    ok, path, _ = gate_token.issue(root, "A1")
    assert not ok and path is None


def test_more_assets_do_not_help_if_the_declared_ones_are_absent(tmp_path):
    """Two or four images must not satisfy a three-item declared set."""
    root = _project(tmp_path, CONTRACT, [_bound("scene_master", "s1"),
                                         _bound("scene_master", "s2"),
                                         _bound("scene_master", "s3")])
    verdict = gate_token.evaluate(root, "A1")
    assert not verdict["ok"]
    assert verdict["bound_count"] == 3 and verdict["declared_count"] == 3
    assert verdict["diffs"]["missing"]


def test_right_role_wrong_file_is_caught(tmp_path):
    root = _project(tmp_path, CONTRACT, [_bound("scene_master", "s1"),
                                         _bound("character_master", "WRONG"),
                                         _bound("prop_master", "p1")])
    verdict = gate_token.evaluate(root, "A1")
    assert not verdict["ok"]
    assert any(d["role"] == "character_master" for d in verdict["diffs"]["missing"])


def test_unverified_upload_does_not_count_as_bound(tmp_path):
    root = _project(tmp_path, CONTRACT, [_bound("scene_master", "s1"),
                                         _bound("character_master", "c1", verified=False),
                                         _bound("prop_master", "p1")])
    verdict = gate_token.evaluate(root, "A1")
    assert not verdict["ok"]
    assert [d["role"] for d in verdict["diffs"]["unverified"]] == ["character_master"]


def test_undeclared_binding_is_reported(tmp_path):
    root = _project(tmp_path, CONTRACT, [_bound("scene_master", "s1"),
                                         _bound("character_master", "c1"),
                                         _bound("prop_master", "p1"),
                                         _bound("keyframe", "k1")])
    verdict = gate_token.evaluate(root, "A1")
    assert not verdict["ok"]
    assert [d["role"] for d in verdict["diffs"]["undeclared"]] == ["keyframe"]


def test_a_token_stops_holding_when_the_contract_changes(tmp_path):
    root = _project(tmp_path, CONTRACT, [_bound("scene_master", "s1"),
                                         _bound("character_master", "c1"),
                                         _bound("prop_master", "p1")])
    ok, _, _ = gate_token.issue(root, "A1")
    assert ok
    assert gate_token.token_for(root, "A1")["still_valid"]

    changed = dict(CONTRACT)
    changed["assets"] = CONTRACT["assets"] + [
        {"role": "prop_master", "path": "assets/针筒.png", "purpose": "lock prop", "sha256": "p2"}]
    (root / "workflow" / "production_contract.json").write_text(
        json.dumps(changed, ensure_ascii=False), encoding="utf-8")

    token = gate_token.token_for(root, "A1")
    assert not token["still_valid"]
    assert "合同已变更" in token["stale_reason"]


def test_no_contract_means_no_gate(tmp_path):
    root = tmp_path / "empty"
    (root / "workflow").mkdir(parents=True)
    verdict = gate_token.evaluate(root, "A1")
    assert not verdict["ok"]
    assert verdict["declared_count"] == 0
