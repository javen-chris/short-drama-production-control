"""Cost ledger with submission idempotency.

An unidentified cloud task must be reconciled against the ledger before it is
submitted again: paying twice for the same unit is never allowed, even when the
previous status is UNKNOWN.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

DUPLICATE_STATUSES = {"PENDING", "SUCCEEDED", "UNKNOWN"}


def idempotency_key(unit_id: str, contract_id: str, provider: str, payload: dict) -> str:
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    return f"{unit_id}:{contract_id}:{provider}:{digest[:16]}"


def find_duplicate(ledger: dict, key: str) -> dict | None:
    for entry in ledger.get("entries", []):
        if entry.get("idempotency_key") == key and entry.get("status") in DUPLICATE_STATUSES:
            return entry
    return None


def register_submission(ledger: dict, unit_id: str, contract_id: str, provider: str, payload: dict, cost_cny: float = 0.0) -> dict:
    """Record a paid submission once. Re-submitting the same inputs is refused."""
    key = idempotency_key(unit_id, contract_id, provider, payload)
    duplicate = find_duplicate(ledger, key)
    if duplicate is not None:
        raise ValueError(
            f"duplicate submission refused for {unit_id}: existing task {duplicate.get('task_id')} has status {duplicate.get('status')}"
        )
    entry = {
        "idempotency_key": key,
        "unit_id": unit_id,
        "contract_id": contract_id,
        "provider": provider,
        "status": "PENDING",
        "cost_cny": cost_cny,
        "input_hash": key.rsplit(":", 1)[-1],
        "submitted_at": datetime.now(timezone.utc).isoformat(),
    }
    ledger.setdefault("entries", []).append(entry)
    return entry


def total_spend(ledger: dict) -> float:
    return round(sum(float(entry.get("cost_cny", 0) or 0) for entry in ledger.get("entries", [])), 4)


def budget_status(ledger: dict) -> dict:
    budget = ledger.get("budget_cny")
    spent = total_spend(ledger)
    return {
        "budget_cny": budget,
        "spent_cny": spent,
        "remaining_cny": None if budget is None else round(budget - spent, 4),
        "over_budget": budget is not None and spent > budget,
    }
