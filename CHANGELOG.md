# CHANGELOG.md

Completed changes, newest first. Commit hashes refer to `hesiyang5-glitch/wfd-research-assistant`.





## 2026-10-06 — "GPT coding — OpenAI API" label (merged to `main` 2026-10-06 with owner approval)
- Owner choice: the coding lines name the model family on both sides — "Claude coding — Anthropic API" and
  "GPT coding — OpenAI API" (Services, cost estimates, Re-analyze, Stop dialog title, "Spent" line, server reason text).
  Mode names ("OpenAI only — OpenAI API"), "OpenAI suggestion" and the budget labels from the owner's label table
  ("OpenAI coding budget per case") are unchanged. Label only: payloads and cost numbers verified identical.
- Tests: `test_ui_labels` 37 (1 new check, 3 expectations updated).

## 2026-10-06 — Interface terminology standardized (merged to `main` 2026-10-06 with owner approval)
- **This change modifies interface labels and explanatory copy only. It does not change provider behavior, model
  requests, evidence handling, caching, pricing, database structure, or coding results.**
- Three levels are named consistently: provider (Anthropic / OpenAI), API (Anthropic API / OpenAI API) and model
  (the identifier the backend already supplies: the `model_name` setting for Claude, `OPENAI_MODEL` for OpenAI).
  "Claude (Anthropic)" vs "OpenAI" pairings removed; no "ChatGPT API"; no primary/secondary wording.
- `web/app.js`, `web/i18n.js`: Services grouped (External services / AI coding providers / Internal processing, with
  API, OCR, LSA and BM25 expanded); readable Settings labels (keys only as tooltips; option values unchanged);
  provider cards with model identifiers; cost estimate names (Shared web research, Expected cost, Maximum estimated
  cost, Cached requests, New paid requests, Not selected — $0.00); Re-analyze dialogs, Progress, Stop/Resume and
  Review use the same names. `app/server.py`, `app/coding.py`, `app/research.py`: display names in user-facing
  reasons, run logs and job messages only (`PROVIDER_LABELS`, used in stored prompts and exports, is unchanged).
- Tests: new `tests/test_ui_labels.py` (36) — labels in every affected view, plus unchanged request payloads, settings
  keys/values, cost numbers, cache keys, database schema, prompt, stored results and Human final values (fingerprints
  pinned from `main` 302a2f2). `tests/test_independent_providers.py`: three wording assertions updated to the new
  labels ("Not selected", "Shared web research", "Combined — maximum estimated cost"). Full label table:
  `docs/ui_terminology_labels.md`.

## 2026-10-06 — Provider-neutral evidence status (merged to `main` 2026-10-06 with owner approval)
- D-038. New `app/evidence_status.py` (five statuses, resolution rules, legacy read-time derivation). Shared prompt
  rules and reply format ask both providers for `evidence_status`, `rule_unclear`, `alternatives`, `missing_evidence`
  (`PROMPT_VERSION` `wfd-prompt-2026-10-06`); OpenAI strict schema `wfd-batch-v2`; `normalize_structured` still reads v1.
- Migration `2026-10-06-evidence-status` (additive, repeatable): four nullable columns on `suggestions`. Old rows untouched.
- `app/coding.py`: stores evidence status, validation status, validated alternatives, missing evidence; replies without
  an evidence status are not cached; the combined view keeps each provider's status; INFERRED/AMBIGUOUS/... never feed
  derived fields. Typical output estimate 260 → 320 tokens per variable.
- `app/agreement.py`: bulk-eligible only when both providers are SUPPORTED (legacy "not recorded" results keep earlier
  eligibility, disclosed). `app/export.py`: Results "Evidence status" / "Validation status"; Provider_Suggestions adds
  evidence status, validation status, alternative values, missing evidence; INFERRED never exported unreviewed;
  Case_Row unchanged. `web/app.js`: evidence-status badge in cells; detail panel shows the two statuses separately,
  alternatives and missing evidence (bilingual).
- Tests: new `tests/test_evidence_status.py` (59). Existing test stand-ins now answer with `evidence_status`; the pinned
  Claude system-prompt hash was updated deliberately (`test_providers`). All 12 suites pass offline.

## 2026-10-06 — Multi-select validation per selection (merged to `main` 2026-10-06 with owner approval)
- D-037. `app/validator.py`: per-selection validation, no redundant top-level evidence for multi-select, JSON-list
  values accepted, `partially_valid` outcome, machine-readable `reason_codes`/`selections`/`rejected_citations`,
  structural problems = `malformed_output`.
- `app/coding.py`: stores status `partially_valid` (not cached); comparison routes partial results to human review;
  neutral combined view keeps the partial status. `app/agreement.py`: partial results never bulk-eligible.
  `app/export.py`: "Partially valid" cell; not exported unreviewed. `web/app.js`: cell tag and rejected-selection note.
