"""Replaceable language-model adapters. Keys are read server-side from the environment only."""
from __future__ import annotations

import json
import time

import httpx

from ..config import env, load_pricing


class LLMError(Exception):
    """possibly_billed=True means the request may have reached the provider and been charged
    (e.g. a read timeout or a server error after sending). Such calls are never retried automatically
    and are counted against the budget at their worst-case cost."""

    def __init__(self, msg: str, possibly_billed: bool = False, config_error: bool = False, attempts: int | None = None,
                 request_id: str | None = None, signature: str | None = None):
        super().__init__(msg)
        self.possibly_billed = possibly_billed
        # config_error: wrong/missing model, key, permission or quota. Never retried; the run stops immediately.
        self.config_error = config_error
        self.attempts = attempts  # requests actually sent (None = unknown; counted as the maximum allowed)
        self.request_id = request_id
        self.signature = signature or msg[:160]  # used to detect "the same rejection twice in a row"


# Failures where the request certainly never reached the provider: safe to retry.
NOT_SENT = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)
# Rejected before any processing (rate limit / overloaded): safe to retry.
RETRY_STATUS_ANTHROPIC = (429, 529)
RETRY_STATUS_OPENAI = (429,)
READ_TIMEOUT = 600.0  # long enough for the largest batch (max_tokens <= 16,000)


def estimate_tokens(text: str) -> int:
    # ~4 characters per token for English prose; deliberately rounded up.
    return int(len(text) / 3.6) + 1


def price_for(model: str) -> dict | None:
    return load_pricing().get("models", {}).get(model)


def cost_usd(model: str, in_tok: int, out_tok: int) -> float | None:
    """Cost at the configured list price. Cached input is deliberately charged at the full input price (overstates).
    Reasoning tokens are part of `out_tok` (OpenAI bills them as output). A long-context surcharge applies when the
    pricing entry defines one (e.g. gpt-6.1-sol: >272K input tokens -> 2x input, 1.5x output for the whole request)."""
    p = price_for(model)
    if not p or p.get("input_per_mtok") is None or p.get("output_per_mtok") is None:
        return None
    i_rate, o_rate = p["input_per_mtok"], p["output_per_mtok"]
    lc = p.get("long_context")
    if lc and in_tok > int(lc.get("threshold_input_tokens", 10 ** 12)):
        i_rate *= float(lc.get("input_multiplier", 1))
        o_rate *= float(lc.get("output_multiplier", 1))
    return round(in_tok / 1e6 * i_rate + out_tok / 1e6 * o_rate, 5)


def price_note(model: str, stale_days: int = 90) -> str | None:
    """Warn when a price is missing or its verification date is old, instead of presenting false precision."""
    import datetime as dt
    import re as _re
    p = price_for(model)
    if not p or p.get("input_per_mtok") is None:
        return f"no price configured for {model}"
    m = _re.search(r"(\d{4}-\d{2}-\d{2})", str(p.get("verified", "")))
    if not m:
        return f"price for {model} has no verification date"
    age = (dt.date.today() - dt.date.fromisoformat(m.group(1))).days
    if age > stale_days:
        return f"price for {model} was last verified {age} days ago ({m.group(1)}); check the provider's pricing page"
    return None


class LLMClient:
    provider = "base"

    def __init__(self, model: str):
        self.model = model

    def complete(self, system: str, user: str, max_tokens: int = 4000) -> dict:
        raise NotImplementedError


class AnthropicClient(LLMClient):
    provider = "anthropic"

    def __init__(self, model: str, key: str):
        super().__init__(model)
        self.key = key

    def generation_settings(self) -> dict:
        return {"api": "messages"}

    def complete(self, system, user, max_tokens=4000, max_attempts=4):
        # No `temperature`: current Claude models reject it ("temperature is deprecated for this model").
        body = {"model": self.model, "max_tokens": max_tokens, "system": system,
                "messages": [{"role": "user", "content": user}]}
        last = None
        n = 0
        for attempt in range(max(1, min(4, int(max_attempts)))):
            n += 1
            try:
                r = httpx.post("https://api.anthropic.com/v1/messages", json=body,
                               timeout=httpx.Timeout(READ_TIMEOUT, connect=15.0),
                               headers={"x-api-key": self.key, "anthropic-version": "2023-06-01",
                                        "content-type": "application/json"})
            except NOT_SENT as e:
                last = f"could not connect: {e}"
                time.sleep(2 ** attempt)
                continue
            except httpx.HTTPError as e:
                raise LLMError(f"network error after the request was sent ({type(e).__name__}); not retried because it "
                               f"may already have been billed", possibly_billed=True, attempts=n) from e
            if r.status_code in RETRY_STATUS_ANTHROPIC:
                last = f"HTTP {r.status_code}: {r.text[:200]}"
                time.sleep(3 * (attempt + 1))
                continue
            if r.status_code >= 500:
                raise LLMError(f"HTTP {r.status_code} from provider; not retried because it may already have been billed: "
                               f"{r.text[:200]}", possibly_billed=True, attempts=n)
            if r.status_code != 200:
                cfg = r.status_code in (401, 403, 404)
                raise LLMError(f"HTTP {r.status_code}: {r.text[:300]}", config_error=cfg, attempts=n)
            j = r.json()
            text = "".join(b.get("text", "") for b in j.get("content", []) if b.get("type") == "text")
            u = j.get("usage", {})
            return {"text": text, "input_tokens": u.get("input_tokens"), "output_tokens": u.get("output_tokens"),
                    "stop_reason": j.get("stop_reason"), "request_id": r.headers.get("request-id") if hasattr(r, "headers") else None,
                    "response_id": j.get("id"), "attempts": n, "status": "completed"}
        raise LLMError(last or "failed after retries", attempts=n)


