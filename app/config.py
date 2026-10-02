"""Configuration. Secrets come only from environment variables / the server-side .env file; they are never sent to the browser."""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("WFD_DATA_DIR", ROOT / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
(DATA_DIR / "files").mkdir(exist_ok=True)
(DATA_DIR / "schemas").mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "wfd.sqlite3"
CONFIG_DIR = ROOT / "config"
REFERENCE_DIR = ROOT / "reference"


def load_dotenv(path: Path = ROOT / ".env") -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        os.environ.setdefault(k, v)


load_dotenv()


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def secret_status() -> dict:
    """What is configured — booleans only, never the values."""
    return {
        "BRAVE_API_KEY": bool(env("BRAVE_API_KEY")),
        "TAVILY_API_KEY": bool(env("TAVILY_API_KEY")),
        "SEARXNG_URL": bool(env("SEARXNG_URL")),
        "ANTHROPIC_API_KEY": bool(env("ANTHROPIC_API_KEY")),
        "OPENAI_API_KEY": bool(env("OPENAI_API_KEY")),
        "OPENAI_BASE_URL": bool(env("OPENAI_BASE_URL")),
        "EMBEDDINGS": bool(env("EMBEDDING_MODEL")),
    }


def load_pricing() -> dict:
    """Edited prices live in the data folder (persistent across updates); config/pricing.json is the shipped default."""
    for p in (DATA_DIR / "pricing.json", CONFIG_DIR / "pricing.json"):
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    return {"models": {}, "search": {}}


DEFAULT_SETTINGS = {
    "search_provider": "auto",          # auto | brave | tavily | searxng | none
    "model_provider": "auto",           # auto | anthropic | openai | none
    "model_name": "claude-sonnet-5-5",
    "max_search_rounds": 3,             # follow-up rounds after the initial sweep
    "max_queries": 40,
    "results_per_query": 10,
    "pages_per_query": 2,               # go beyond the first results page
    "max_fetch": 60,
    "time_limit_minutes": 20,
    "budget_usd": 3.00,                 # cap on paid model + search spend per CASE, summed across all runs
    "follow_links": True,
    "passages_per_variable": 8,
    "max_passages_per_call": 40,        # batching size, NOT a cap: more evidence = more calls
    "language": "zh",
    "require_approval_over_budget": True,
    # --- model providers (OpenAI support, 2026-10-01). The OpenAI model comes from the OPENAI_MODEL environment variable.
    "coding_mode": "single",            # single (original: one provider via model_provider) | anthropic_only | openai_only |
                                        # dual_independent | anthropic_primary_openai_review | openai_primary_anthropic_review
    "openai_reasoning_effort": "medium",        # low | medium | high | xhigh | max (gpt-6.1-sol default: medium)
    "openai_reasoning_reserve_tokens": 16000,   # added to the visible-output allowance (reasoning counts as output)
    "openai_max_output_tokens": 32000,          # hard cap on max_output_tokens per OpenAI request
    "openai_timeout_seconds": 600,              # per-request read timeout; a timeout is never retried
    "openai_budget_usd": 3.00,                  # cap on OpenAI model spend per CASE (inside the overall budget_usd)
    "max_openai_attempts_per_case": 50,         # every request sent to OpenAI, incl. retries and re-runs
    "max_model_attempts_per_case": 100,         # every request sent to any model provider
}

# Limits that an approval may raise — always to an explicit number, never to "unlimited".
RAISABLE_LIMITS = ("budget_usd", "openai_budget_usd", "max_openai_attempts_per_case", "max_model_attempts_per_case")
