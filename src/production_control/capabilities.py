CAPABILITIES={
 "runninghub":{"provider":"runninghub","submission":"api","supports_prompt":True,"supports_keyframe":True,"supports_storyboard_composite":True,"max_resolution":"720p-test","status_polling":True},
 "xiaoyunque":{"provider":"xiaoyunque","submission":"api_or_mcp","supports_prompt":True,"supports_keyframe":True,"supports_storyboard_composite":True,"max_resolution":"provider-dependent","status_polling":True},
 "libtv":{"provider":"libtv","submission":"api_or_mcp","supports_prompt":True,"supports_keyframe":True,"supports_storyboard_composite":True,"max_resolution":"provider-dependent","status_polling":True}
}

def get_capability(provider: str) -> dict:
    if provider not in CAPABILITIES: raise ValueError(f"unsupported provider: {provider}")
    return CAPABILITIES[provider].copy()

