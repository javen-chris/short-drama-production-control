IMAGE_MODEL = "gpt-image-2"

IMAGE_CAPABILITIES = {
 "gpt_image2_local_subscription": {"channel": "gpt_image2_local_subscription", "model": IMAGE_MODEL, "backends": ["web", "codex"], "quota": "chatgpt_subscription", "cash_cost": 0, "max_references": 4, "parallel": False, "fallback": "gpt_image2_runninghub_workflow", "note": "本机 Hermes/Codex Agent 调用 GPT 前台；--project= 与 --keep-conversation 必带，参考图需轻量化"},
 "gpt_image2_runninghub_workflow": {"channel": "gpt_image2_runninghub_workflow", "model": IMAGE_MODEL, "backends": ["runninghub"], "quota": "paid", "cash_cost_cny": 0.1, "max_references": 3, "parallel": True, "fallback": None, "workflow_id": "2100124476636753922", "note": "付费兜底；必须走 runninghub_app.py 封装，务必先取得明确授权并记录单张成本"}
}

CAPABILITIES={
 "runninghub":{"provider":"runninghub","submission":"api","supports_prompt":True,"supports_keyframe":True,"supports_storyboard_composite":True,"max_resolution":"720p-test","status_polling":True},
 "xiaoyunque":{"provider":"xiaoyunque","submission":"api_or_mcp","supports_prompt":True,"supports_keyframe":True,"supports_storyboard_composite":True,"max_resolution":"provider-dependent","status_polling":True},
 "libtv":{"provider":"libtv","submission":"api_or_mcp","supports_prompt":True,"supports_keyframe":True,"supports_storyboard_composite":True,"max_resolution":"provider-dependent","status_polling":True}
}

def get_capability(provider: str) -> dict:
    if provider not in CAPABILITIES: raise ValueError(f"unsupported provider: {provider}")
    return CAPABILITIES[provider].copy()

def get_image_capability(channel: str) -> dict:
    if channel not in IMAGE_CAPABILITIES: raise ValueError(f"unsupported image channel: {channel}")
    return IMAGE_CAPABILITIES[channel].copy()

