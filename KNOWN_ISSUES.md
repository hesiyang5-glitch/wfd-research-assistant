# KNOWN_ISSUES.md — open defects, limitations, risks, planned work

Last reviewed: 2026-10-01 (commit `33a0c5e`). Severity: **High** (blocks correct/safe use), **Medium**,
**Low**. Move items to `CHANGELOG.md` when fixed.

## Pending owner decisions

| ID | Issue | Severity |
|---|---|---|
| K-01 | **Auto-deploy conflicts with project rule.** Render deploys every push to `main`; the rule says no automatic deploys without explicit request. Options in DECISIONS D-020 (`autoDeployTrigger: off` vs approval before every push). Until decided, nothing is pushed to `main` without approval. | High (process) |
| K-02 | **Per-case caps on model attempts and search requests missing.** Dollar budget is per case; query count (40) is per run; model attempts bounded only by batching and dollars. Proposal in DECISIONS D-021. | Medium |

## Live verification gaps

| ID | Issue | Severity |
|---|---|---|
| K-03 | **No successful live coding run yet.** First run: all 16 Claude calls rejected (temperature, fixed `de5aece`); Re-analyze then blocked by the owner's browser popup blocking (fixed `33a0c5e`). Needs re-test: hard-refresh, Re-analyze Marshall Fire. | High |
| K-04 | Coding quality vs hand-coded benchmarks unmeasured (TEST_PLAN §4). | High |
| K-05 | Live export, live causal-uncertainty handling, live review/reanalysis not yet exercised. | Medium |
| K-06 | Recorded case spend vs Anthropic Console usage not yet reconciled. | Medium |

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
| K-17 | 512 MB instance: large or scanned PDFs (OCR) may run out of memory. Upgrade path: 2 GB plan. | Medium |
| K-18 | Single worker thread: one job at a time across all cases. | Low |
| K-19 | Shared password; no per-user accounts or roles; any signed-in user can change settings and raise budgets. | Medium |
| K-20 | Lockout relies on `CF-Connecting-IP` behavior reported by a third party, not Render docs; site-wide limit is the backstop and can be used to pause sign-in for everyone (existing sessions unaffected). | Low |
| K-21 | Render billing for failed first deploys and for disks of suspended services is not documented; assume charges while resources exist. | Low |
| K-22 | Anthropic API key in production was created with a 30-day expiry (owner's setting, expires 2026-10-31). Rotate before then (DEPLOY.md, "Rotate keys"). | Medium |
| K-23 | No CI; Docker build verified only by Render deploys. Tests need sample PDFs supplied via `WFD_TEST_PDFS`. | Low |
| K-24 | Tavily cost counted at pay-as-you-go price even within free credits (overstates spend; may trigger budget pauses earlier than necessary). | Low |
| K-25 | Start scripts' first-time `pip install` (local use) never tested end-to-end. | Low |

## Planned improvements (not started)

- Per-case attempt/search caps (K-02) and auto-deploy policy (K-01) once decided.
- Fetch-limit accounting and 403 handling (K-07); stricter gap scoring (K-08).
- Cache-busting for `web/` assets (K-16).
- Benchmark scoring on B1–B3 and a results table in TEST_PLAN.
- Optional: per-user accounts; CI running the offline suites.
