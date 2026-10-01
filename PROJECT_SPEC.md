# PROJECT_SPEC.md — functional and research requirements

Authoritative requirements for WFD Coding Assistant. Status tags:

- **TESTED** — implemented and verified (automated test and/or observed in the live deployment; see notes)
- **PARTIAL** — implemented but not fully tested (e.g. only offline, only with fakes, or only one live case)
- **PLANNED** — agreed requirement, not implemented yet
- **UNRESOLVED** — open question or known gap; see `KNOWN_ISSUES.md`

"Offline" tests use local fixtures (a `TEST-FIXTURE` search provider, a local test web server, or a scripted
fake model). They prove the app's rules, not real-world search or coding quality.

Last reviewed: 2026-10-01 (commit `33a0c5e`).

## 1. Purpose and users

A small research team codes U.S. public warning failures (WEA, EAS, sirens, local opt-in systems) into the
WFD workbook. The app does the source discovery and evidence gathering, proposes codebook-valid values with
citations, and leaves every final decision to a human reviewer.

## 2. Inputs

| Requirement | Status |
|---|---|
| User enters incident name, location, approximate date or range; optional aliases, details, known links | TESTED |
| Users do not need to collect or upload sources before starting | TESTED (live: Marshall Fire run) |
| Optional supplements: add URL, upload PDF/HTML/DOCX/TXT, paste text | TESTED (offline) |

## 3. Automatic multi-round source discovery

| Requirement | Status |
|---|---|
| Real search API, separate from the model (Tavily active; Brave/SearXNG adapters exist) | TESTED live for Tavily (13 queries, one case); Brave/SearXNG not tested live |
| Identity check before research; candidate years shown when the same name matches several incidents | PARTIAL (logic tested offline; live run had no ambiguity) |
| 10 initial query templates by source type: AAR, AAR PDF, `.gov`, investigation, original alert, corrections, reforms, hearings, academic, media | TESTED offline; TESTED live (one case) |
| Beyond the first results page (page 2 where the provider supports paging; Tavily has none) | TESTED offline |
| Gap-driven follow-up rounds: weakly supported variables → targeted queries (`gap: <VARIABLE>`) | TESTED offline; did not trigger in the live run (gap check reported no weak variables) — see KNOWN_ISSUES |
| Follow relevant links from relevant pages to official documents/PDFs | TESTED offline |
| Search snippets are discovery leads only, never evidence | TESTED (only fetched full text is indexed) |
| Configurable limits: rounds, queries, sources read, time, cost; stopping is reported as "research incomplete", never as absence of evidence | TESTED |

## 4. Source priority and handling

| Requirement | Status |
|---|---|
| Prioritize AARs → government/official → institutional/academic → credible media → other | PARTIAL: query templates and fetch order prefer AAR/government; classification is URL/title-based heuristic |
| Fetch accessible web pages and PDFs; keep URL, title, publisher, date (if found), retrieval time, content hash | TESTED |
| Keep page numbers for PDFs and paragraph positions for HTML | TESTED |
| OCR scanned PDF pages when Tesseract is available; otherwise report unread pages | PARTIAL (OCR engine present in the image; no truly scanned sample tested) |
| Retrieval failures recorded with a reason; never bypass logins, paywalls or access restrictions | TESTED (live: 27 failures recorded, many HTTP 403) |
| Exact duplicates and syndicated/near-duplicate copies flagged; copies not treated as independent corroboration | TESTED offline; live 1 duplicate found |
| Relevance check against the target incident (name, location, year) | TESTED offline; live 4 sources marked irrelevant |
| Users can exclude a source or change relevance/type; suggestions citing an excluded source are marked stale | TESTED offline |

## 5. Codebook-constrained coding

| Requirement | Status |
|---|---|
| Active codebook = authority for definitions/codes; active workbook = field names and order; no hard-coded field count | TESTED (82 fields from workbook v1.7) |
| Versioned schema; upload new codebook (.docx/.txt) + workbook (.xlsx); editing a rule creates a new version | TESTED offline |
| Rule problems flagged, never guessed (33 flagged for v1.3 + v1.7) | TESTED |
| Fields with no codebook rule kept and marked "rule missing"; no codes suggested for them | TESTED |
| Never invent numeric codes; categorical values must be codebook codes | TESTED (validator rejects) |
| `-9` only where the codebook defines it for that variable | TESTED |
| Unsupported values left blank (status `insufficient_evidence`) or flagged for review | TESTED offline |
| Multi-select: each selected option needs its own evidence | TESTED |
| Free-text fields grounded in cited passages | PARTIAL (prompt rule; quotes validated, prose not) |
| Admin/derived fields generated or calculated with a stated basis, never presented as sourced facts | TESTED offline |
| Model calls send only retrieved evidence passages; source text treated as data, not instructions | PARTIAL (prompt rule; no adversarial test) |
| Live Claude coding completes | TESTED live (Marshall Fire, 2026-10-01: 16 calls, 0 failed) |
| Live suggestions are accurate against hand-coded benchmarks | **UNRESOLVED** — comparison not yet done (TEST_PLAN §4) |

## 6. Evidence traceability