class OpenAICompatClient(LLMClient):
    """Legacy adapter for an OpenAI-COMPATIBLE server set with OPENAI_BASE_URL (e.g. a local Ollama / LM Studio / vLLM
    model), via Chat Completions. Official OpenAI uses OpenAIResponsesClient (app/llm/openai_responses.py)."""
    provider = "openai_compatible"

    def generation_settings(self) -> dict:
        return {"api": "chat.completions", "temperature": 0, "base_url": self.base}

    def __init__(self, model: str, key: str, base: str):
        super().__init__(model)
        self.key, self.base = key, base.rstrip("/")

    def complete(self, system, user, max_tokens=4000):
        body = {"model": self.model, "max_tokens": max_tokens, "temperature": 0,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        headers = {"Content-Type": "application/json"}
        if self.key:
            headers["Authorization"] = f"Bearer {self.key}"
        last = None
        for attempt in range(3):
            try:
                r = httpx.post(f"{self.base}/chat/completions", json=body, headers=headers,
                               timeout=httpx.Timeout(READ_TIMEOUT, connect=15.0))
            except NOT_SENT as e:
                last = f"could not connect: {e}"
                time.sleep(2 ** attempt)
                continue
            except httpx.HTTPError as e:
                raise LLMError(f"network error after the request was sent ({type(e).__name__}); not retried because it "
                               f"may already have been billed", possibly_billed=True) from e
            if r.status_code in RETRY_STATUS_OPENAI:
                last = f"HTTP {r.status_code}"
                time.sleep(3 * (attempt + 1))
                continue
            if r.status_code >= 500:
                raise LLMError(f"HTTP {r.status_code} from provider; not retried because it may already have been billed",
                               possibly_billed=True)
            if r.status_code != 200:
                raise LLMError(f"HTTP {r.status_code}: {r.text[:300]}")
            j = r.json()
            u = j.get("usage") or {}
            return {"text": j["choices"][0]["message"]["content"], "input_tokens": u.get("prompt_tokens"),
                    "output_tokens": u.get("completion_tokens"), "stop_reason": j["choices"][0].get("finish_reason")}
        raise LLMError(last or "failed after retries")


def openai_model() -> str:
    from .openai_responses import DEFAULT_OPENAI_MODEL
    return env("OPENAI_MODEL") or DEFAULT_OPENAI_MODEL


def provider_status() -> dict:
    """Which providers can be used — booleans and model names only, never key values."""
    from .openai_responses import sdk_available
    return {
        "anthropic": {"configured": bool(env("ANTHROPIC_API_KEY")), "model_setting": "model_name"},
        "openai": {"configured": bool(env("OPENAI_API_KEY")) and not env("OPENAI_BASE_URL"),
                   "model": openai_model(), "model_from": "OPENAI_MODEL" if env("OPENAI_MODEL") else "default",
                   "sdk_installed": sdk_available(), "api": "responses"},
        "openai_compatible": {"configured": bool(env("OPENAI_BASE_URL")),
                              "model": env("OPENAI_MODEL") or None, "api": "chat.completions"},
    }


def make_client(provider: str, model: str, settings: dict | None = None) -> LLMClient | None:
    """Build exactly the named provider, or None when its key is not configured."""
    settings = settings or {}
    if provider == "anthropic" and env("ANTHROPIC_API_KEY"):
        return AnthropicClient(model if (model or "").startswith("claude") else "claude-sonnet-5-5", env("ANTHROPIC_API_KEY"))
    if provider == "openai" and env("OPENAI_API_KEY") and not env("OPENAI_BASE_URL"):
        from .openai_responses import OpenAIResponsesClient
        return OpenAIResponsesClient(openai_model(), env("OPENAI_API_KEY"),
                                     reasoning_effort=str(settings.get("openai_reasoning_effort", "medium")),
                                     timeout_s=float(settings.get("openai_timeout_seconds", READ_TIMEOUT)))
    if provider in ("openai", "openai_compatible") and env("OPENAI_BASE_URL"):
        return OpenAICompatClient(env("OPENAI_MODEL", model) if (model or "").startswith("claude") else model,
                                  env("OPENAI_API_KEY"), env("OPENAI_BASE_URL"))
    return None


def get_client(provider: str, model: str, settings: dict | None = None) -> LLMClient | None:
    """Single-provider resolution (legacy `model_provider` setting). 'auto' = Claude if its key exists, else OpenAI,
    else an OpenAI-compatible local server. A second provider is never started automatically."""
    order = [provider] if provider not in ("auto", "", None) else ["anthropic", "openai", "openai_compatible"]
    for p in order:
        c = make_client(p, model, settings)
        if c:
            return c
    return None


def parse_json_block(text: str):
    """Extract the first JSON object/array from a model reply."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t
        t = t.rsplit("```", 1)[0]
    for opener, closer in (("{", "}"), ("[", "]")):
        s = t.find(opener)
        e = t.rfind(closer)
        if s != -1 and e > s:
            try:
                return json.loads(t[s:e + 1])
            except json.JSONDecodeError:
                continue
    raise LLMError("model reply was not valid JSON")
