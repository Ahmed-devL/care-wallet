"""
llm_client.py — thin wrapper around NVIDIA's hosted, OpenAI-compatible
chat-completions endpoint (https://integrate.api.nvidia.com/v1).

Why this exists as its own file: every LLM call in this project (message
extraction, image extraction, decision explanations) goes through here, so
usage tracking and caching only need to be correct in ONE place.

SETUP (do this yourself, or hand this exact instruction to a coding agent --
it's pure scaffolding, no decision logic):

    Create a file named `.env` in the repo root (same folder as AGENTS.md)
    containing exactly:

        NVIDIA_API_KEY=nvapi-your-real-key-here

    Make sure `.env` is listed in .gitignore (it already should be, next to
    log.txt) so the key is never committed.

No extra pip packages needed beyond `requests` (already in most Python
installs; if missing: `pip install requests`).
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Optional

import requests

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.join(_HERE, "..")
_ENV_PATH = os.path.join(_REPO_ROOT, ".env")
_CACHE_DIR = os.path.join(_HERE, "cache")
_CACHE_PATH = os.path.join(_CACHE_DIR, "llm_cache.json")

API_BASE = "https://integrate.api.nvidia.com/v1/chat/completions"

# Sensible defaults -- override via .env if you want different models.


def _load_dotenv() -> None:
    """Minimal .env loader -- no extra dependency needed. Only sets a var
    if it isn't already set in the real environment (real env wins)."""
    if not os.path.exists(_ENV_PATH):
        return
    with open(_ENV_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val


_load_dotenv()
API_KEY = os.environ.get("NVIDIA_API_KEY", "")

DEFAULT_TEXT_MODEL = os.environ.get("NVIDIA_TEXT_MODEL", "meta/llama-3.3-70b-instruct")
DEFAULT_VISION_MODEL = os.environ.get("NVIDIA_VISION_MODEL", "minimaxai/minimax-m3")

_replay_mode = False

def set_replay_mode(enabled: bool) -> None:
    global _replay_mode
    _replay_mode = enabled

# ---------------------------------------------------------------------------
# Usage tracking (feeds evaluation/usage_report.md directly -- don't hand-type
# those numbers, read them from here after the full run).
# ---------------------------------------------------------------------------
_usage: dict[str, dict[str, int]] = {}  # model -> {"calls":..,"prompt":..,"completion":..}


def _record_usage(model: str, prompt_tokens: int, completion_tokens: int) -> None:
    row = _usage.setdefault(model, {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0})
    row["calls"] += 1
    row["prompt_tokens"] += prompt_tokens
    row["completion_tokens"] += completion_tokens


def get_usage_summary() -> dict[str, dict[str, int]]:
    """Call this once at the end of the full run and dump it into
    evaluation/usage_report.md. Includes calls served from cache with
    calls_from_cache so you can show the cache is actually working."""
    return json.loads(json.dumps(_usage))  # deep copy


# ---------------------------------------------------------------------------
# Disk cache -- keyed by sha256(model + full request payload). This means:
#   - Re-running the pipeline makes ZERO new API calls for anything already
#     resolved (satisfies the --replay requirement from the phase playbook
#     without needing a separate CLI mode).
#   - If you tweak a prompt, the cache key changes automatically and it
#     re-fetches just that one.
# ---------------------------------------------------------------------------
def _load_cache() -> dict:
    if os.path.exists(_CACHE_PATH):
        with open(_CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_cache(cache: dict) -> None:
    os.makedirs(_CACHE_DIR, exist_ok=True)
    with open(_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2)


_cache = _load_cache()


class LLMError(RuntimeError):
    pass


def chat(
    messages: list[dict],
    model: Optional[str] = None,
    max_tokens: int = 1024,
    temperature: float = 0.0,
    max_retries: int = 3,
) -> str:
    """
    Send a chat-completion request. Returns the assistant's text content.
    Cached: an identical (model, messages, max_tokens, temperature) call
    never hits the network twice.

    Raises LLMError with a clear message if NVIDIA_API_KEY is missing or the
    API returns an error after retries -- callers should catch this and fall
    back to a conservative default rather than crash the whole run.
    """
    if not API_KEY:
        raise LLMError(
            "NVIDIA_API_KEY is not set. Create a `.env` file at the repo root "
            "with a line: NVIDIA_API_KEY=nvapi-... (see llm_client.py docstring)."
        )

    model = model or DEFAULT_TEXT_MODEL
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    cache_key = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    if cache_key in _cache:
        entry = _cache[cache_key]
        _record_usage(model, 0, 0)  # served from cache -- zero new tokens
        _usage[model]["calls_from_cache"] = _usage[model].get("calls_from_cache", 0) + 1
        return entry["content"]

    if _replay_mode:
        raise LLMError("Cache miss in --replay mode. API calls are strictly disabled.")

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    last_err = None
    for attempt in range(max_retries):
        try:
            resp = requests.post(API_BASE, headers=headers, json=payload, timeout=60)
            if resp.status_code == 429 or resp.status_code >= 500:
                last_err = f"HTTP {resp.status_code}: {resp.text[:300]}"
                time.sleep(2 ** attempt)
                continue
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            _record_usage(model, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))
            _cache[cache_key] = {"content": content}
            _save_cache(_cache)
            return content
        except requests.RequestException as e:
            last_err = str(e)
            time.sleep(2 ** attempt)

    raise LLMError(f"NVIDIA API call failed after {max_retries} attempts: {last_err}")


def chat_with_image(
    text_prompt: str,
    image_path: str,
    model: Optional[str] = None,
    max_tokens: int = 512,
) -> str:
    """Single-image vision call. image_path is a local PNG/JPG file path."""
    import base64

    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    ext = "png" if image_path.lower().endswith("png") else "jpeg"

    messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": text_prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/{ext};base64,{b64}"}},
        ],
    }]
    return chat(messages, model=model or DEFAULT_VISION_MODEL, max_tokens=max_tokens, temperature=0.0)


def extract_json(text: str) -> dict | list:
    """
    Strip markdown code fences if present and parse JSON. Raises ValueError
    with the raw text included if parsing fails, so callers can log/skip
    the offending item instead of crashing the whole batch.
    """
    t = text.strip()
    if t.startswith("```"):
        t = t.split("```")[1]
        if t.startswith("json"):
            t = t[4:]
    t = t.strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError as e:
        raise ValueError(f"Could not parse JSON from model output: {e}\nRaw output: {text[:500]}")