| Requirement | Status |
|---|---|
| Every non-blank suggestion cites passage IDs with verbatim quotes; server checks IDs exist and quotes match | TESTED |
| Evidence shows source, URL, page or paragraph; clicking opens the source at the highlighted passage | TESTED (browser test) |
| Counter-evidence and alternative accounts shown separately | TESTED offline |

## 7. Observed failure vs. uncertain cause

| Requirement | Status |
|---|---|
| Prompt instructs: code documented failures even if cause is uncertain; generic "technical issue" proves no specific cause; competing explanations → `disputed`, keep alternatives | PARTIAL (rule implemented; tested only with a fake model) |
| Causal variables marked `CAUSAL` in the prompt; disputed fields stay blank with alternatives listed | TESTED offline |
| No incident-specific rules (e.g. nothing written for one fire or one article) | TESTED by design review |

## 8. Human review and audit trail

| Requirement | Status |
|---|---|
| Results table beside evidence panel; definition, codes, rationale, support, counter-evidence, unresolved issues | TESTED |
| Accept / Edit (reason required) / Clear (reason required) / Defer / Undo | TESTED |
| Human edits validated against the codebook | TESTED |
| Original model value, reviewed value, reason, reviewer name and time preserved; full history | TESTED |
| Reanalysis never overwrites reviewed values; differences marked (Δ) | TESTED |
| Review filters are review states, not WFD codes | TESTED |

## 9. Export

| Requirement | Status |
|---|---|
| 4-column TSV (Variable, Value, Source, Explanation) | TESTED offline |
| XLSX review workbook: results, case row, evidence, sources, search log, runs/usage, field mapping | TESTED offline |
| Workbook-aligned single case row with original headers in original order, genuine blanks | TESTED offline |
| JSON with full results and evidence relationships | TESTED offline |
| Default = reviewed values only; unreviewed suggestions only on request and clearly labeled | TESTED offline |
| Multi-codes written as text so Excel cannot turn "1, 3" into a date | TESTED offline |
| Original workbook never modified | TESTED |
| Export from the live deployment | PARTIAL (not yet tried live) |

## 10. Persistence

| Requirement | Status |
|---|---|
| Cases, sources, passages, suggestions, reviews, jobs, usage in SQLite on disk (not browser memory) | TESTED |
| Background jobs survive restarts and resume from the last completed stage; completed model calls reused from cache | TESTED offline |
| Data survives Render redeploys (persistent disk at `/var/data`) | TESTED live (Marshall Fire case and its sources were still present after the `de5aece` redeploy) |

## 11. Cost safeguards

| Requirement | Status |
|---|---|
| Per-case dollar budget (default $3) summed across all runs, model + search | TESTED offline |
| Pre-run estimate; precise worst-case estimate before coding; pause when it exceeds the remaining case budget | TESTED offline |
| Approval raises the case budget to an explicit amount (spent + worst case), logged with reviewer name; never removes the cap | TESTED offline |
| Worst-case check before every model call (input +25%, all output tokens) | TESTED offline |
| Retry only requests that surely were not processed (429/529/connection); timeouts and 5xx not retried and counted at worst case | TESTED offline |
| Same 4xx error on two consecutive batches stops the run | TESTED offline |
| Tavily counted at $0.016/request; budget checked before every query | TESTED offline |
| Unknown model price pauses instead of running uncapped | TESTED offline |
| Duplicate submissions for a running case return the same job | TESTED |
| Truncated/invalid model replies never cached | TESTED offline |
| **Per-case caps on number of model attempts and search requests** (project rule) | **UNRESOLVED** — current count caps are per run (`max_queries` 40); model attempts bounded only by batching and the dollar budget |

## 12. Security

| Requirement | Status |
|---|---|
| Secrets only in environment variables; never in code, Git, frontend, logs or exports | TESTED (repository and history scan, 2026-10-01) |
| Login required when reachable from other computers; server refuses public bind without `WFD_PASSWORD` | TESTED |
| Shared team password + reviewer name; signed HttpOnly SameSite cookie, 14-day expiry | TESTED |
| Lockout: 8 failures per address / 15 min; 40 failures site-wide pause sign-in | TESTED offline |
| JSON-only mutating requests (CSRF guard); security headers (CSP, frame denial, nosniff) | TESTED |
| Client address from Cloudflare header (`CF-Connecting-IP`) on Render | PARTIAL (assumption from a third-party report; site-wide limit is the backstop) |
| Per-user accounts and roles | PLANNED (not requested yet; all signed-in users have equal rights) |

## 13. Interface

| Requirement | Status |
|---|---|
| Bilingual (Chinese/English) interface; original English variable names kept | TESTED |
| Pages: research entry, cases, progress, sources, search log, review, export/runs, schema, settings | TESTED |
| Confirmations shown inside the page (browser popups can be blocked) | TESTED offline (fix deployed in `33a0c5e`; not yet confirmed by the user live) |

## 14. Deployment

See `DEPLOY.md` and `ARCHITECTURE.md`. Render web service (Docker, `0.5c-512mb`, Oregon) + 5 GB disk, deployed
from `main` of `hesiyang5-glitch/wfd-research-assistant`. Docker build and health check: TESTED live.
