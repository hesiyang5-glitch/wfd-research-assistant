"""OpenAI provider: official `openai` Python SDK, Responses API, Structured Outputs (strict JSON Schema).

Checked against developers.openai.com on 2026-10-01 and the SDK source (openai-python 3.23.0):
- `client.responses.create(model=, instructions=, input=, max_output_tokens=, reasoning={"effort": ...},
  text={"format": {"type": "json_schema", "name": ..., "schema": ..., "strict": True}}, store=False)`
- `response.status` is "completed" or "incomplete"; `response.incomplete_details.reason` is e.g. "max_output_tokens"
  or "content_filter". Reasoning tokens are billed as output tokens and count against `max_output_tokens`.
- `response.usage.input_tokens`, `.input_tokens_details.cached_tokens`, `.output_tokens`,
  `.output_tokens_details.reasoning_tokens`; `response._request_id` holds the `x-request-id` header.
- The SDK retries by default; it is created with `max_retries=0` so this module alone decides what is retried.

Retry rules (same principle as the Claude adapter): only requests that certainly were not processed are retried —
a connection that never opened, or HTTP 429 rate limiting. Read timeouts, broken connections after sending and
5xx errors are NOT retried and are reported as possibly billed. Missing/unavailable model, bad key, no permission
or exhausted quota are configuration errors: never retried, and the run stops at once.

The API key is read only from OPENAI_API_KEY on the server and is removed from every error message.
"""
from __future__ import annotations

import re
import time

from .clients import LLMClient, LLMError, READ_TIMEOUT

DEFAULT_OPENAI_MODEL = "gpt-6.1-sol"
REASONING_EFFORTS = ("low", "medium", "high", "xhigh", "max")  # gpt-6.1-sol: "none"/"minimal" not supported
_PREFLIGHT_OK: dict[str, float] = {}  # model -> time of last successful availability check (process-local)
PREFLIGHT_TTL = 3600.0


def redact(msg: str, key: str = "") -> str:
    s = str(msg or "")
    if key:
        s = s.replace(key, "[redacted]")
    s = re.sub(r"sk-[A-Za-z0-9_\-*.]{4,}", "sk-[redacted]", s)
    s = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9_\-.]+", r"\1[redacted]", s)
    return s[:400]


def sdk_available() -> bool:
    try:
        import openai  # noqa: F401
        return True
    except Exception:
        return False


