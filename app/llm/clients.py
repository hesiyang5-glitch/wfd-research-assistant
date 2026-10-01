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

    def __init__(self, msg: str, possibly_billed: bool = False):
        super().__init__(msg)
        self.possibly_billed = possibly_billed


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
    p = price_for(model)
    if not p or p.get("input_per_mtok") is None:
        return None
    return round(in_tok / 1e6 * p["input_per_mtok"] + out_tok / 1e6 * p["output_per_mtok"], 5)


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

    def complete(self, system, user, max_tokens=4000):
        body = {"model": self.model, "max_tokens": max_tokens, "system": system,
                "messages": [{"role": "user", "content": user}], "temperature": 0}
        last = None
        for attempt in range(4):
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
                               f"may already have been billed", possibly_billed=True) from e
            if r.status_code in RETRY_STATUS_ANTHROPIC:
                last = f"HTTP {r.status_code}: {r.text[:200]}"
                time.sleep(3 * (attempt + 1))
                continue
            if r.status_code >= 500:
                raise LLMError(f"HTTP {r.status_code} from provider; not retried because it may already have been billed: "
                               f"{r.text[:200]}", possibly_billed=True)
            if r.status_code != 200:
                raise LLMError(f"HTTP {r.status_code}: {r.text[:300]}")
            j = r.json()
            text = "".join(b.get("text", "") for b in j.get("content", []) if b.get("type") == "text")
            u = j.get("usage", {})
            return {"text": text, "input_tokens": u.get("input_tokens"), "output_tokens": u.get("output_tokens"),
                    "stop_reason": j.get("stop_reason")}
        raise LLMError(last or "failed after retries")


class OpenAICompatClient(LLMClient):
    """OpenAI or any OpenAI-compatible server (e.g. a local Ollama / LM Studio / vLLM model via OPENAI_BASE_URL)."""
    provider = "openai"

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


def get_client(provider: str, model: str) -> LLMClient | None:
    order = [provider] if provider not in ("auto", "", None) else ["anthropic", "openai"]
    for p in order:
        if p == "anthropic" and env("ANTHROPIC_API_KEY"):
            return AnthropicClient(model if model.startswith("claude") else "claude-sonnet-5-5", env("ANTHROPIC_API_KEY"))
        if p == "openai" and (env("OPENAI_API_KEY") or env("OPENAI_BASE_URL")):
            return OpenAICompatClient(env("OPENAI_MODEL", model) if model.startswith("claude") else model,
                                      env("OPENAI_API_KEY"), env("OPENAI_BASE_URL", "https://api.openai.com/v1"))
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
