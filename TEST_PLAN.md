# TEST_PLAN.md — acceptance criteria and tests

Last reviewed: 2026-10-01 (commit `33a0c5e`).

## 1. Automated tests (offline, no paid calls)

All run without internet. Search uses the labeled `TEST-FIXTURE` provider and/or a local test web server;
model behavior uses scripted fakes. They verify the app's rules, **not** live search or real coding quality.
Set `WFD_TEST_PDFS` to a folder containing the Texas-flood source PDFs (claude.ai Project:
`WFD project/sources/20250704-TX01/`) and the Denver alert article.

| Suite | Command | Checks | Last result | Covers |
|---|---|---|---|---|
| Pipeline | `python3 -m tests.test_pipeline` | 44 | 44/44 pass (2026-10-01, `feature/openai-provider`; cache check now expects replies with invalid items NOT to be cached, D-025) | schema vs workbook order/count, rule flags, `-9` rules; research stages with fixture search; PDF page numbers; exact/near duplicates; irrelevant sources; 403 recorded not bypassed; no-model mode invents nothing; validator (invented code, fake quote, unknown ID, per-option evidence, disputes); review preserved across reanalysis; cache reuse; TSV/XLSX/case-row/JSON exports; restart recovery |
| Cost safety | `python3 -m tests.test_costs` | 32 | 32/32 pass (2026-10-02, `feature/budget-default-5`) | default case budget $5, OpenAI sub-budget $3; output allowance ≥1,200 tokens/variable, ≤12 variables per call, under the 16,000 ceiling, no variable dropped; retry only 429/529/connection; timeouts/5xx not retried and counted; no `temperature` sent; truncated replies not cached; complete replies cached; worst-case pre-check; repeated 4xx stops run; budget per case across runs; approval sets explicit amount and is logged; unknown price pauses; Tavily $0.016 counted and capped |
| OpenAI provider, modes, limits | `python3 -m tests.test_providers` | 138 | 138/138 pass (2026-10-01, `feature/openai-provider`) | real `openai` SDK (3.23.0) through a mocked HTTP transport: strict schema (codebook enums, `-9` only where defined, passage ids per batch, all fields required), success parsing, invalid JSON / schema / refusal / invalid code / incomplete (`max_output_tokens`) not cached, timeout and 5xx not retried and counted at worst case, 429 and connect retries counted, quota/unknown model/bad key = configuration error, OpenAI budget, combined budget (Claude + OpenAI + search), OpenAI and total attempt caps across runs, explicit approval, cache-key isolation and invalidation (model, codebook, evidence, schema, effort, variables, role), legacy Claude cache reuse, Anthropic-only / OpenAI-only / manual fallbacks, one search for dual runs, identical independent prompts, reviewer labelling, comparison statuses, export blocking disagreements, human values never overwritten, migration repeatable + rollback/restore, no keys in API/DB/logs/exports/server output, browser: provider status, mode list with/without key, dual cost display, side-by-side suggestions |
| Bulk agreement confirmation | `python3 -m tests.test_bulk_agreement` | 64 | 64/64 pass (2026-10-02, `feature/separate-run-agreement`; separate-run eligibility, core checks, warnings, method, audit, export, browser unticked default) | eligibility (exact, multi-select order, dates, numbers, listed open-list option; disagreement; both blank; not run; failed; stopped; invalid code; invalid citation; free text; counter-evidence; stale; evidence difference; review mode; separate runs; deferred; existing Human final), read-only dialog data, explicit confirmation required, unchecking, write-time re-check, audit row fields, history method, export (Results origin, Case_Row, Bulk_Confirmations, Provider_Suggestions), re-analysis never overwrites, manual correction, Reset undo; browser button/dialog/uncheck/confirm |
| Existing-data migration | `python3 -m tests.test_legacy_migration` | 18 | 18/18 pass (2026-10-01, `feature/openai-provider`) | copy of a database produced by the deployed code `c57214a` (Claude-coded synthetic Marshall Fire case + human edit): every existing row unchanged; Claude values in the Claude column, OpenAI "Not run"; human edit stays Human final; spend/attempts carried over; export uses the human value; browser row check |
| Login & security | `python3 -m tests.test_auth` | 24 | 24/24 pass (2026-10-01, `feature/openai-provider`) | refuses public bind without password; health check; headers; API/export blocked when logged out; wrong password slowed; name required; HttpOnly SameSite cookie; JSON-only mutations; reviewer name in history and sources; tampered session rejected; per-address lockout; faked `X-Forwarded-For` doesn't bypass; site-wide pause; signed-in users unaffected; browser login flow |
| Resilience (D-033) | `python3 -m tests.test_resilience` | 31 | 31/31 pass (2026-10-02, `fix/health-under-load`) | native thread pools = 1 (and overrides); evidence index built once, reused by estimates, rebuilt on added/excluded/restored source, one build for concurrent callers, per case; `sending` ledger row before the request, updated (not duplicated) after success/failure; restart pauses running job (not re-queued), cancels a cancelling job, counts in-flight request at worst case once, keeps attempt count, Resume re-queues; worker thread niced; health check < 2 s while 3 estimates run with the server pinned to one core (approximation: Render's 0.5-CPU quota cannot be reproduced locally) |
| Equal providers + first-form choice (D-036) | `python3 -m tests.test_independent_providers` | 68 | 68/68 pass (2026-10-05, `fix/labels-and-browser-cache`; E19 asserts the cross-version class; services list and no-cache header checks added) | P1–P20 (Claude only / OpenAI only / dual from the first form; one search; separate results; unavailable providers with plain reasons; rejected key blocks before search; estimate per mode, search once, combined = search + selected; hard-budget minimum; mode persists across refresh and restart; pause after research at $0 model cost; stop/fail of one provider leaves the other; other cases and Human final unchanged; shared definitions) and E1–E21 (shared snapshot and analysis version; identical prompts; no hierarchy; neutral combined view; Claude-only and OpenAI-only results reused in dual; cache hits keep provenance; cached = $0 estimate; evidence/codebook/prompt/model/cross-model changes miss; role label never changes the key; legacy rows unchanged by migration; version-matched comparison; cross-model excluded); browser: no hierarchy wording (EN/ZH), estimates change, keyboard, disabled reasons, confirmation dialog, cancel creates nothing, 390 px without horizontal scroll; network guard: no non-local connection |
| Matched vs cross-version (D-035 retained, D-036) | `python3 -m tests.test_cross_version` | 27 | 27/27 pass (2026-10-05, `feature/independent-providers`) | 1 matched classification (separate runs, identical versions); 2–3 cross-version agreement/disagreement; 4 comparable side by side; 5 eligible; 6 refused without acknowledgement, exact warning text; 7 acknowledgement and full audit recorded; 8 version-difference panel accurate (dimensions, versions, added source and passages); 9 disagreement not attributed to the provider alone; 10–11 cache stricter than comparison, no wrong cache hit on new evidence; 12 history and Human final unchanged; 13 invalid/insufficient ineligible; 14 cross-model excluded; R1 codebook difference not bulk-confirmable; export label; browser: unticked default, warning appears on tick, Confirm disabled until acknowledged, acknowledgement recorded, version panel; 15 network guard |
| Missing values (D-039) | `python3 -m tests.test_missingness` | 58 | 58/58 pass (2026-10-06, `audit/missingness`) | exactly 7 variables define `-9`; `-9` accepted (with evidence, warning) only there, rejected for every other model-coded variable and type (numeric, date, text, open list, single/multi-select) with reason `missing_code_not_defined`; `-9.0` = `-9`; no mixing; placeholders blank; real negative coordinates kept; codebook `-9` wording in prompt; workbook `-9`/placeholders flagged, allowed values unchanged, notes not sent to model; consistency flags (UNCERTAINTY_TYPE, LAT/LONG→GEOCODE 0, reversed dates, duration formula, researcher `-9` kept but flagged) on human-final values only; INCIDENT_DURATION blank for missing/reversed dates, 3 for the codebook example; export column; audit table complete, consistent with schema, committed CSV fresh, every PI id documented; network guard |
| Evidence status (D-038) | `python3 -m tests.test_evidence_status` | 59 | 59/59 pass (2026-10-06, `feature/evidence-status`) | all five statuses for Claude-style JSON and OpenAI structured replies; INFERRED kept as candidate, never exported unreviewed or bulk-confirmed; AMBIGUOUS best candidate + validated alternatives; INSUFFICIENT never forces a value; CONFLICTING cause keeps competing passages while the supported failure phenomenon is kept; validation failures (fabricated quote, invalid code, unknown status) separate from evidence status; missing status = not recorded, not cached; schema v2; agreement never upgrades; human final unchanged; legacy rows "not recorded" and not rewritten; migration repeatable/non-destructive; export columns; UI labels; network guard |
| Multi-select validation (D-037) | `python3 -m tests.test_multiselect_validation` | 24 | 24/24 pass (2026-10-06, `fix/multiselect-validation`) | benchmark shape (per-option evidence, no top-level; JSON-list value) valid; supported + fake-quote / invalid-code / unsupplied-id / not-supporting selections → partially valid with supported codes kept and reasons recorded; only invalid codes → invalid; malformed structures → malformed_output, never insufficient; single-select rules unchanged; Claude JSON and OpenAI structured paths through the pipeline; partial replies not cached, never bulk-eligible, never exported unreviewed, own cell state; Human final unchanged; network guard |
| Browser flow | `python3 -m tests.test_ui_flow` | flow | PASS (2026-10-01, `feature/openai-provider`) | home form → research (fixture) → sources (irrelevant flagged) → review edit → citation opens highlighted passage → XLSX export contains reviewed value; no JS errors |

Development note: PyPI was unreachable from the build environment, so `openai` 3.23.0, `httpx` 0.28.1 and `httpcore`
were loaded from their GitHub sources via `PYTHONPATH` for these runs (not committed).

Not automated: Docker image build, Render deployment, live Tavily/Anthropic/OpenAI calls, OCR on a scanned PDF,
neural embeddings, start scripts' first-time `pip install`. There is no CI yet.

## 2. Acceptance criteria (per requirement)

A change is acceptable only if the relevant criteria still hold:

1. **Codebook values** — every non-blank categorical value is a code from the active codebook entry; `-9` only where defined; single-select holds one code.
2. **Evidence alignment** — every non-blank suggestion cites existing passage IDs with verbatim quotes; each multi-select option has its own evidence.
3. **Unsupported fields** — no evidence → blank (`insufficient_evidence`) or a review flag; never a default code.
4. **Uncertainty** — competing causal explanations → `disputed`, value blank or limited to what is established, alternatives listed; a documented failure is still coded.
5. **Traceability** — evidence shows source, URL, page/paragraph; the citation opens the passage.
6. **Excel export** — case row headers identical to the workbook header row, same order, genuine blanks; multi-codes as text; default export = reviewed values only.
7. **Persistence** — data and reviewed values survive restart and redeploy; interrupted jobs resume.
8. **Cost enforcement** — no case exceeds its explicit budget; approvals raise to explicit amounts; possibly-billed failures counted; no automatic retry of possibly-billed calls; incomplete replies never cached.
9. **Security** — no secrets in repository/frontend/logs/exports; login required on public deployments.

## 3. Manual live checks (production, small paid usage)

Run after each deploy that changes research or coding behavior. Set "Cost cap per case" to $1–2.

| # | Check | Expected | Status (2026-10-01) |
|---|---|---|---|
| L1 | Sign in at `https://wfd-coding-assistant.onrender.com` | login page, then app | PASS |
| L2 | Settings page | `TAVILY_API_KEY` and `ANTHROPIC_API_KEY` = yes; search `tavily`; model `anthropic: claude-sonnet-5-5`; OCR available | PASS (owner) |
| L3 | Start research on benchmark B1 | search log provider `tavily`; templates cover AAR/.gov/corrections/reforms | PASS (13 queries) |
| L4 | Sources | AAR found; failures listed with reasons; irrelevant sources flagged | PASS (S1 = Boulder County operational AAR PDF; 27 failures, many 403) |
| L5 | Coding completes | coding line shows N calls, 0 failed | **PASS** (2026-10-01, `c57214a`): 16 calls, 0 failed; 7 batches reused from cache at no charge; case spend $1.49 / $3 |
| L6 | Review: 5 variables with values | citations open and support the code | pending |
| L7 | Causal variable with conflicting accounts | `disputed`, alternatives shown | pending |
| L8 | Edit a value, re-analyze | edit preserved; Δ where suggestion changed | pending |
| L9 | Export XLSX / case row | headers match workbook; unreviewed cells blank | pending |
| L10 | Case spend vs Anthropic Console usage | app's recorded cost ≥ actual | pending |
| L11 | Data after redeploy | case still present | PASS (after `de5aece`) |

### First-stage production verification of `cd4e6b8` (2026-10-01, owner, read-only, $0)

| Check | Result |
|---|---|
| Backup before merge | `/var/data/backup-before-openai-20261001.sqlite3`, integrity ok |
| Build and site | PASS — new interface live; `openai` package 3.23.0 installed in the image |
| Migration | PASS — `2026-10-01-openai-provider` applied; integrity ok |
| Existing data unchanged | PASS — cases 1, sources 60, passages 820, suggestions 246, reviews 0, usage 38 (= backup); model_calls 0 |
| Claude results in Claude column; OpenAI "Not run"; seven columns | PASS (screenshot) |
| Human final | PASS — none existed, none created |
| OpenAI not configured | PASS — Settings "not configured"; Re-analyze offers only Default / Claude only; `OPENAI_API_KEY set: False` |
| Excel export | PASS — 9 sheets incl. Provider_Suggestions; Case_Row 82 columns identical to `WFD_Cases`; blank (no reviews); usage $1.49 = recorded spend; no secrets |
| Legacy cache reuse | PASS — Re-analyze estimate "16 calls (0 new), max additional cost $0.000" |
| "Invalid output" on SUMMARY / INCLUSION_CRITERIA_INDICATORS | explained — earlier Claude run; quotes not verbatim in S1-P54/S1-P56 (validator), not caused by the update |
| Stop/Resume buttons; a Claude call on the new version | not yet observed (appear on the next run; needs approval) |

### Incident-fix checks (branch `fix/health-under-load`, after owner approval to merge; $0)

| # | Check | Expected | Status |
|---|---|---|---|
| R1 | Render Shell read-only diagnostics (DEPLOY.md, "Slow or restarting service") on the **current** deployment | shows host CPU count, CPU quota, throttling counters, BLAS thread counts — confirms or rejects the root cause | DONE 2026-10-02 (owner): 32 host CPUs, quota 0.5 CPU, thread pools 32/32/32, 1682 throttled periods — root cause confirmed |
| R2 | Same diagnostics after deploying the fix | BLAS/OpenMP thread counts = 1 | PASS 2026-10-02 (owner, instance stfgb, `f664344` live 10:50 am): `OMP_NUM_THREADS=1`, openmp 1, openblas 1, openblas 1 |
| R3 | Cost estimate in Re-analyze dialog (no model call) while watching Render Events | no failed health checks | PASS 2026-10-02 (owner screenshots): estimate dialog worked; Events after the `f664344` and `7194f1a` deploys showed only "Deploy live", no "Instance failed" |
| R4 | Next paid re-analysis (separate approval) | no health-check failures; if a restart happens anyway, job shows "Interrupted… paused", not restarted | PARTIAL 2026-10-02: single-variable dual run and full OpenAI-only run both completed; the owner did not send Render Events for the run period, so "no Instance failed" is unconfirmed |

### OpenAI live checks (after merge + deploy approval; small paid usage, OpenAI case budget $1–3)

| # | Check | Expected | Status |
|---|---|---|---|
| O1 | Settings with `OPENAI_API_KEY` set | "OpenAI — configured · gpt-6.1-sol"; no key value visible anywhere | PASS (2026-10-01, owner screenshots: dual modes offered in Re-analyze; no key shown) |
| O2 | Re-analyze B1 with "OpenAI only" on 1–3 variables | free model check passes; schema accepted (no HTTP 400); calls complete | PASS 2026-10-02 (single-variable dual runs SYSTEM_LEVEL and REDUNDANCY_AND_CHANNEL_BEHAVIOR completed; REDUNDANCY: Claude 1, OpenAI 1 = hand-coded benchmark; that run cost $0.04 total vs $0.231 worst case) |
| O3 | Run log / Runs_Usage | input, output, **reasoning** tokens and request id per batch; cost at $2/$10 | pending (per-batch token counts not yet read from `model_calls` or the export) |
| O4 | Full OpenAI re-analysis of B1 | 0 cut off (`max_output_tokens`); note max reasoning tokens to tune D-028 | PARTIAL 2026-10-02 (`2fbd11b` not yet live; ran on `58d8fdc`): OpenAI-only, 16 requests, OpenAI attempts 2→18 (no retries), actual cost **$0.465** vs worst case $4.01 (≈1/9); case budget raised by owner approval to $5.56 (OpenAI $4.03); case spend after: $2.01 (Claude $1.32, OpenAI $0.484, search $0.208). Not yet checked: cut-off count and max reasoning tokens per batch |
| O5 | Dual independent on B1 | one search (none on re-analysis); both providers stored; disagreements in "disputed" | PARTIAL (2026-10-01, `66f53f8`): single-variable dual re-analysis of SYSTEM_LEVEL completed; Claude and OpenAI results both shown (owner screenshot); app-recorded cost about $0.02. During it the service failed health checks and restarted (K-38). Not yet checked: per-batch tokens/request ids in `model_calls` (owner Shell query not run), why the row shows "Pending human review", full-case dual run |
| O6 | Accept a specific provider's value; re-analyze | human value kept; "accepted from" recorded | pending |
| O7 | Recorded OpenAI spend vs OpenAI usage dashboard | app ≥ actual | PARTIAL — owner saw about $0.01 on the OpenAI dashboard and about $1.29 total on the Anthropic console (2026-10-01); not yet compared line by line with the app's ledger |
| O8 | Wrong `OPENAI_MODEL` | job pauses with "not available to this API project"; no paid call | pending |
| O9 | Stop OpenAI during a dual run, then Resume OpenAI | Claude unaffected; only stopped OpenAI variables re-coded; spend matches calls actually sent | pending |

## 4. Benchmark cases

Human-coded rows in `reference/MASTER_WFD_Pilot_Workbook_v1.7.xlsx` (50 coded rows). These are the team's
codes, **not ground truth**; some hand codes conflict with the codebook (see KNOWN_ISSUES), so disagreements
need human judgment, not automatic scoring.

| ID | Incident | Inputs to use | Selected hand-coded values (v1.7) |
|---|---|---|---|
| B1 `20211230-CO01` | Marshall Fire | `Marshall Fire` · `Boulder County, Colorado` · `December 30, 2021` | FAILURE_TYPE 6 · FAILURE_SUBTYPE C1 · SYSTEM_INVOLVED WEA; LOCAL · SYSTEM_LEVEL 3 · SUCCESS_NONUSE_PARTIALUSE 1 · REDUNDANCY 1 · platform Everbridge · DELIVERY_COVERAGE 19 · ALERTING_AUTHORITY_TYPE 3 |
| B2 `20180113-HI01` | Hawaii false missile alert | `Hawaii false ballistic missile alert` · `Hawaii` · `January 13, 2018` | FAILURE_TYPE 2 · SUBTYPE O2 · SYSTEM_INVOLVED WEA; EAS · SYSTEM_LEVEL 2 · SUCCESS_NONUSE_PARTIALUSE 3 · platform AlertSense · ALERT_CORRECTION_OR_UPDATE 2 |
| B3 `20181108-CA01` | Camp Fire | `Camp Fire` · `Butte County, California` · `November 8, 2018` | FAILURE_TYPE 6 · SUBTYPE G2 · SYSTEM_INVOLVED WEA; LOCAL; SIREN · SYSTEM_LEVEL 3 · SUCCESS_NONUSE_PARTIALUSE 2 · platform CodeRED · DELIVERY_COVERAGE 13.5 |
| B4 (offline corpus) | 2025 Texas Hill Country flood | 10 project PDFs + 1 unrelated Denver article | used by automated tests (not coded in v1.7) |

Suggested scoring per benchmark: for each variable with a hand code, record agree / disagree / app blank /
app disputed, and whether the app's citation supports its value. Track over time in this file.

## 5. Updating this plan

Update when acceptance criteria change, when a suite's check count changes, or after each live check round.
