import httpx
from app.config import load_settings

_DEFAULT_ENDPOINT = "https://api.deepseek.com"


def _default_poster(url, headers, payload) -> dict:
    resp = httpx.post(url, headers=headers, json=payload, timeout=120.0)
    resp.raise_for_status()
    return resp.json()


def _provider_for(model, settings) -> tuple:
    """Pick (api_key, endpoint) from the model name.

    kimi-*/moonshot-* go to Moonshot; everything else to DeepSeek.
    """
    name = (model or "").lower()
    if name.startswith("kimi") or name.startswith("moonshot"):
        return settings.kimi_api_key, settings.kimi_endpoint
    return settings.deepseek_api_key, _DEFAULT_ENDPOINT


def chat(messages, model, *, api_key=None, endpoint=None, poster=None) -> str:
    s = load_settings()
    default_key, default_endpoint = _provider_for(model, s)
    api_key = api_key or default_key
    endpoint = (endpoint or default_endpoint).rstrip("/")
    poster = poster or _default_poster
    url = f"{endpoint}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {"model": model, "messages": messages}
    data = poster(url, headers, payload)
    return data["choices"][0]["message"]["content"]


def resolve_model_config(user) -> dict:
    s = load_settings()
    if user and user.get("model_key"):
        return {
            "api_key": user["model_key"],
            "endpoint": user.get("model_endpoint") or _DEFAULT_ENDPOINT,
        }
    return {"api_key": s.deepseek_api_key, "endpoint": _DEFAULT_ENDPOINT}
