import json
from pathlib import Path

from production_control.contract_validator import validate_contract
from production_control.prompt_linter import lint


ROOT = Path(__file__).resolve().parents[1]


def load(name: str) -> dict:
    return json.loads((ROOT / "examples" / name).read_text(encoding="utf-8"))


def test_direct_prompt_contract_is_ready_for_adapter():
    assert validate_contract(load("production_contract.valid.json")) == []


def test_complex_action_requires_storyboard_composite():
    contract = load("production_contract.valid.json")
    contract["prompt_unit"]["risk_flags"] = ["physical_contact"]
    assert "complex risk flags require storyboard_required mode" in validate_contract(contract)


def test_submission_cannot_enable_retry():
    contract = load("production_contract.valid.json")
    contract["authorization"]["allow_retry"] = True
    assert validate_contract(contract)


def test_prompt_requires_prohibitions():
    unit = load("prompt_unit.direct.json")
    unit["prohibitions"] = []
    assert lint(unit)

