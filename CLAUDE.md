# CLAUDE.md — instructions for Claude sessions in this repository

Read this first. It is short on purpose; details live in the files listed under "Where things are".

## What this project is

WFD Coding Assistant: a web app that helps researchers code incidents for the **Warning Failure Database (WFD)**
(University of Colorado Denver / Colorado School of Public Health; PIs Hamilton Bean and Katie Dickinson).
A user enters an incident name, location and approximate date. The app searches the web in several rounds,
reads the sources, retrieves evidence for each codebook variable, asks Claude for **suggested** codes,
validates them on the server, and gives researchers a review workbench and Excel export.

The user (project owner) is a student researcher, not a professional developer. Explain decisions plainly,
in Chinese and English when talking to them, and never imply that something untested is production-ready.

## Authority order (when sources disagree)

1. The current GitHub repository and deployed code
2. The current WFD codebook (`CODEBOOK v1.3.docx` in the claude.ai Project; plain-text variable excerpt in `reference/`)
3. The current WFD workbook (`reference/MASTER_WFD_Pilot_Workbook_v1.7.xlsx`)
4. This file, then `PROJECT_SPEC.md`, `ARCHITECTURE.md`, `DECISIONS.md`, `TEST_PLAN.md`, `CHANGELOG.md`,
   `KNOWN_ISSUES.md`, `DEPLOY.md`
5. Chat history and memory (least authoritative)

If a request conflicts with an established requirement here, point out the conflict and ask before changing it.

## Start of every task

1. Inspect the repository (`git log`, the files you will touch, these docs).
2. Summarize briefly: current state, the requested change, affected files, risks (research validity, data loss,
   security, deployment, API cost), and your test plan.
3. Say clearly if any repository, file or service access is unavailable.
4. Don't modify code until the request is clear; ask only questions that change the implementation.

## Non-negotiable coding rules (WFD research)

- Never invent a code, category, variable or definition. Codes come only from the active codebook entry.
- `-9` (or any special missing value) is allowed **only** where that variable's codebook entry defines it.
- Insufficient evidence → blank value or explicit review flag. Blank is the default.
- Every substantive suggestion must cite real passage IDs with verbatim quotes; the server validates this.
- Separate the observed failure from its cause. Several possible causes establish none of them; an uncertain
  cause must not erase a documented failure. Preserve conflicting evidence.
- Model suggestions stay separate from human-approved values. Reanalysis never overwrites reviewed values.
- Several providers (Claude, OpenAI) get the same evidence and codebook; agreement between models is not verification,
  disagreement goes to human review. A second provider never starts unless a mode is chosen explicitly.

## Non-negotiable engineering rules

- **Pushing to `main` deploys to production.** Render auto-deploys every push to `main`
  (see `DEPLOY.md`). Owner decision D-020: ask and get explicit approval **before every push or merge to `main`**
  (approval for one push does not carry over). Use a branch otherwise.
- Never put secrets (API keys, passwords, tokens) in code, Git, frontend files, logs, docs or screenshots.
  Secrets live only in Render environment variables or a local untracked `.env`.
- Before any action that can create charges, delete data, change deployment resources or expose the app,
  explain the effect and get explicit approval.
- Cost safety must hold: per-case budget across all runs; approval raises the cap to an explicit amount and
  never removes it; no automatic retry of possibly-billed calls; never cache truncated/invalid model replies.
- Small, reviewable changes. Inspect existing code first. Preserve user data (SQLite on the Render disk).
- Never claim something was tested if it was not. Distinguish offline tests (fixtures/fakes) from live checks.

## Commands

```bash
python3 -m app.server                 # run locally on http://127.0.0.1:8765 (data in ./data)
python3 -m tests.test_pipeline        # schema, retrieval, dedupe, validation, review, export, persistence
python3 -m tests.test_costs           # budget, retry, caching, search-cost rules (fake model, no network)
python3 -m tests.test_auth            # login, lockout, sessions, CSRF guard (starts local servers)
python3 -m tests.test_ui_flow         # browser click-through (Playwright + Chromium)
python3 -m tests.test_providers       # OpenAI provider, modes, limits, cache keys, migration, UI (mocked SDK transport)
```

Tests need the Texas-flood sample PDFs: set `WFD_TEST_PDFS=/path/to/folder` (they are in the claude.ai
Project under `WFD project/sources/20250704-TX01/`). Tests run fully offline.

## Where things are

| Path | What |
|---|---|
| `app/schema_loader.py` | codebook + workbook → variable dictionary, field mapping, rule-issue flags |
| `app/research.py` | pipeline: identify → search → fetch → gap check → follow-up → coding; budgets |
| `app/search/providers.py` | Tavily / Brave / SearXNG adapters; `TEST-FIXTURE` provider for tests only |
| `app/ingest.py` | fetching, HTML/PDF/DOCX extraction, OCR status, passages, dedupe, source typing |
| `app/retrieval.py` | BM25 + semantic (LSA or embeddings) evidence retrieval |
| `app/coding.py` | prompt rules, batching, worst-case budget checks, derived/admin fields |
| `app/validator.py` | server-side validation of codes, quotes, evidence IDs, missing-value rules |
| `app/llm/clients.py` | Anthropic and OpenAI-compatible adapters, provider resolution, retry policy, cost math |
| `app/llm/openai_responses.py`, `app/llm/structured.py` | OpenAI (official SDK, Responses API) and its strict per-batch schema |
| `app/migrations.py` | additive DB migration; `rollback` / `restore` |
| `app/export.py` | TSV / XLSX / workbook-aligned case row / JSON |
| `app/server.py`, `app/auth.py`, `app/jobs.py`, `app/db.py` | HTTP API, login, background jobs, SQLite |
| `web/` | no-build HTML/JS interface (bilingual) |
| `config/pricing.json` | editable model and search prices (shipped defaults) |
| `render.yaml`, `Dockerfile` | Render Blueprint and container image |
| `tools/` | builds the static interface preview (not part of the app) |

## Before finishing a material task

Update the relevant docs (`DECISIONS.md` for decisions, `CHANGELOG.md` for changes, `KNOWN_ISSUES.md` for open
problems, `TEST_PLAN.md` if acceptance criteria change, `DEPLOY.md` if deployment changes), run the tests,
commit with a clear message, and end with a handoff: what changed, files, tests and results, deployment status,
remaining issues, next step, and whether any paid action is required.
