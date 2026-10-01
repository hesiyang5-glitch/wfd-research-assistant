# CHANGELOG.md

Completed changes, newest first. Commit hashes refer to `hesiyang5-glitch/wfd-research-assistant`.

## 2026-10-01 — documentation (branch `docs/project-memory`, not yet on `main`)
- Added `CLAUDE.md`, `PROJECT_SPEC.md`, `ARCHITECTURE.md`, `DECISIONS.md`, `TEST_PLAN.md`, `CHANGELOG.md`, `KNOWN_ISSUES.md`.
- Corrected stale statements in `README.md` (temperature, test counts, verification status) and `DEPLOY.md`
  (repository name, auto-deploy behavior, pre-filled Tavily price, recovery steps, current deployment).
- Recorded owner decision D-020: keep auto-deploy, approval before every push to `main` (closes former K-01).
- No application behavior changed.

## 2026-10-01 — `33a0c5e` In-page confirmations (deployed)
- Re-analyze, Re-run and source exclusion now use in-page dialogs instead of `window.confirm()`/`prompt()`,
  which the owner's browser blocked silently.
- Buttons show "Estimating cost…" while busy; failures appear as on-screen messages.
- `/api/cases/{id}/estimate` returns an HTTP error instead of a 200 with an error body.

## 2026-10-01 — `de5aece` Claude request fix (deployed)
- Stopped sending `temperature` to Anthropic (`claude-sonnet-5-5` rejects it; the first live run's 16 calls all
  failed with HTTP 400, no charge).
- If two consecutive batches fail with the same 4xx error, remaining batches are not sent and are marked with the reason.
- `tests/test_costs.py`: +3 checks (25 total).

## 2026-10-01 — `a83ab50` Cost safety (deployed; first deploy on Render)
- Budget is per case, summed across all runs (model + search); approval raises the case budget to spent +
  worst-case estimate instead of removing the cap; budget changes logged with reviewer name.
- Worst-case budget check before every model call; possibly-billed failures counted at worst case.
- Retry only 429/529/connection errors; timeouts and 5xx not retried; read timeout raised to 600 s.
- Tavily priced at $0.016/request in `config/pricing.json`; budget checked before every query; warning when a
  search provider has no price.
- Unknown model price pauses the run.
- Truncated or unreadable model replies no longer cached.
- `render.yaml`: plan `0.5c-512mb`; removed `BRAVE_API_KEY` prompt.
- Login lockout uses Cloudflare client-address headers and a site-wide failure limit.
- `DEPLOY.md`: removed example password, corrected disk-billing note, added spending-limits section.
- New `tests/test_costs.py` (22 checks); `tests/test_auth.py` updated (24 checks).

## 2026-09-30 / 2026-10-01 — `a1c98ab` First version
- Research pipeline: identity check, 10 source-type query templates, paging, fetching (HTML/PDF/DOCX, OCR
  status), dedupe and syndication detection, relevance check, link following, gap-driven follow-up rounds,
  limits and coverage report, persistent background jobs with resume.
- Codebook/workbook schema loader with versioning, field mapping and 33 rule-issue flags for v1.3 + v1.7.
- Hybrid evidence retrieval (BM25 + LSA/embeddings); batched model coding with prompt rules; server-side validator.
- Review workbench with evidence panel, citation navigation, accept/edit/clear/defer/undo, history, Δ marks.
- Exports: TSV, XLSX review workbook, workbook-aligned case row, JSON.
- Bilingual interface; login (shared password + reviewer name); security headers; Dockerfile and Render Blueprint.
- Tests: `test_pipeline.py` (44), `test_auth.py` (21), `test_ui_flow.py`.
- Also published a static interface preview (claude.ai artifact) built by `tools/build_preview.py`; it cannot search, call models or export.
