import json
from pathlib import Path

from production_control.contract_validator import validate_contract
from production_control.prompt_linter import lint
from production_control.shot_language_linter import lint_sequence
from production_control.pipeline_validator import validate_chain


ROOT = Path(__file__).resolve().parents[1]


def load(name: str) -> dict:
    return json.loads((ROOT / "examples" / name).read_text(encoding="utf-8"))


def test_direct_prompt_contract_is_ready_for_adapter():
    assert validate_contract(load("production_contract.valid.json")) == []


def test_complex_action_requires_storyboard_or_degraded_mode():

    contract = load("production_contract.valid.json")
    contract["prompt_unit"]["risk_flags"] = ["physical_contact"]
    assert "complex risk flags require storyboard_required mode or degraded_direct fallback" in validate_contract(contract)


def test_degraded_direct_allowed_without_storyboard_authorization():
    contract = load("production_contract.valid.json")
    contract["storyboard_mode"] = "degraded_direct"
    contract["prompt_unit"]["risk_flags"] = ["physical_contact"]
    assert validate_contract(contract) == []


def test_degraded_direct_rejected_when_storyboard_authorized():
    contract = load("production_contract.valid.json")
    contract["storyboard_mode"] = "degraded_direct"
    contract["prompt_unit"]["risk_flags"] = ["physical_contact"]
    contract["authorization"]["allow_storyboard_generation"] = True
    assert "degraded_direct must not be used when storyboard generation is authorized" in validate_contract(contract)


def test_tail_frame_missing_without_authorization_is_not_blocking():
    contract = load("production_contract.valid.json")
    contract["prompt_unit"]["risk_flags"] = ["real_tail_frame_required"]
    assert validate_contract(contract) == []


def test_tail_frame_missing_with_authorization_blocks():
    contract = load("production_contract.valid.json")
    contract["prompt_unit"]["risk_flags"] = ["real_tail_frame_required"]
    contract["authorization"]["allow_tail_frame_generation"] = True
    assert "real_tail_frame_required with tail-frame generation authorized needs a real_tail_frame asset" in validate_contract(contract)


def test_submission_cannot_enable_retry():
    contract = load("production_contract.valid.json")
    contract["authorization"]["allow_retry"] = True
    assert validate_contract(contract)


def test_prompt_requires_prohibitions():
    unit = load("prompt_unit.direct.json")
    unit["prohibitions"] = []
    assert lint(unit)


def test_repeated_shot_language_requires_reason():
    first = load("prompt_unit.direct.json")
    second = json.loads(json.dumps(first))
    second["unit_id"] = "EP01-U02"
    assert lint_sequence([first, second])
    second["repeat_reason"] = "保持观众视线锁定手机信息"
    assert lint_sequence([first, second]) == []


def test_pipeline_object_chain_is_valid():
    assert validate_chain(load("pipeline_bundle.valid.json")) == []


def test_pipeline_blocks_unconfirmed_script():
    bundle = load("pipeline_bundle.valid.json")
    bundle["script"]["status"] = "FAIL"
    assert "script must be PASS before downstream objects" in validate_chain(bundle)
