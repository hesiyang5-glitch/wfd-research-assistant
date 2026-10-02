# ARCHITECTURE.md — current system

Last reviewed: 2026-10-01 (commit `33a0c5e`; OpenAI provider sections describe branch `feature/openai-provider`, not deployed).

## Overview

```
Browser (web/: index.html, app.js, i18n.js, styles.css — no build step)
   │  JSON over HTTPS, signed session cookie
   ▼
app/server.py  (Python standard-library ThreadingHTTPServer; routes + static files)
   │                         │
   │ enqueue                 │ read/write
   ▼                         ▼
app/jobs.py (1 worker thread) ──► app/db.py (SQLite, WAL)  ◄── /var/data/wfd.sqlite3 on Render disk
   │
   ▼
app/research.py  pipeline
   identify ─► search ─► fetch & dedupe ─► gap check ─► follow-up search ─► coding ─► review
     │           │            │                │                               │
     │      search/providers  ingest.py     retrieval.py                  coding.py ─► llm/clients.py ─► Anthropic API
     │                                                                     │      └► llm/openai_responses.py ─► OpenAI Responses API (optional)
     │      (Tavily API)      (httpx, pdfplumber, OCR)                    validator.py
     ▼
   export.py (TSV / XLSX / case row / JSON)
```

Why this stack: the build environment could not install FastAPI/React from package registries, and a
standard-library server plus SQLite installs in one step and runs anywhere Python runs (see DECISIONS.md).

## Components

