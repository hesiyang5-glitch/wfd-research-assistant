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
| K-26 | OpenAI live use so far (2026-10-02): two single-variable dual runs and one full OpenAI-only run of the Marshall Fire case (16 requests, $0.465), all completed; strict schema accepted live. Not yet verified: per-batch reasoning tokens, whether any batch was cut off, OpenAI dashboard vs app ledger line by line. | Medium |
| K-27 | OpenAI output allowance and reasoning effort are first guesses (D-028). Live data point: full run cost about 1/9 of the worst case, so the 16,000-token reasoning reserve is mostly unused; read `reasoning_tokens` per batch from `model_calls` before lowering it (lowering risks cut-off, paid-but-unusable replies). | Medium |
| K-28 | Worst-case reserves are large: a full OpenAI run is about $2.5 worst case and dual ≈ $3.5, so at the old default $3 budget most OpenAI/dual runs paused for approval first. Default raised to $5 on branch `feature/budget-default-5` (D-034, not merged); a full OpenAI run can still hit the $3 OpenAI sub-budget. Typical actual cost is unmeasured. | Medium |
| K-29 | The reviewer-mode estimate approximates the extra input (primary suggestions) at ~250 tokens per variable. | Low |
| K-30 | Existing cases keep the settings saved when they were created; new limits apply from code defaults (not from edited global defaults) until changed for that case. | Low |
| K-31 | `render.yaml` lists `OPENAI_API_KEY` with `sync: false`; whether Render prompts for it on an existing Blueprint is unverified — add it in the dashboard by hand. | Low |
| K-32 | Resolved 2026-10-01: Render built the image with `openai` 3.23.0 (verified in the Shell after deploying `cd4e6b8`). | — |
| K-33 | Resolved on the branch: `docs/live-coding-result` was merged into `feature/openai-provider` (2026-10-01), so one later merge to `main` carries both. | — |
| K-35 | Providers in one job run one after another (alphabetical by provider; order carries no meaning, D-036), not in parallel. Stop takes effect before the next batch; a request already sent cannot be cancelled (up to the 600 s timeout) and may be billed. | Low |
| K-36 | Existing-data migration is proven on a database produced by the deployed code `c57214a` (synthetic Marshall Fire case), not on a copy of the production database (not accessible from the development environment, and must not be used). Back up before merging. | Medium |
| K-37 | Bulk confirmation (same-run, deployed `66f53f8`; separate-run with warning, D-035, pushed `2fbd11b`): the confirm dialog and the Excel result of a bulk confirmation have **not yet been used live**. Undo is per variable (Reset). | Low |
| K-39 | Mostly explained 2026-10-02: "Pending human review" is shown when one provider found no supported value (e.g. MESSAGE_DISSEMINATION_TIME: Claude -9, OpenAI none), a provider marked the variable disputed/rule unclear, or a check failed (e.g. REMEDIAL_ACTION_COMPLETION_STATUS: both 2 but marked disputed). Exact reason for SYSTEM_LEVEL not read from the tooltip yet. Working as designed. | Low |
| K-34 | D-025 changes Claude behavior: batches whose reply had an invalid item are re-sent (and re-paid) on re-analysis. | Low |
| K-40 | Fixed (D-036, merged to `main` 2026-10-05 as `177a1b8`): cache identity is the model-visible input, not the role; a single-provider result is reused when that provider joins a dual run. Verified offline only. | — |
| K-41 | Claude LESSONS_IDENTIFIED (Marshall Fire) shows "invalid output" (validation failed). Most likely a quote not found verbatim, as earlier with SUMMARY / INCLUSION_CRITERIA_INDICATORS; exact validator message not yet read. OpenAI's suggestion for that field is usable for review. | Low |
| K-42 | Re-analyze can run one variable or all; there is no multi-select. Starting a second variable while one is running does not queue it (duplicate-submission guard returns the running job). Possible feature: "Re-analyze selected" (not started). | Low |
| K-43 | Resolved by the cross-version class (D-036): existing results without recorded versions stay comparable as "cross-version (version not recorded)" and can be bulk-confirmed with the warning and acknowledgement. Re-analysis on unchanged evidence is expected to come from cache at ~$0 — not yet verified on production data. | Low |
| K-44 | The free availability check confirms the key and model but cannot detect an account without credit; that only shows on the first paid request (configuration error, not retried). The Anthropic check (`GET /v1/models/{model}`) has never been called live. | Low |
| K-45 | First-form worst case is very conservative (e.g. dual ≈ $9 against a $5 cap); the run then pauses before coding for an explicit raise. One measured full OpenAI run cost ≈1/9 of its worst case (K-27). | Low |
| K-47 | D-038 (merged 2026-10-06): after deployment, every earlier result (incl. pre-October cached Claude replies) is an earlier analysis version with evidence status "not recorded"; re-analysing for evidence statuses sends new paid requests (no reusable cache). Evidence statuses are the model's judgement — the server checks consistency and citations, not the soundness of an inference. Not yet run against a live model. | Medium |
| K-48 | Pre-existing test hygiene (found 2026-10-06, also on `main`): the browser part of `test_independent_providers` starts a server subprocess (with a fake key and no network guard) that makes the free availability check (`GET /v1/models/...`) toward OpenAI. It was blocked by the sandbox; it is unbilled and the key is fake, but the subprocess should get a guard or a stubbed check. | Low |
| K-52 | Label-only terminology change (merged 2026-10-06): left unchanged on purpose because changing them would alter stored data, prompts or exports — the stored rationale "No language model configured: …" on manual-coding rows, `PROVIDER_LABELS` ("Claude (Anthropic)") in historical cross-model prompts and in the Excel Provider_Suggestions sheet, internal ids/roles (`anthropic`, `openai`, `primary`, `reviewer`) and the legacy mode names (owner decision 2026-10-06: keep internal ids; exports and run logs show readable names since `ui/export-log-labels`; the JSON export and status codes stay raw). "Expected cost" is the low end of the existing estimate (typical output size), explained in a tooltip. | Low |
| K-46 | D-037 (merged 2026-10-06): results stored as `validation_failed` before the fix are not re-validated automatically; their replies were never cached (D-025), so re-analyzing those variables sends new (paid) requests. Whether a passage substantively supports a code is not machine-checked (human review). | Low |

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
| K-16 | Fixed 2026-10-06: interface files are served with `Cache-Control: no-cache, must-revalidate`, so browsers re-check them after a deploy. A browser that still holds a copy from before this fix needs one last hard refresh (Ctrl/Cmd+Shift+R). | — |
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