- Intended behaviour change: `test_pipeline` multi-select case (one option without its own evidence) is now
  `partially_valid` with the supported code kept, instead of `validation_failed`.
- Tests: new `tests/test_multiselect_validation.py` (24); all 11 suites pass offline.
## 2026-10-05 — Services list without a single "Language model"; interface files never served stale (merged to `main` 2026-10-06 with owner approval)
- The home page's Services list no longer shows one "Language model" line (a leftover of the legacy single-provider
  default that suggested Claude was the model); Claude and OpenAI are listed side by side as before (D-036). The line
  only appears when no model is configured.
- K-16: `Cache-Control: no-cache, must-revalidate` on interface files.
- Tests: `test_independent_providers` 68 (2 new checks); auth, providers, UI flow pass.

## 2026-10-05 — Equal independent providers, provider choice on the first form, matched vs cross-version comparison (merged to `main` 2026-10-05 with owner approval after a backup; live verification pending)
- D-036 (D-035 retained). Migration `2026-10-05-independent-providers` (additive): `evidence_snapshots` (with passage
  hashes), `analysis_specs`; new columns on runs, suggestions, model_calls, bulk_confirmations. Nothing old is rewritten.
- Neutral providers: new runs `independent`; cross-model review refused for new runs (history labelled
  `cross_model_review`); no Claude-preferred default; neutral wording; export "Interpretation" columns.
- Two comparison classes: matched version (ticked by default) and cross-version (eligible under D-035, not ticked,
  warning + acknowledgement required; codebook-version differences never bulk-confirmed); version-difference panel;
  full audit of class, differences, warning, acknowledgement, versions, selection.
- K-40 fixed: cache keyed by model-visible input, not role; earlier entries still found (read-only); not weakened by D-035.
- First form: Coding provider choice, estimate per mode, confirmation, free availability check, one-request minimum,
  optional pause after research. Re-analyze uses the same mode list.
- Tests: new `test_independent_providers.py` (66) and `test_cross_version.py` (27), both with browser checks and a
  network guard; `test_providers` 141, `test_bulk_agreement` 67. All 10 suites pass offline.

## 2026-10-02 — Session handoff (documentation only)
Completed and tested (offline suites; live where stated):
- D-033 incident fix: deployed `f664344`; on Render thread pools = 1 and no failed health checks after deploy (owner).
- D-035 separate-run bulk confirmation: offline 64/64 bulk tests + all suites pass; merged `2fbd11b`.
Completed but not fully tested:
- `2fbd11b` live: deploy pushed, owner did not yet confirm "Deploy live" or try the dialog; Excel sync test (accept/edit/bulk/export, edit kept after re-analysis) not yet done live.
- Full OpenAI-only run completed live ($0.465); per-batch reasoning tokens / cut-offs not yet inspected; Render Events during the run not seen.
Unresolved: K-40 (cache does not cross single/dual modes), K-41, K-06/K-26 cost reconciliation, K-04 coding accuracy.
Deferred/planned: K-40 fix; lower OpenAI reasoning reserve from measured data (K-27); "Re-analyze selected" (K-42); Anthropic key rotation before 2026-10-31 (K-22).

## 2026-10-02 — Bulk confirmation for agreement from separate runs (merged to `main` 2026-10-02 with owner approval; live check pending)
- `app/agreement.py`: new status `eligible_separate_runs` (D-035); core checks kept, prompt/evidence differences become
  warnings; confirmations use method `bulk_separate_run_agreement` with warnings in the reason and audit row.
- Dialog: separate-run items unticked by default with a warning; Confirm stays disabled until something is ticked.
- Export: Results "Confirmation method" and Explanation name separate-run confirmations.
- Tests: `tests/test_bulk_agreement.py` 64 checks (was 50) incl. browser; also checked by hand on a copy of the
  `c57214a` legacy fixture that old Claude results (no prompt version) plus a later OpenAI run become eligible with a
  warning. Not tested on the production data.

## 2026-10-02 — Default case budget $3 → $5 (branch `feature/budget-default-5`, NOT merged, NOT deployed)
- `app/config.py`: `budget_usd` default 5.00 (D-034, owner approved). OpenAI sub-budget ($3) and attempt caps unchanged.
- `app/coding.py`: the fallback in `limit_needs` now reads the default instead of a hard-coded 3.0.
- `tests/test_costs.py`: checks the new default; the per-case budget test now pre-spends "default − $0.05" instead of
  a fixed $2.95, so it keeps testing the pause/approval path at any default.