| Module | Responsibility |
|---|---|
| `app/config.py` | Paths (`WFD_DATA_DIR`), `.env` loading, default settings, pricing loader (data-dir copy overrides `config/pricing.json`) |
| `app/schema_loader.py` | Parses the codebook (`Variable:` headings, `code = label` lines, missing-value rules, subfields) and workbook header row; maps fields; classifies each field (`sourced`, `judgment`, `derived`, `admin`, `analyst_note`, `unmapped`); flags rule problems and conflicts in existing workbook data |
| `app/search/providers.py` | `TavilySearch` (advanced depth, no paging), `BraveSearch`, `SearxngSearch`; `FixtureSearch` only when `WFD_TEST_FIXTURE` is set (labeled `TEST-FIXTURE` everywhere) |
| `app/ingest.py` | Fetch (public HTTP only, 60 MB cap, honest User-Agent), HTML/PDF/DOCX/TXT extraction, repeated header/footer removal, boilerplate filtering, OCR of text-less PDF pages, passage chunking (no count cap), content hashing, shingle-based near-duplicate detection, source-type heuristic |
| `app/research.py` | Job context, identity scoring, query templates, gap queries, link following, relevance assessment, limits (time, queries, fetches, case budget), coverage report |
| `app/retrieval.py` | Per-case index: BM25 + semantic ranking (embeddings if `EMBEDDING_MODEL` set, else LSA), reciprocal-rank fusion; variable queries built from codebook text only |
| `app/coding.py` | Modes and provider plans (`resolve_plan`), shared evidence preparation (`prepare`), provider-neutral `run_coding` / `run_coding_plan`, server-side `CaseLimits` (budgets and attempt caps from the ledgers), cache keys v2, provider comparison (`suggestion_sets`, `compare_pair`). Batches variables by codebook section (≤40 passages and ≤12 variables per call — batch sizes, not caps; output allowance 1,500 + 1,200 tokens per variable, ceiling 16,000), builds prompts with the coding rules, worst-case budget check per call, failed-call accounting, safe caching, repeated-error stop, derived/admin field generation |
| `app/validator.py` | Validates each suggestion: codebook codes, single vs multi-select, per-option evidence, `-9` only where defined, numeric/date formats, evidence IDs exist, quotes verbatim |
| `app/llm/clients.py` | `AnthropicClient` (Messages API, no `temperature`), `OpenAICompatClient` (legacy, OpenAI-compatible servers via `OPENAI_BASE_URL`, provider `openai_compatible`); provider resolution (`make_client`, `get_client`, `provider_status`); retry only 429/529/connection errors; `LLMError` flags `possibly_billed`, `config_error`, `attempts`; cost math incl. long-context surcharge; stale-price notes |
| `app/llm/openai_responses.py` | `OpenAIResponsesClient`: official SDK, Responses API, strict Structured Outputs, SDK retries off, own retry rules, free model preflight, key redaction, usage incl. reasoning tokens and request ids |
| `app/llm/structured.py` | Builds the strict per-batch JSON Schema from codebook entries; normalizes structured replies into the provider-neutral item format |
| `app/migrations.py` | Additive, repeatable migration; `rollback` / `restore` commands |
| `app/export.py` | Assembles results (display suggestion, every provider's suggestion, comparison, review, category) and writes exports; disagreements never exported without a human value |
| `app/auth.py` | Shared-password login, signed session tokens, lockout (per address + site-wide) |
| `app/jobs.py` | Job queue in SQLite, single worker thread, duplicate-submission guard, restart recovery |
| `app/server.py` | API routes, security headers, JSON-only mutations, health check `/healthz`, refuses public bind without password |

## Data model (SQLite tables)

`schema_versions` (versioned codebook+workbook mapping as JSON) · `settings` · `cases` (incl. per-case settings
and budget) · `jobs` + `job_log` · `search_queries` + `search_results` · `sources` · `passages` (IDs like
`S12-P7`, with page/paragraph) · `runs` · `suggestions` (model or derived values, evidence, counter-evidence,
validation, raw reply) · `reviews` (current human value per variable) + `review_history` (every change, reason,
reviewer) · `usage` (every paid or possibly-paid call, actual or estimated cost) · `cache` (search results,
complete model replies, embeddings).

Added by the OpenAI-provider migration (additive): `model_calls` (append-only: every model request batch with
provider, model, role, run group, batch variables, evidence ids + hash, status, incomplete reason, HTTP attempts,
request/response ids, input/cached/output/reasoning tokens, output limit, cost, cache key/status, duration — never
prompts or keys) · `schema_migrations` · `suggestions_provider_archive` (used only by rollback) · new columns:
`runs.provider/role/group_id/coding_mode/independent`, `suggestions.provider/model/role/group_id/call_id/cache_status`,
`usage.call_id/reasoning_tokens/cached_input_tokens/request_id`, `reviews.source_provider`,
`review_history.source_provider`.

## Pipeline details

1. **Identify** — 3 queries; score results by name/location/year match; pause for a choice if several years compete.
2. **Search** — 10 source-type templates × pages (provider permitting). Every query logged with provider name.
3. **Fetch & dedupe** — candidates ranked by identity score then source type (AAR, government first); up to
   `max_fetch` (60) attempts; exact duplicates by content hash, near-duplicates by shingle containment ≥ 0.6;
   relevance check on full text; follow up to 4 promising links per relevant page.
4. **Gap check** — for each model-coded variable, retrieve top passages and score evidence strength; weak ones (< 0.35) drive follow-up queries.
5. **Follow-up search** — up to `max_search_rounds` (3) rounds of up to 8 gap queries; stops when a round adds no sources.
6. **Coding** — resolve the mode's provider plan (pause if a needed key is missing) → free model availability check →
   per-provider worst-case estimate → pause if any case limit could be exceeded → one shared evidence preparation →
   batched calls per provider (limits re-checked before every request) → validation → suggestions stored per provider
   and role → derived/admin fields computed once → provider comparison.
7. **Review** — humans accept/edit/clear/defer; exports default to reviewed values.

## Storage and persistence

- Local: `./data/` (SQLite `wfd.sqlite3`, `files/` downloaded sources and uploads, `schemas/` uploaded codebooks/workbooks, `pricing.json` if edited, `.session_secret` if `WFD_SECRET` unset).
- Render: same layout under `/var/data`, a 5 GB persistent disk; survives restarts and redeploys; Render snapshots it daily (kept ≥ 7 days).

## Deployment

- GitHub `hesiyang5-glitch/wfd-research-assistant` (private), branch `main`.
- Render Blueprint `wfd-coding-assistant` → web service `wfd-coding-assistant` (Docker, plan `0.5c-512mb`, Oregon), URL `https://wfd-coding-assistant.onrender.com`, health check `/healthz`.
- **Auto-deploy is on** (kept by owner decision D-020; every push to `main` needs prior approval): every push to `main` builds and deploys (~1 min build, 1–2 min downtime because a service with a disk cannot do zero-downtime deploys).
- Image: `python:3.11-slim` + Tesseract; `WFD_HOST=0.0.0.0`, `WFD_DATA_DIR=/var/data`, `WFD_TRUST_PROXY=1`; listens on Render's `PORT` (10000).

## External services

| Service | Used for | Credential | Cost accounting |
|---|---|---|---|
| Tavily | web search | `TAVILY_API_KEY` | $0.016/request counted (2 credits × $0.008); free credits make real cost $0 until exhausted |
| Anthropic | coding suggestions (`claude-sonnet-5-5`) | `ANTHROPIC_API_KEY` | $2 / $10 per million input/output tokens (checked 2026-09-30) |
| Render | hosting | Render account | $7/month instance + $1.25/month disk |
| OpenAI (optional, branch only) | coding suggestions via Responses API (`OPENAI_MODEL`, default `gpt-6.1-sol`) | `OPENAI_API_KEY` | $2 / $10 per million input/output tokens, reasoning billed as output; >272K input tokens 2× / 1.5× (checked 2026-10-01) |
| Brave / SearXNG / OpenAI-compatible / embeddings | optional alternatives | env vars | not configured in production |

## Security model

Single shared team password (`WFD_PASSWORD`) plus a self-declared reviewer name recorded in history; signed
HttpOnly SameSite=Lax cookie (secret `WFD_SECRET`, generated by Render); all signed-in users have equal rights,
including settings and budgets. Mutating requests must be JSON. CSP `default-src 'self'`. Keys never leave the
server; `/api/status` reports only whether each key is set.

## Model providers (branch `feature/openai-provider`)

- **Modes** (`coding_mode`; per run via the re-analysis dialog): `single` (default, original behavior), `anthropic_only`,
  `openai_only`, `dual_independent`, `anthropic_primary_openai_review`, `openai_primary_anthropic_review`.
- **One evidence corpus.** Search/fetch happen once per case. `prepare()` builds batches and prompts once per job; every
  provider gets the identical case + evidence prompt (same passage ids; batching is the same for both today, and each
  `model_calls` row records its variables and evidence ids/hash so any future difference is visible).
- **Normalized results.** Claude replies (JSON text) and OpenAI replies (strict schema) are converted to the same item
  list and checked by the same validator. Stored per provider, model, role and run group; human reviews stay in `reviews`.
- **Display / export.** The display suggestion is the primary's (or, in dual mode, the first provider's). If providers
  disagree or an output is invalid, the variable is "disputed", plain "accept" is refused (a specific provider's
  suggestion must be chosen) and no unreviewed value is exported.
- **Limits** (`CaseLimits`, read from `usage` + `model_calls` before every request): combined budget, OpenAI budget,
  OpenAI attempts, total model attempts. Retries inside a request are capped by the remaining attempts.
- **Incomplete replies.** OpenAI `status=incomplete` (reason recorded, e.g. `max_output_tokens`), refusals, invalid JSON
  and schema violations are billed at actual usage when reported, logged, discarded and never cached.
- **Cache key v2** — see DECISIONS D-026.
- **Stop / resume** (D-030): `provider_controls(job_id, provider, stop_requested)` is read before every batch; never-sent
  batches are stored as `stopped`; Resume queues a follow-up job (`params.resume`) that codes only stopped variables in
  the same `group_id`. `limit_changes` records every case-limit change (who, old, new, why).
- **Bulk agreement confirmation** (D-032): `app/agreement.py` (`assess`, `eligible_summary`, `bulk_confirm`); audit in `bulk_confirmations`; `reviews.method`.
- **Review cells** (D-031): `suggestion_sets()` returns one cell per provider column (latest result of that provider
  across runs), the display suggestion, the comparison and system rows.
