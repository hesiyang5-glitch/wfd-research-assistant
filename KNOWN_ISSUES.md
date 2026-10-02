# KNOWN_ISSUES.md — open defects, limitations, risks, planned work

Last reviewed: 2026-10-01 (commit `33a0c5e`). Severity: **High** (blocks correct/safe use), **Medium**,
**Low**. Move items to `CHANGELOG.md` when fixed.

## Pending owner decisions

| ID | Issue | Severity |
|---|---|---|
| K-02 | **Per-case cap on search requests missing.** Model-attempt caps per case are implemented on `feature/openai-provider` (D-027, not deployed); search query count (40) is still per run. | Medium |

## Live verification gaps

| ID | Issue | Severity |
|---|---|---|
| K-03 | **Output headroom is modest.** Live re-analysis (2026-10-01, `c57214a`) coded all 16 batches, 0 failed. Heaviest batch used 4,811 of 7,500 output tokens for 5 variables (~960/variable vs 1,200 allowed). Watch the logged token counts; raise `OUT_TOKENS_PER_VAR` if a cut-off recurs. | Low |
| K-04 | Coding quality vs hand-coded benchmarks unmeasured (TEST_PLAN §4). | High |
| K-05 | Live export, live causal-uncertainty handling, live review/reanalysis not yet exercised. | Medium |
| K-06 | Recorded case spend vs Anthropic Console usage not yet reconciled. | Medium |

## OpenAI provider (merged and deployed 2026-10-01: `cd4e6b8`, then `66f53f8`)

| ID | Issue | Severity |
|---|---|---|
| K-26 | **Only one live OpenAI call scenario so far** (2026-10-01: single-variable dual re-analysis of SYSTEM_LEVEL, completed). Still unverified at full scale: that the owner's API project can use `gpt-6.1-sol`; that OpenAI accepts the generated strict schema (enums, `$defs`, sanitized keys) for every batch; real reasoning-token use vs the 16,000 reserve; real cost; refusal/incomplete shapes from the live API. Offline tests use the official SDK (3.23.0 from GitHub source) with a mocked transport. | High |
| K-27 | OpenAI output allowance and reasoning effort are first guesses (D-028); tune from the logged `reasoning_tokens` per batch. | Medium |
| K-28 | Worst-case reserves are large: a full OpenAI run is about $2.5 worst case and dual ≈ $3.5, so at the old default $3 budget most OpenAI/dual runs paused for approval first. Default raised to $5 on branch `feature/budget-default-5` (D-034, not merged); a full OpenAI run can still hit the $3 OpenAI sub-budget. Typical actual cost is unmeasured. | Medium |
| K-29 | The reviewer-mode estimate approximates the extra input (primary suggestions) at ~250 tokens per variable. | Low |
| K-30 | Existing cases keep the settings saved when they were created; new limits apply from code defaults (not from edited global defaults) until changed for that case. | Low |
| K-31 | `render.yaml` lists `OPENAI_API_KEY` with `sync: false`; whether Render prompts for it on an existing Blueprint is unverified — add it in the dashboard by hand. | Low |
| K-32 | Resolved 2026-10-01: Render built the image with `openai` 3.23.0 (verified in the Shell after deploying `cd4e6b8`). | — |
| K-33 | Resolved on the branch: `docs/live-coding-result` was merged into `feature/openai-provider` (2026-10-01), so one later merge to `main` carries both. | — |
| K-35 | Providers in one job run one after another (Claude first in dual mode), not in parallel. Stop takes effect before the next batch; a request already sent cannot be cancelled (up to the 600 s timeout) and may be billed. | Low |
| K-36 | Existing-data migration is proven on a database produced by the deployed code `c57214a` (synthetic Marshall Fire case), not on a copy of the production database (not accessible from the development environment, and must not be used). Back up before merging. | Medium |
| K-37 | Bulk confirmation (deployed in `66f53f8`; the confirm dialog has not yet been used live). Same-run agreement needs a dual-independent run made after this change; separate-run agreement (D-035, branch `feature/separate-run-agreement`, not deployed) is offered unticked with a warning. No batch-undo button: undo is per variable (Reset). | Low |
| K-39 | SYSTEM_LEVEL row after the live dual test shows "Pending human review"; reason not yet explained (likely disagreement or validation flag — unconfirmed). | Low |
| K-34 | D-025 changes Claude behavior: batches whose reply had an invalid item are re-sent (and re-paid) on re-analysis. | Low |

## Research quality

