"""Language model calls. Every provider here speaks the OpenAI chat format, so switching is just env vars.

Townie tries each provider that has a key, in LLM_ORDER (default: featherless, gemini, groq),
and each provider's main model before its backup model. Add a key and it joins the list."""
import asyncio
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
    per_provider = []
    for name in [n.strip() for n in config.LLM_ORDER.split(",")]:
        p = PROVIDERS.get(name)
        if not p or not p["key"]:
            continue
        per_provider.append([(name, p["url"], p["key"], m) for m in dict.fromkeys(m for m in p["models"] if m)])
    # Main model of each provider first, then their backups, so a backup request goes to a
    # different provider (Featherless allows only a few requests at once on small plans).
    out = []
    for tier in range(max((len(x) for x in per_provider), default=0)):
        out += [models[tier] for models in per_provider if tier < len(models)]
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


GARBAGE = re.compile(r"(.)\1{5,}")  # e.g. "!!!!!!" from a glitching model


async def _call(name, url, key, model, messages, max_tokens, temperature, timeout):
    """One request. Returns (text, label) or None on any failure or garbage output."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(url, headers={"Authorization": f"Bearer {key}"}, json={
                "model": model,
                "messages": messages,
                "temperature": temperature,
                **_model_options(model, max_tokens),
            })
            r.raise_for_status()
            text = (r.json()["choices"][0]["message"]["content"] or "").strip()
    except Exception as e:
        print(f"[llm] {name}/{model} failed: {e!r}")
        return None
    if not text or GARBAGE.search(text):
        print(f"[llm] {name}/{model} gave unusable output: {text[:60]!r}")
        return None
    return text, f"{name}:{model}"


async def chat(messages: list, max_tokens: int = 120, temperature: float = 0.5,
               timeout: float = 6.0, hedge: float = 2.5) -> str | None:
    """Ask the first model. If it hasn't answered after `hedge` seconds (or it fails),
    also ask the next one, and use whichever good answer arrives first."""
    global last_used
    chain = active()
    if not chain:
        return None
    pending: set = set()
    next_i = 0

    def start_next():
        nonlocal next_i
        name, url, key, model = chain[next_i]
        next_i += 1
        pending.add(asyncio.create_task(_call(name, url, key, model, messages, max_tokens, temperature, timeout)))

    start_next()
    try:
        while pending:
            wait_for = hedge if next_i < len(chain) else None
            done, _ = await asyncio.wait(pending, timeout=wait_for, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                pending.discard(task)
                result = task.result()
                if result:
                    last_used = result[1]
                    return result[0]
            # Nothing usable yet: bring in the next model (on a timeout, or when one failed).
            if next_i < len(chain) and (not done or not pending):
                start_next()
        return None
    finally:
        for task in pending:
            task.cancel()


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
