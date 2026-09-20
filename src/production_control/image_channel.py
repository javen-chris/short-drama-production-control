"""GPT-Image-2 channel policy: the only image model, with a paid fallback.

Model is pinned to gpt-image-2. The local subscription channel (driven by a
Hermes/Codex agent against the ChatGPT front end) is always tried first; the
RunningHub GPT-Image-2 workflow is a paid fallback that requires explicit
authorization and a recorded reason.
"""
from __future__ import annotations

from .capabilities import IMAGE_MODEL, get_image_capability

LOCAL_CHANNEL = "gpt_image2_local_subscription"
RH_CHANNEL = "gpt_image2_runninghub_workflow"

QUOTA_EXHAUSTED = {"subscription_quota_exhausted", "local_channel_unavailable", "reference_slot_limit"}


def choose_image_channel(quota_available: bool, fallback_reason: str | None = None, runninghub_authorized: bool = False) -> dict:
    """Return the channel decision for one image asset.

    quota_available True  -> local subscription channel, never the paid one.
    quota_available False -> paid RunningHub workflow, only when authorized;
                             otherwise the record is blocked, not silently routed.
    """
    if fallback_reason is not None and fallback_reason not in QUOTA_EXHAUSTED:
        raise ValueError(f"unknown fallback reason: {fallback_reason}")
    if quota_available:
        capability = get_image_capability(LOCAL_CHANNEL)
        return {
            "image_channel": LOCAL_CHANNEL,
            "model": IMAGE_MODEL,
            "fallback_reason": "none",
            "cash_cost_cny": capability["cash_cost"],
            "authorized": True,
            "reason": "订阅额度可用，走本机 GPT 前台通道",
        }
    if not fallback_reason:
        raise ValueError("falling back from the local channel requires a recorded reason")
    capability = get_image_capability(RH_CHANNEL)
    if not runninghub_authorized:
        return {
            "image_channel": RH_CHANNEL,
            "model": IMAGE_MODEL,
            "fallback_reason": fallback_reason,
            "cash_cost_cny": capability["cash_cost_cny"],
            "authorized": False,
            "blocked": True,
            "reason": "订阅额度不可用且 RunningHub 生图未授权，停在 BLOCKED_UNAUTHORIZED",
        }
    return {
        "image_channel": RH_CHANNEL,
        "model": IMAGE_MODEL,
        "fallback_reason": fallback_reason,
        "workflow_id": capability["workflow_id"],
        "cash_cost_cny": capability["cash_cost_cny"],
        "authorized": True,
        "blocked": False,
        "reason": "订阅额度不可用，使用 RunningHub GPT-Image-2 工作流兜底",
    }


def validate_image_record(record: dict) -> list[str]:
    """Reject any image asset that is not GPT-Image-2 or that lacks provenance."""
    errors: list[str] = []
    if record.get("model") != IMAGE_MODEL:
        errors.append(f"image model must be {IMAGE_MODEL}")
    channel = record.get("image_channel")
    if channel not in {LOCAL_CHANNEL, RH_CHANNEL}:
        errors.append(f"image_channel must be {LOCAL_CHANNEL} or {RH_CHANNEL}")
        return errors
    capability = get_image_capability(channel)
    if channel == RH_CHANNEL:
        if record.get("fallback_reason") not in QUOTA_EXHAUSTED:
            errors.append("runninghub fallback requires a recorded fallback_reason")
        if not record.get("authorized"):
            errors.append("runninghub image generation requires explicit authorization")
        if not record.get("task_id"):
            errors.append("runninghub images require a task_id for cost reconciliation")
    else:
        if not record.get("conversation_url") and not record.get("evidence"):
            errors.append("local subscription images require a conversation or evidence record")
        if record.get("fallback_reason") not in {None, "none"}:
            errors.append("local subscription channel must not carry a fallback reason")
    if not record.get("evidence"):
        errors.append("every image asset needs an evidence path or reference")
    references = record.get("reference_count")
    if references is not None and references > capability["max_references"]:
        errors.append(f"{channel} supports at most {capability['max_references']} references, got {references}")
    if record.get("cost_cny") is not None and record["cost_cny"] < 0:
        errors.append("cost_cny must not be negative")
    return errors