- Tests (offline, 2026-10-02): test_costs 32/32, test_pipeline 44/44, test_auth 24/24, test_legacy_migration 18/18,
  test_bulk_agreement 50/50, test_resilience 31/31, test_ui_flow PASS. **Not run:** test_providers (the OpenAI SDK's
  dependencies `httpx2` and `jiter` could not be installed in this environment; PyPI unreachable).
- Not changed: existing cases keep their stored budget; team defaults saved on the Settings page override the shipped
  default (see D-034).

## 2026-10-02 — Stay responsive under load; pause interrupted jobs (merged `f664344`, deployed 10:50 am with owner approval; thread limit verified on Render)
- Numerical libraries limited to 1 thread (`app/__init__.py`, Dockerfile); `WFD_NATIVE_THREADS` overrides (D-033).
- Evidence index built once per case/evidence set and shared by gap check, estimates, coding and evidence search;
  rebuilt automatically when sources are added, excluded or restored (`retrieval.get_index`).
- Background worker runs at lower CPU priority than web requests.
- After a restart, a running job is paused ("Interrupted by a server restart") with Resume / Cancel on the Progress
  page; it is no longer restarted automatically.
- Model requests are recorded as `sending` (worst-case cost) before they are sent; at startup unfinished ones become
  `interrupted_possibly_billed` and are counted at worst case.
- Tests: new `tests/test_resilience.py` (31 checks); all 8 suites pass offline. Not tested: on Render (the 0.5-CPU
  quota cannot be reproduced locally; the load test pins to one core and did not reproduce the original failure on the
  old code either, so it shows no regression, not proof of the fix); the interrupted-job notice in a browser.

Status at handoff (2026-10-02):
- Completed and tested offline: thread limit, shared index, worker priority, paused recovery, pre-send ledger.
- Completed, not fully tested: behavior on Render; interrupted-job notice in a browser.
- Root cause confirmed on Render 2026-10-02 (32 threads per pool under a 0.5-CPU quota; 1,682 throttled periods).
- Render event reason: "HTTP health check failed (timed out after 5 seconds)", not out of memory.
- Unresolved: memory peak not checked; K-39.
- Deferred: larger instance / separate worker (paid; only if the problem recurs).

## 2026-10-01 — Production: bulk agreement merged (`66f53f8`), OpenAI key added, first live dual test
- Owner approved; `66f53f8` auto-deployed. Owner added `OPENAI_API_KEY` in Render.
- Single-variable dual re-analysis (SYSTEM_LEVEL, Marshall Fire) completed; both providers' results shown; app-recorded
  cost about $0.02. During it Render health checks failed and the service restarted (502); the old code re-queued the
  job, which then finished. Fix on branch `fix/health-under-load` (above).

## 2026-10-01 — Bulk confirmation of independent model agreement (branch `feature/bulk-agreement`, NOT merged, NOT deployed)
- New `app/agreement.py`: eligibility rules (D-032) and `bulk_confirm()`; endpoints `GET /api/cases/{id}/bulk_agreements`
  (read-only) and `POST /api/cases/{id}/bulk_confirm` (requires `confirmed: true`; re-checks eligibility in one
  transaction; never touches a variable that has any review).
- Review tab: "Confirm N model agreements…" button and a dialog listing each eligible variable (checkbox, agreed value
  and label, Claude/OpenAI model and result ids, evidence-difference flag), excluded count with reasons, and the warning
  that agreement does not prove correctness. Comparison column shows the agreement status.
- Two blank answers are now "Both insufficient", no longer "Model agreement" (also changes that label for existing
  dual runs; exports unchanged because both values were blank).
- Runs record `prompt_version`; reviews/history record `method`; new audit table `bulk_confirmations`
  (additive migration). Export: Results gains "Agreement status" and "Confirmation method"; new `Bulk_Confirmations`
  sheet; Case_Row carries confirmed values only.
- Tests: new `tests/test_bulk_agreement.py` (50 checks incl. browser); `tests/test_providers.py` updated for
  "Both insufficient".

## 2026-10-01 — Per-provider Stop/Resume, provider review table, legacy-data migration test (branch `feature/openai-provider`, NOT deployed)
- Progress page: separate **Stop Claude / Stop OpenAI / Resume Claude / Resume OpenAI** buttons (D-030). Stop is checked
  before every batch: batches not yet sent are recorded as "stopped" (never sent, never billed); a request already sent
  finishes and is kept and billed; completed and cached results are kept; the other provider keeps going. The stop
  dialog warns that a sent request may still finish and be billed. Resume withdraws a stop that has not taken effect,
  or queues a follow-up job that codes only the stopped variables in the same comparison group.
- Review table columns are now `# | Variable | Claude suggestion | OpenAI suggestion | Human final | Comparison |
  Review status` (D-031). Each provider column shows that provider's latest result across runs, so one provider can
  never hide or replace the other; a stopped run never hides an earlier completed result. Distinct states: Not run,
  No supported value, Stopped, Failed, Invalid output, Limit reached, Disputed. Fields no model codes (IDs, derived,
  admin, analyst notes) span both columns as "not model-coded".
