"""Who is allowed to write what, and which model may QA which Gate.

The producing model must not be able to declare its own work passed. Enforcing
that by asking it nicely does not work - it is enforced here, at the only door
the trace has: `append_event` refuses a COMPLETED written by a producer, so the
only way a step can be recorded as passed is for a *different* model to say so
through its own entry point.

The rules are data, not code, so the Gate-to-model assignment can be changed
without a release.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

POLICY_RELPATH = "capabilities/qa_policy.json"

PRODUCER = "producer"
QA = "qa"

WRITE_AUTHORITY_VIOLATION = "WRITE_AUTHORITY_VIOLATION"
SELF_QA_VIOLATION = "SELF_QA_VIOLATION"
QA_WITHOUT_SUBMISSION = "QA_WITHOUT_SUBMISSION"
QA_MODEL_NOT_ALLOWED = "QA_MODEL_NOT_ALLOWED"
QA_MODEL_UNKNOWN = "QA_MODEL_UNKNOWN"
PRODUCER_MODEL_NOT_ALLOWED = "PRODUCER_MODEL_NOT_ALLOWED"

DEFAULT_PRODUCER_ALLOWED = frozenset({
    "SUBMITTED_FOR_QA", "BLOCKED", "FAILED", "WAITING_APPROVAL",
    "PAUSED_EXCEPTION", "SUBMITTED_IN_PROGRESS",
})
DEFAULT_QA_ALLOWED = frozenset({
    "COMPLETED", "COMPLETED_WITH_CONTINUITY_CAVEAT", "USABLE_WITH_SCENE_CONTINUITY_FAIL",
    "BLOCKED", "FAILED", "WAITING_APPROVAL", "PAUSED_EXCEPTION",
})


def console_root(path: str | Path | None = None) -> Path:
    if path:
        return Path(path)
    return Path(__file__).resolve().parents[2]


@lru_cache(maxsize=4)
def _load_cached(policy_path: str) -> dict:
    path = Path(policy_path)
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_policy(console: str | Path | None = None) -> dict:
    """The policy document, or an empty dict when there is none.

    A missing policy must not silently grant permission, so callers fall back to
    the built-in defaults below rather than to "anything goes".
    """
    return _load_cached(str(console_root(console) / POLICY_RELPATH))


def _role_set(policy: dict, role: str) -> frozenset[str]:
    roles = (policy or {}).get("roles") or {}
    entry = roles.get(role) or {}
    values = entry.get("may_write")
    if not values:
        return DEFAULT_PRODUCER_ALLOWED if role == PRODUCER else DEFAULT_QA_ALLOWED
    return frozenset(values)


def may_write(role: str, outcome: str, policy: dict | None = None) -> tuple[bool, str]:
    """Is this role allowed to record this outcome?

    The asymmetry is the whole point: a producer may submit, only QA may pass.
    """
    policy = policy if policy is not None else load_policy()
    role = role or PRODUCER
    allowed = _role_set(policy, role)
    if outcome in allowed:
        return True, ""
    if role == PRODUCER:
        return False, (
            f"{WRITE_AUTHORITY_VIOLATION}：生产角色不允许写 {outcome}。"
            "生产者只能写 SUBMITTED_FOR_QA（提交待审），不能自己宣布通过。"
            "通过必须由另一个模型的 QA 入口写入（tools/qa_verdict.py）。"
        )
    return False, f"{WRITE_AUTHORITY_VIOLATION}：QA 角色不允许写 {outcome}。"


def gate_info(gate: str, policy: dict | None = None) -> dict:
    policy = policy if policy is not None else load_policy()
    gates = (policy or {}).get("gates") or {}
    if gate and gate in gates:
        return dict(gates[gate], gate=gate)
    return {"gate": gate, "name": "", "qa_models": []}


def qa_model_allowed(gate: str, model: str, policy: dict | None = None) -> tuple[bool, str]:
    """Is this model permitted to QA this Gate?

    An empty qa_models list means "any model that is not the producer"; a filled
    one means only those models. An unnamed model is never allowed - an
    unattributable QA is not evidence of anything.
    """
    model = (model or "").strip()
    if not model:
        return False, f"{QA_MODEL_UNKNOWN}：QA 未提供执行模型，无法证明独立。"
    allowed = gate_info(gate, policy).get("qa_models") or []
    if allowed and model not in allowed:
        return False, (f"{QA_MODEL_NOT_ALLOWED}：Gate {gate} 的 QA 只允许 "
                       f"{'、'.join(allowed)}，收到的是 {model}。")
    return True, ""


def producer_model_allowed(model: str, policy: dict | None = None) -> tuple[bool, str]:
    """Is this model permitted to produce?

    Empty producer_models means the name is not restricted. Filling it pins the
    producing model too, which only makes sense once the team actually runs one.
    """
    policy = policy if policy is not None else load_policy()
    model = (model or "").strip()
    allowed = (policy or {}).get("producer_models") or []
    if not allowed or not model:
        return True, ""
    if model not in allowed:
        return False, (f"{PRODUCER_MODEL_NOT_ALLOWED}：生产模型只允许 "
                       f"{'、'.join(allowed)}，收到的是 {model}。")
    return True, ""


def available_gates(policy: dict | None = None) -> list[str]:
    policy = policy if policy is not None else load_policy()
    gates = (policy or {}).get("gates") or {}
    return sorted(gates) or [f"G{n}" for n in range(9)]