class OpenAIResponsesClient(LLMClient):
    provider = "openai"
    supports_schema = True
    api = "responses"

    def __init__(self, model: str, key: str, reasoning_effort: str = "medium", timeout_s: float = READ_TIMEOUT,
                 sdk_client=None, sleep=None):
        super().__init__(model)
        self._key = key
        self.reasoning_effort = reasoning_effort if reasoning_effort in REASONING_EFFORTS else "medium"
        self.timeout_s = float(timeout_s)
        self._client = sdk_client
        self._sleep = sleep or (lambda s: time.sleep(s))

    def __repr__(self):  # never show the key
        return f"OpenAIResponsesClient(model={self.model!r}, effort={self.reasoning_effort!r})"

    def generation_settings(self) -> dict:
        """Settings that change the reply; part of the cache key."""
        return {"api": "responses", "reasoning_effort": self.reasoning_effort, "store": False}

    def _sdk(self):
        if self._client is None:
            try:
                import httpx2
                from openai import OpenAI
            except ImportError as e:
                raise LLMError("the official `openai` Python package is not installed on the server "
                               "(requirements.txt: openai>=3.23)", config_error=True) from e
            self._client = OpenAI(api_key=self._key, max_retries=0,
                                  timeout=httpx2.Timeout(self.timeout_s, connect=15.0))
        return self._client

    # ------------------------------------------------------------------ errors
    def _translate(self, e: Exception, attempts: int) -> tuple[LLMError | None, bool]:
        """Map an SDK exception to (error to raise, retry?)."""
        import openai
        msg = redact(f"{type(e).__name__}: {getattr(e, 'message', None) or e}", self._key)
        if isinstance(e, openai.APIConnectionError):  # includes APITimeoutError
            import httpx2
            cause = e.__cause__
            if isinstance(cause, (httpx2.ConnectError, httpx2.ConnectTimeout, httpx2.PoolTimeout)):
                return LLMError(f"could not connect to OpenAI: {msg}", attempts=attempts), True
            what = "timed out waiting for the reply" if isinstance(e, openai.APITimeoutError) else \
                "connection broke after the request was sent"
            return LLMError(f"OpenAI request {what}; not retried because it may already have been billed",
                            possibly_billed=True, attempts=attempts), False
        if isinstance(e, openai.APIStatusError):
            code = (getattr(e, "code", None) or "")
            status = getattr(e, "status_code", 0) or 0
            rid = getattr(e, "request_id", None)
            if status == 429 and code == "insufficient_quota":
                return LLMError(f"OpenAI account has no remaining quota/credit (HTTP 429 insufficient_quota). Check billing "
                                f"for this API project. {msg}", config_error=True, attempts=attempts, request_id=rid), False
            if status == 429:
                return LLMError(f"HTTP 429 rate limited: {msg}", attempts=attempts, request_id=rid), True
            if status in (401, 403) or code in ("model_not_found",) or status == 404:
                why = {401: "the OpenAI API key was rejected", 403: "this API project has no permission for the request",
                       404: f"model '{self.model}' is not available to this API project"}.get(status, "configuration error")
                if code == "model_not_found":
                    why = f"model '{self.model}' is not available to this API project"
                return LLMError(f"OpenAI configuration error: {why} (HTTP {status}). Set OPENAI_MODEL / OPENAI_API_KEY "
                                f"correctly; nothing was retried. {msg}", config_error=True, attempts=attempts,
                                request_id=rid), False
            if status >= 500:
                return LLMError(f"HTTP {status} from OpenAI; not retried because it may already have been billed: {msg}",
                                possibly_billed=True, attempts=attempts, request_id=rid), False
            return LLMError(f"HTTP {status}: {msg}", attempts=attempts, request_id=rid), False
        return LLMError(f"OpenAI client error: {msg}", attempts=attempts), False

    # ------------------------------------------------------------------ preflight (free)
    def preflight(self) -> None:
        """Confirm the configured model exists for this API project (GET /v1/models/{model}; not a billed call).
        Raises a configuration error instead of letting every batch fail."""
        if time.time() - _PREFLIGHT_OK.get(self.model, 0) < PREFLIGHT_TTL:
            return
        import openai
        try:
            self._sdk().models.retrieve(self.model)
        except openai.OpenAIError as e:
            err, _ = self._translate(e, 0)
            if isinstance(e, openai.APIStatusError) and getattr(e, "status_code", 0) == 404:
                err = LLMError(f"OpenAI configuration error: model '{self.model}' is not available to this API project. "
                               f"Set OPENAI_MODEL to a model the project can use; nothing was sent for coding.",
                               config_error=True, attempts=0)
            if err.possibly_billed:  # a models lookup is never billed; treat as a plain failure
                err.possibly_billed = False
            raise err from e
        _PREFLIGHT_OK[self.model] = time.time()

    # ------------------------------------------------------------------ main call
    def complete(self, system, user, max_tokens=4000, schema=None, schema_name="wfd_batch", max_attempts=3):
        import openai
        kwargs = {"model": self.model, "instructions": system, "input": user, "max_output_tokens": int(max_tokens),
                  "reasoning": {"effort": self.reasoning_effort}, "store": False}
        if schema is not None:
            kwargs["text"] = {"format": {"type": "json_schema", "name": schema_name, "schema": schema, "strict": True}}
        attempts, last = 0, None
        for i in range(max(1, int(max_attempts))):
            attempts += 1
            try:
                resp = self._sdk().responses.create(**kwargs)
            except openai.OpenAIError as e:
                err, retry = self._translate(e, attempts)
                if retry and i + 1 < max_attempts:
                    last = err
                    self._sleep(3 * (i + 1))
                    continue
                raise err from e
            return self._normalize(resp, attempts)
        raise last or LLMError("failed after retries", attempts=attempts)

    @staticmethod
    def _normalize(resp, attempts: int) -> dict:
        u = getattr(resp, "usage", None)
        itd = getattr(u, "input_tokens_details", None) if u else None
        otd = getattr(u, "output_tokens_details", None) if u else None
        refusal = ""
        for item in getattr(resp, "output", None) or []:
            if getattr(item, "type", "") == "message":
                for c in getattr(item, "content", None) or []:
                    if getattr(c, "type", "") == "refusal":
                        refusal = getattr(c, "refusal", "") or "refused"
        status = getattr(resp, "status", None) or "completed"
        inc = getattr(resp, "incomplete_details", None)
        reason = getattr(inc, "reason", None) if inc else None
        if refusal:
            stop = "refusal"
        elif status == "incomplete":
            stop = "max_output_tokens" if reason == "max_output_tokens" else f"incomplete:{reason or 'unknown'}"
        elif status == "completed":
            stop = "end_turn"
        else:
            stop = f"status:{status}"
        return {"text": getattr(resp, "output_text", "") or "", "input_tokens": getattr(u, "input_tokens", None) if u else None,
                "cached_input_tokens": getattr(itd, "cached_tokens", None) if itd else None,
                "output_tokens": getattr(u, "output_tokens", None) if u else None,
                "reasoning_tokens": getattr(otd, "reasoning_tokens", None) if otd else None,
                "stop_reason": stop, "status": status, "incomplete_reason": reason, "refusal": refusal[:300],
                "request_id": getattr(resp, "_request_id", None), "response_id": getattr(resp, "id", None),
                "attempts": attempts}
