# DECISIONS.md — decision log

Dated decisions with rationale. Newest last. Status: **Active**, **Superseded**, or **Pending** (needs the owner's decision).

---

## D-001 · 2026-09-30 · Stack: Python standard library server + SQLite + no-build HTML/JS — Active
**Decision.** Use `http.server.ThreadingHTTPServer`, SQLite (WAL) and a plain JavaScript single-page interface instead of FastAPI/React.
**Why.** The build environment could not install FastAPI or npm packages; this stack installs with one `pip install` and runs on any machine or container. Easy for a non-developer owner to start (`start.command` / `start.bat`).
**Trade-off.** Single process, one worker thread, no ORM; fine for a small team, not for many concurrent users.

## D-002 · 2026-09-30 · Codebook and workbook authority — Active
**Decision.** The active codebook defines variables, definitions, permitted codes and missing-value rules; the active workbook defines field names and order. The field count is never hard-coded. Schemas are versioned; editing a rule creates a new version.
**Why.** Project requirement; the codebook and workbook will change (v1.3 / v1.7 today).
**Consequence.** Problems are flagged (33 for v1.3 + v1.7), never guessed. Fields without a rule are kept and marked "rule missing".

## D-003 · 2026-09-30 · Blank by default; `-9` only where defined — Active
**Decision.** Unsupported values stay blank (`insufficient_evidence`). A special missing value such as `-9` is accepted only if that variable's codebook entry defines it (7 variables in v1.3).
**Why.** The workbook uses `-9` in many fields where the codebook does not define it; copying that habit would invent codes.

## D-004 · 2026-09-30 · Evidence-first coding with server-side validation — Active
**Decision.** The model receives only retrieved passages and the codebook text for each variable. Every non-blank value must cite passage IDs with verbatim quotes; each multi-select option needs its own evidence. The server rejects invalid codes, unknown IDs, non-verbatim quotes and undefined missing values.
**Why.** "Legal value" is not "supported value"; validation must not depend on trusting the model.

## D-005 · 2026-09-30 · Separate observed failure from cause — Active
**Decision.** The prompt requires coding documented failures regardless of cause uncertainty; causal variables are marked `CAUSAL`; competing explanations produce `disputed` with alternatives kept; generic "technical issue" language establishes no specific cause. No incident-specific rules.
**Why.** Core WFD research-method requirement (e.g. a broadcast demonstrably did not air while software vs operator explanations remain disputed).

## D-006 · 2026-09-30 · Human review is the source of truth — Active
**Decision.** Model suggestions and human values are stored separately with full history, reasons and reviewer names. Reanalysis never overwrites reviewed values. Exports default to reviewed values; unreviewed exports are labeled.

## D-007 · 2026-09-30 · Search is a separate, real service; test fixtures are labeled — Active
**Decision.** Search uses a real API (Tavily now; Brave and SearXNG adapters exist). There is no "model memory" fallback. An offline `TEST-FIXTURE` provider exists only for tests and is labeled in the UI, logs and coverage report.

## D-008 · 2026-09-30 · Derived and administrative fields — Active
**Decision.** `VERSION_ENTRY_DATE`, `WFD_ID`, `INCIDENT_DURATION`, source counts/URLs/type summary, `DATA_EXTRACTION_METHOD`, `RECORD_STATUS`, `REVISION_HISTORY` are generated or calculated with a stated basis and never presented as sourced incident facts. Analyst-comment fields are left to humans.

## D-009 · 2026-09-30 · Hosting on Render with a persistent disk — Active
**Decision.** Render Blueprint: one Docker web service plus a 5 GB disk at `/var/data`. The free plan was rejected (sleeps, no disk → data loss).
**Cost.** $7/month (`0.5c-512mb`) + $1.25/month disk, plus usage-based Tavily and Anthropic.

## D-010 · 2026-09-30 · Login model — Active
**Decision.** One shared team password (`WFD_PASSWORD`) plus a reviewer name recorded in history; signed HttpOnly cookie; the server refuses to listen publicly without a password.
**Why.** Small team, minimal setup. **Limitation:** no per-user permissions.

## D-011 · 2026-10-01 · Per-case dollar budget; approval raises to an explicit amount — Active
**Decision.** The budget (default $3) covers model + search spending summed across **all runs of a case**. If a run's worst-case estimate exceeds the remaining budget, the run pauses; approving sets the case budget to spent + worst-case estimate, logged with the reviewer's name. The cap is never removed.
**Why.** Audit found the earlier per-run budget and "approve = unlimited" behavior. Project rule.

## D-012 · 2026-10-01 · Retry policy for paid APIs — Active
**Decision.** Retry only when the request surely was not processed (HTTP 429, 529, connection failures). Read timeouts and 5xx are not retried and are counted against the budget at worst case. Two consecutive identical 4xx errors stop the run.
**Why.** Retrying a request that the provider may already have processed can charge twice.

## D-013 · 2026-10-01 · Tavily counted in the dollar budget — Active
**Decision.** Count each Tavily request at $0.016 (advanced search = 2 credits × $0.008 pay-as-you-go), checked before every query.
**Why.** Search spending was previously not counted. Deliberately conservative: requests within free monthly credits actually cost $0.

## D-014 · 2026-10-01 · Never cache incomplete model replies — Active
**Decision.** Only complete, parseable replies are cached. Replies cut off at the output limit or unreadable replies are reported and re-attempted on the next analysis.

## D-015 · 2026-10-01 · Blueprint uses Tavily only; plan id `0.5c-512mb` — Active
**Decision.** Removed the `BRAVE_API_KEY` prompt from `render.yaml`; renamed plan `starter` → `0.5c-512mb` (same size and price; Render's current id).

## D-016 · 2026-10-01 · Lockout keyed on Cloudflare client address + site-wide limit — Active
**Decision.** Use `CF-Connecting-IP` / `True-Client-IP` (Render sits behind Cloudflare); never trust the first `X-Forwarded-For` entry; add a site-wide limit (40 failures / 15 min) as backstop.
**Caveat.** The header behavior comes from a third-party report, not Render documentation.

## D-017 · 2026-10-01 · No `temperature` parameter for Claude — Active
**Decision.** Do not send `temperature`; `claude-sonnet-5-5` rejects it ("temperature is deprecated for this model"). Found in the first live run (all 16 calls rejected, no charge).

## D-018 · 2026-10-01 · In-page confirmations instead of browser popups — Active
**Decision.** Replace `window.confirm()`/`prompt()` with in-page dialogs and show all errors.
**Why.** The owner's browser blocks popups, which made Re-analyze silently do nothing.

## D-019 · 2026-10-01 · Repository is the project memory — Active
**Decision.** Keep durable project knowledge in `CLAUDE.md`, `PROJECT_SPEC.md`, `ARCHITECTURE.md`, `DECISIONS.md`, `TEST_PLAN.md`, `CHANGELOG.md`, `KNOWN_ISSUES.md`, `DEPLOY.md` so future sessions don't depend on chat history.
**Note.** This documentation was committed to branch `docs/project-memory`, not `main`, because pushing to `main` triggers a production deploy and the owner asked not to deploy in this task.

## D-020 · 2026-10-01 · Keep auto-deploy; approval required before every push to `main` — Active
**Decision (owner chose option 2).** Render keeps auto-deploying every push to `main`. Because a push to `main` is a production deploy, Claude must ask the owner and get explicit approval **before every push or merge to `main`**, stating what will go live and the expected 1–2 minutes of downtime. All other work goes on branches.
**Why.** Keeps deploys simple (no manual Render step) while satisfying the rule "do not deploy unless the user explicitly requests deployment".
**Rejected.** Option 1, turning off auto-deploy (`autoDeployTrigger: off`) and deploying manually from Render.
**Note.** Approval for one push does not carry over to later pushes.

## D-021 · Pending · Per-case caps on model attempts and search requests
**Question.** Project rule asks for server-side per-case limits on model attempts and search requests. Today only the dollar budget is per case; query count (`max_queries` = 40) is per run, and model attempts are bounded by batching and the dollar budget.
**Proposal.** Add `max_model_attempts_per_case` and `max_search_requests_per_case`, counted from the `usage` table across all runs, including retries and possibly-billed failures.