| ID | Issue | Severity |
|---|---|---|
| K-07 | **Many official sites return HTTP 403** to the app's fetcher (NOAA, colorado.gov, AMS journals, ULI in the Marshall Fire run: 27 of 60 attempts failed). Likely bot/User-Agent filtering. Failed attempts also consume the 60-fetch limit. Options: count only successful fetches against the limit, separate failure cap, manual upload workflow; any User-Agent change needs an owner decision (must not bypass access controls). | High |
| K-08 | **Gap check may be too lenient.** With 790 passages it reported no weak variables, so no follow-up search ran. The keyword-based strength score likely overrates large corpora. | Medium |
| K-09 | Source type is a URL/title heuristic; uploads without a URL get `unknown`. Primary/secondary counts depend on it. | Medium |
| K-10 | Identity disambiguation is simple (year clustering of result titles). Same-name incidents in the same year/place are not separated. | Medium |
| K-11 | Semantic retrieval uses LSA (not neural embeddings) unless `EMBEDDING_MODEL` is configured. | Low |
| K-12 | Token counts are estimated (≈3.6 characters/token); estimates can differ from billed tokens. Worst-case factor +25% on input mitigates. | Low |
| K-13 | Free-text fields: quotes are validated, the model's prose is not. | Medium |
| K-14 | Prompt-injection resistance (source text treated as data) is a prompt rule only; no adversarial test. | Medium |
| K-15 | `WFD_ID` sequence uses IDs in the active workbook, not the master database. | Low |

## Codebook / workbook issues (need PI decisions; app flags them, never guesses)

33 flagged on the Schema page. Highlights:
- `FAILURE_TYPE` "single-select, though multiple secondary codes may be noted" vs workbook entries like `2, 5`.
- `ALERTING_AUTHORITY_TYPE` says both single-select and multiple values permitted.
- `MESSAGE_RECEPTION_DOCUMENTATION` codes start at 2; 13 workbook rows use `1`.
- `DELIVERY_COVERAGE`: percentage bands vs "add the specific number".
- `-9` defined for 7 variables but used in many others in the workbook.
- Excel auto-converted multi-codes into dates (e.g. `2026-01-03` for "1, 3").
- Workbook column 77 has a blank header; column 76 header has extra text (`Albert | Elise`); `LAT/LONG` vs codebook `LATITUDE / LONGITUDE`.
- Some hand codes appear inconsistent with the codebook (e.g. B2 Hawaii `ALERTING_AUTHORITY_TYPE` 1 = federal for a state agency). Benchmarks therefore need human judgment.
- The bundled default schema comes from a plain-text excerpt of the codebook's variable section; parsing the original `.docx` gave identical results in a local test.

## Platform, deployment and security

| ID | Issue | Severity |
|---|---|---|
| K-16 | Static files are served without cache headers; after a deploy, browsers may keep old JavaScript until a hard refresh (Ctrl/Cmd+Shift+R). | Medium |
| K-17 | 512 MB / 0.5 CPU instance: large or scanned PDFs (OCR) may run out of memory; heavy work shares the half CPU with the web server (see K-38). Measured locally: peak ~210 MB for an 825-passage case. Upgrade path: larger plan or separate worker (paid; owner approval). | Medium |
| K-18 | Single worker thread: one job at a time across all cases. | Low |
| K-19 | Shared password; no per-user accounts or roles; any signed-in user can change settings and raise budgets. | Medium |
| K-20 | Lockout relies on `CF-Connecting-IP` behavior reported by a third party, not Render docs; site-wide limit is the backstop and can be used to pause sign-in for everyone (existing sessions unaffected). | Low |
| K-21 | Render billing for failed first deploys and for disks of suspended services is not documented; assume charges while resources exist. | Low |
| K-22 | Anthropic API key in production was created with a 30-day expiry (owner's setting, expires 2026-10-31). Rotate before then (DEPLOY.md, "Rotate keys"). | Medium |
| K-23 | No CI; Docker build verified only by Render deploys. Tests need sample PDFs supplied via `WFD_TEST_PDFS`. | Low |
| K-24 | Tavily cost counted at pay-as-you-go price even within free credits (overstates spend; may trigger budget pauses earlier than necessary). | Low |
| K-25 | Start scripts' first-time `pip install` (local use) never tested end-to-end. | Low |
| K-38 | Incident 2026-10-01 ~11:45 pm: health checks timed out during a single-variable dual re-analysis; Render restarted the service (502) and the old code auto-restarted the job; the job later finished; no unrecorded spend found. Fix (D-033) deployed 2026-10-02 (`f664344`); thread pools verified at 1 on Render. Still to watch: no "Instance failed" during the next real (paid) re-analysis. Root cause **confirmed on Render 2026-10-02** (read-only Shell on instance k8gv2, running `66f53f8`): host has 32 CPUs, quota `50000 100000` (0.5 CPU), OpenMP 32 threads and two OpenBLAS pools with 32 threads each; `nr_throttled` 1682 of 25689 periods. Render events: "Instance failed" 11:43, 11:46, 11:47 pm. Event reason (11:46:56 pm): "HTTP health check failed (timed out after 5 seconds) while running your code" — not out of memory. Memory peak not checked. Local test pins the server to one core; the real CPU quota cannot be reproduced locally. | High |

## Planned improvements (not started)

- Per-case search-request cap (K-02).
- Fetch-limit accounting and 403 handling (K-07); stricter gap scoring (K-08).
- Cache-busting for `web/` assets (K-16).
- Benchmark scoring on B1–B3 and a results table in TEST_PLAN.
- Optional: per-user accounts; CI running the offline suites.
