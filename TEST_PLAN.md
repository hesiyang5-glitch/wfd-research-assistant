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
| Cost safety | `python3 -m tests.test_costs` | 29 | 29/29 pass (2026-10-01, `feature/openai-provider`) | output allowance ≥1,200 tokens/variable, ≤12 variables per call, under the 16,000 ceiling, no variable dropped; retry only 429/529/connection; timeouts/5xx not retried and counted; no `temperature` sent; truncated replies not cached; complete replies cached; worst-case pre-check; repeated 4xx stops run; budget per case across runs; approval sets explicit amount and is logged; unknown price pauses; Tavily $0.016 counted and capped |
| OpenAI provider, modes, limits | `python3 -m tests.test_providers` | 115 | 115/115 pass (2026-10-01, `feature/openai-provider`) | real `openai` SDK (3.23.0) through a mocked HTTP transport: strict schema (codebook enums, `-9` only where defined, passage ids per batch, all fields required), success parsing, invalid JSON / schema / refusal / invalid code / incomplete (`max_output_tokens`) not cached, timeout and 5xx not retried and counted at worst case, 429 and connect retries counted, quota/unknown model/bad key = configuration error, OpenAI budget, combined budget (Claude + OpenAI + search), OpenAI and total attempt caps across runs, explicit approval, cache-key isolation and invalidation (model, codebook, evidence, schema, effort, variables, role), legacy Claude cache reuse, Anthropic-only / OpenAI-only / manual fallbacks, one search for dual runs, identical independent prompts, reviewer labelling, comparison statuses, export blocking disagreements, human values never overwritten, migration repeatable + rollback/restore, no keys in API/DB/logs/exports/server output, browser: provider status, mode list with/without key, dual cost display, side-by-side suggestions |
| Login & security | `python3 -m tests.test_auth` | 24 | 24/24 pass (2026-10-01, `feature/openai-provider`) | refuses public bind without password; health check; headers; API/export blocked when logged out; wrong password slowed; name required; HttpOnly SameSite cookie; JSON-only mutations; reviewer name in history and sources; tampered session rejected; per-address lockout; faked `X-Forwarded-For` doesn't bypass; site-wide pause; signed-in users unaffected; browser login flow |
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
| L5 | Coding completes | coding line shows N calls, 0 failed | **PARTIAL**: in-page dialog works live; 16 calls, 9 cut off at the output limit (`e02de43`). Fix on `fix/output-limit`; re-test pending |
| L6 | Review: 5 variables with values | citations open and support the code | pending |
| L7 | Causal variable with conflicting accounts | `disputed`, alternatives shown | pending |
| L8 | Edit a value, re-analyze | edit preserved; Δ where suggestion changed | pending |
| L9 | Export XLSX / case row | headers match workbook; unreviewed cells blank | pending |
| L10 | Case spend vs Anthropic Console usage | app's recorded cost ≥ actual | pending |
| L11 | Data after redeploy | case still present | PASS (after `de5aece`) |

### OpenAI live checks (after merge + deploy approval; small paid usage, OpenAI case budget $1–3)

| # | Check | Expected | Status |
|---|---|---|---|
| O1 | Settings with `OPENAI_API_KEY` set | "OpenAI — configured · gpt-6.1-sol"; no key value visible anywhere | pending |
| O2 | Re-analyze B1 with "OpenAI only" on 1–3 variables | free model check passes; schema accepted (no HTTP 400); calls complete | pending |
| O3 | Run log / Runs_Usage | input, output, **reasoning** tokens and request id per batch; cost at $2/$10 | pending |
| O4 | Full OpenAI re-analysis of B1 | 0 cut off (`max_output_tokens`); note max reasoning tokens to tune D-028 | pending |
| O5 | Dual independent on B1 | one search (none on re-analysis); both providers stored; disagreements in "disputed" | pending |
| O6 | Accept a specific provider's value; re-analyze | human value kept; "accepted from" recorded | pending |
| O7 | Recorded OpenAI spend vs OpenAI usage dashboard | app ≥ actual | pending |
| O8 | Wrong `OPENAI_MODEL` | job pauses with "not available to this API project"; no paid call | pending |

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
