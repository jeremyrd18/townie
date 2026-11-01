"""Language model calls. Every provider here speaks the OpenAI chat format, so switching is just env vars.

Townie tries each provider that has a key, in LLM_ORDER (default: gemini, groq, featherless),
and each provider's main model before its backup model. Add a key and it joins the list."""
import json
import re

import httpx

from . import config

PROVIDERS = {
    "groq": {
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "key": config.GROQ_API_KEY,
        "models": [config.GROQ_MODEL, config.GROQ_FALLBACK_MODEL],
    },
    "featherless": {
        "url": "https://api.featherless.ai/v1/chat/completions",
        "key": config.FEATHERLESS_API_KEY,
        "models": [config.FEATHERLESS_MODEL, config.FEATHERLESS_FALLBACK_MODEL],
    },
    "gemini": {
        "url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "key": config.GEMINI_API_KEY,
        "models": [config.GEMINI_MODEL],
    },
}


def active() -> list[tuple[str, str, str, str]]:
    """(provider, url, key, model) for every usable provider/model, in order."""
    out = []
    for name in [n.strip() for n in config.LLM_ORDER.split(",")]:
        p = PROVIDERS.get(name)
        if not p or not p["key"]:
            continue
        for model in dict.fromkeys(m for m in p["models"] if m):
            out.append((name, p["url"], p["key"], model))
    return out


def enabled() -> bool:
    return bool(active())


last_used: str | None = None


def describe() -> str:
    """The model that answered the most recent call (or the first in line)."""
    chain = active()
    return last_used or (f"{chain[0][0]}:{chain[0][3]}" if chain else "none (template lines)")


def _model_options(model: str, max_tokens: int) -> dict:
    """Reasoning models think before answering: keep that short and hidden, and leave room for it."""
    m = model.lower()
    if "gpt-oss" in m:
        return {"reasoning_effort": "low", "max_tokens": max_tokens + 400}
    if m.startswith("gemini-2.5"):
        return {"reasoning_effort": "none" if "flash" in m else "low", "max_tokens": max_tokens + 300}
    if m.startswith("gemini"):
        return {"reasoning_effort": "low", "max_tokens": max_tokens + 600}
    if m.startswith("qwen/qwen3"):
        return {"reasoning_format": "hidden", "max_tokens": max_tokens + 600}
    return {"max_tokens": max_tokens}


async def chat(messages: list, max_tokens: int = 120, temperature: float = 0.5, timeout: float = 6.0) -> str | None:
    global last_used
    for i, (name, url, key, model) in enumerate(active()):
        try:
            async with httpx.AsyncClient(timeout=timeout if i == 0 else max(3.0, timeout * 0.7)) as client:
                r = await client.post(url, headers={"Authorization": f"Bearer {key}"}, json={
                    "model": model,
                    "messages": messages,
                    "temperature": temperature,
                    **_model_options(model, max_tokens),
                })
                r.raise_for_status()
                text = r.json()["choices"][0]["message"]["content"].strip()
                last_used = f"{name}:{model}"
                return text
        except Exception as e:
            print(f"[llm] {name}/{model} failed: {e!r}")
    return None


def parse_json(text: str | None):
    """Pull the first JSON object out of a model reply."""
    if not text:
        return None
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