- Review detail panel: "Re-analyze this variable" (same dialog: mode choice + worst-case estimate) for the smallest
  possible live test.
- Case limits can be set to explicit values from the re-analysis dialog (raise or lower, never remove); every change,
  including approvals, is recorded in the new `limit_changes` table.
- Migration adds `provider_controls` and `limit_changes` (additive, repeatable).
- `docs/live-coding-result` merged into this branch, so one later merge to `main` carries everything.
- Tests: `tests/test_providers.py` 138 checks (stop/resume, cells, browser columns and buttons);
  new `tests/test_legacy_migration.py` (18 checks) on a database produced by the deployed code `c57214a`
  (`tests/fixtures/legacy_c57214a_marshall.sqlite3`, built by `tools/make_legacy_fixture.py`).

## 2026-10-01 — OpenAI as a second model provider (branch `feature/openai-provider`, NOT merged, NOT deployed)
- New `app/llm/openai_responses.py`: official `openai` SDK (≥3.23), Responses API, Structured Outputs with a strict
  JSON Schema per batch (`app/llm/structured.py`): codebook codes as enums, `-9` only where defined, passage ids limited
  to the batch, every variable required. SDK auto-retry off; only "never sent" errors and plain 429 are retried;
  timeouts/5xx never retried (possibly billed, counted at worst case); bad key, no permission, unknown model and
  exhausted quota are configuration errors (no retry, run stops). Free model-availability check before estimating.
  API key read only from `OPENAI_API_KEY` and redacted from all error text.
- Provider-neutral coding (`app/coding.py`): one shared evidence preparation and identical prompts for every provider;
  one normalizer → the same server validator; results stored per provider/role/run group. Modes: `single` (default,
  unchanged), `anthropic_only`, `openai_only`, `dual_independent`, `anthropic_primary_openai_review`,
  `openai_primary_anthropic_review`. Search is never repeated per provider. Comparison statuses: model agreement,
  value/evidence disagreement, one provider blank, invalid provider output, needs human review, human approved.
- Limits checked on the server before every request: combined case budget, OpenAI case budget, OpenAI attempts and
  total model attempts per case (new append-only `model_calls` ledger counts every request, incl. retries).
  Approval raises each limit to an explicit value.
- Cache key v2 (provider, model, prompt version, codebook version, variables, evidence hash, response schema,
  generation settings, role). Existing Claude cache entries remain reusable read-only. Replies with invalid,
  incomplete, refused, non-JSON or schema-noncompliant content are never cached — **this now also applies to Claude:
  a reply with any invalid item is no longer cached** (D-025).
- Claude: 401/403/404 responses are now configuration errors (run stops at the first one instead of the second).
  Claude's prompt text is byte-identical to before.
- Additive, repeatable DB migration (`app/migrations.py`) with `rollback`/`restore` commands.
- UI: provider status; mode choice with per-provider and combined worst-case cost, spend by provider and attempt counts
  in the re-analysis dialog; side-by-side provider suggestions with their own evidence and "accept this" buttons;
  comparison badges; human-approved value shown separately; OpenAI settings only when its key is configured.
- Export: new `Provider_Suggestions` sheet; extra columns in Results/Evidence/Runs_Usage; `Case_Row` unchanged;
  provider disagreements are never exported as values without a human decision.
- `render.yaml`: `OPENAI_API_KEY` (`sync: false`, no value). `config/pricing.json`: `gpt-6.1-sol` $2 / $10 per 1M
  (cached $0.10; >272K input tokens 2×/1.5×), verified 2026-10-01.
- Tests: new `tests/test_providers.py` (115 checks, real SDK through a mocked transport, browser checks);
  `tests/test_pipeline.py` cache check updated for D-025. No live OpenAI call has been made.

## 2026-10-01 — First complete live coding run (docs only)
- Marshall Fire re-analysis on `c57214a`: 16 calls, 0 failed, 7 reused from cache; output use up to ~960 tokens
  per variable. Case total $1.49 (including ~$0.68 for the earlier partly cut-off run).

## 2026-10-01 — `c57214a` Output limit fix (deployed)
- First partly successful live coding run (Marshall Fire): 7 of 16 batches coded; 9 replies cut off at the old
  output limit (600 + 450 tokens per variable) and discarded.
- Output allowance raised to 1,500 + 1,200 tokens per variable (ceiling 16,000); at most 12 variables per call so
  the ceiling never clips a batch. Pre-run estimate uses the same numbers.
- Run log now shows output tokens used per batch, to calibrate the limit.
- `tests/test_costs.py`: +4 checks (29 total).

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
