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

## D-021 · Partly decided (2026-10-01, see D-027) · Per-case caps on model attempts and search requests
**Question.** Project rule asks for server-side per-case limits on model attempts and search requests. Today only the dollar budget is per case; query count (`max_queries` = 40) is per run, and model attempts are bounded by batching and the dollar budget.
**Proposal.** Add `max_model_attempts_per_case` and `max_search_requests_per_case`, counted from the `usage` table across all runs, including retries and possibly-billed failures.

## D-022 · 2026-10-01 · Larger output allowance per variable — Active (deployed `c57214a`)
**Decision.** Output allowance per call = 1,500 + 1,200 tokens per variable (ceiling 16,000), at most 12 variables per call.
**Why.** At 600 + 450 per variable, 9 of 16 live batches were cut off. A cut-off reply is billed in full and thrown away, while a generous limit costs nothing extra on a complete reply (only tokens produced are billed); it only raises the worst-case reserve checked against the case budget.
**Not chosen.** Shortening the required evidence (fewer quotes, no counter-evidence) — that would weaken traceability and conflicting-evidence handling.

## D-023 · 2026-10-01 · OpenAI as a second provider via the official SDK and Responses API — Active (branch, not deployed)
**Decision.** Add OpenAI through the official `openai` Python SDK (≥3.23) and the Responses API with Structured Outputs
(strict JSON Schema). Model from `OPENAI_MODEL` (default `gpt-6.1-sol`, confirmed in OpenAI's model docs 2026-10-01;
whether the owner's API project can use it is checked live, for free, before the first paid call). Key only from
`OPENAI_API_KEY`. `store=false`; no `temperature`.
**Why.** Requested by the owner; Structured Outputs lets the codebook's codes be enforced as enums, while the same
server validator still checks every value, quote and passage id for both providers.
**Not chosen.** Chat Completions; reusing the old OpenAI-compatible adapter for OpenAI itself. That adapter is kept,
unchanged, as provider `openai_compatible` when `OPENAI_BASE_URL` is set (local models).

## D-024 · 2026-10-01 · Operating modes; default unchanged — Active (branch)
**Decision.** Modes `single` (default: original behavior — one provider via `model_provider`, Claude first),
`anthropic_only`, `openai_only`, `dual_independent`, `anthropic_primary_openai_review`, `openai_primary_anthropic_review`.
A second provider never starts because a key exists; a mode must be chosen. Search/fetch run once per case; providers
receive identical prompts built from one evidence preparation. Independent coders never see each other's output; a
reviewer does and is labelled "not independent". Agreement is not verification: disagreement (or an invalid output)
routes the variable to human review, blocks a plain "accept" (a specific provider's suggestion must be chosen) and
blocks unreviewed export of that value.

## D-025 · 2026-10-01 · Never cache a reply that contains invalid items (all providers) — Active (branch)
**Decision.** A model reply is cached only if it is complete, readable, schema-valid (OpenAI) and every item passes
server validation. Previously a complete Claude reply was cached even when some items failed validation.
**Why.** Owner requirement: invalid codebook values / schema-noncompliant replies must not be cached.
**Trade-off.** Re-analysis re-sends (and re-pays for) batches whose reply had an invalid item, instead of reproducing
the same invalid result for free. Valid batches are still reused.

## D-026 · 2026-10-01 · Cache key v2; old Claude cache entries reused read-only — Active (branch)
**Decision.** Key = hash of provider, model, prompt version + exact prompt text, codebook version, variable set,
evidence hash (ids + text), response-schema version + hash, generation settings (e.g. reasoning effort) and role. The
output-token limit is not part of the key: only complete replies are cached, and a complete reply does not depend on
the limit. Old `llm:` keys (model + Claude system prompt + prompt) are still read for Claude only, so existing cached
replies are reused without re-billing.

## D-027 · 2026-10-01 · Per-case model-attempt caps and an OpenAI budget — Active (branch)
**Decision.** New append-only `model_calls` ledger records every request sent (incl. 429/connection retries) with
tokens, reasoning tokens, request id and status. Server-side checks before every request: combined budget
(`budget_usd`), `openai_budget_usd` ($3), `max_openai_attempts_per_case` (50), `max_model_attempts_per_case` (100).
Usage rows from before the ledger count as one attempt each. Approval raises each limit to the explicit value needed.
**Still pending (rest of D-021).** A per-case cap on search requests (today `max_queries` is per run).

## D-028 · 2026-10-01 · OpenAI output allowance includes a reasoning reserve — Active (branch, needs live calibration)
**Decision.** `max_output_tokens` = min(`openai_max_output_tokens` 32,000, `openai_reasoning_reserve_tokens` 16,000 +
1,500 + 1,200 per variable). Reasoning effort `medium` (OpenAI's default for `gpt-6.1-sol`), configurable.
**Why.** OpenAI bills reasoning tokens as output and counts them against `max_output_tokens`; a reply cut off there is
billed and discarded. The reserve only raises the worst-case figure checked against budgets.
**To revisit** after the first live runs, using the logged reasoning/output tokens per batch.

## D-029 · 2026-10-01 · Configuration errors stop immediately — Active (branch)
**Decision.** Unknown/unavailable model, rejected key, missing permission and exhausted quota are configuration errors:
never retried; a job pauses with a plain message before estimating or spending. Claude 401/403/404 follow the same rule.

## D-030 · 2026-10-01 · Stop and resume each provider independently — Active (branch)
**Decision.** Per job and provider, a stop flag (`provider_controls`) is checked before every batch. Providers in one job
run one after another (Claude first in dual mode), on one shared evidence preparation. Stopping a provider: its batches
not yet sent are recorded as `stopped` (no request, no cost; `model_calls` status `stopped`); a request already sent
cannot be recalled — it finishes, is billed and is kept; completed and cached results stay; the other provider is not
affected (if it has not started yet, it still runs). Resume: if the stop has not taken effect, the flag is withdrawn;
otherwise a follow-up job codes only that provider's stopped variables in the same comparison group (other results are
not re-sent). The job-level Cancel still stops everything.
**Not chosen.** Running both providers in parallel threads: faster, but needs budget reservations to keep the combined
budget strict under concurrency, and SQLite writes from two threads; not worth the risk for this release.

## D-031 · 2026-10-01 · Review table shows one column per provider — Active (branch)
**Decision.** Columns `# | Variable | Claude suggestion | OpenAI suggestion | Human final | Comparison | Review status`.
Each provider column = that provider's latest result across all runs (rows before OpenAI support are Claude's). A run
of one provider never replaces the other's column. A `stopped` row never hides that provider's earlier completed
value (shown with a "latest run stopped" note). Comparison is labelled independent, reviewer (not independent) or
separate runs (evidence may differ). Human final is `reviews` only; no model run writes to it.

## D-032 · 2026-10-01 · Bulk confirmation of independent model agreement — Active (branch `feature/bulk-agreement`)
**Decision.** Model agreement never becomes a final value by itself. Variables meeting all eligibility rules are
offered in a confirmation dialog; only the variables the reviewer leaves checked, and that are still eligible at write
time, receive a Human final (`reviews.action = accepted`, `method = bulk_independent_agreement`) with a full audit row
in `bulk_confirmations`. Eligibility: same dual-independent run (same `group_id`, both role `independent`); same
recorded prompt version, codebook version and batch evidence fingerprint; both `suggested`, validated, non-blank, no
counter-evidence, not stale; normalized values equal (code sets, numbers, ISO dates); field type categorical, numeric,
date, or open list with only codebook-listed options (free text, admin, generated, derived never); no review of any
kind (accepted, edited, cleared or deferred). Two blanks = "Both insufficient". Undo/correction = the normal Reset /
Edit actions; re-analysis never writes to Human final.
**Owner choices (2026-10-01):** only the same dual-independent run qualifies (separate runs never); open lists only
with listed options; a deferred review excludes the variable.

## D-033 · 2026-10-02 · Stay responsive under load; never auto-restart an interrupted job — Proposed (branch `fix/health-under-load`, not merged)
**Context.** 2026-10-01 ~11:45 pm (dual-mode test): while the server prepared one re-analysis, Render's health check
(`/healthz`, 5 s timeout) failed repeatedly, Render restarted the service (502 for visitors), and on startup the code
re-queued the running job, which repeated the heavy work. Logs show a 45 s gap between two steps that take ~0.3 s
locally. Most likely cause (not yet confirmed on Render): numerical libraries (OpenBLAS/OpenMP via numpy/scikit-learn)
start one thread per CPU of the whole host machine; on a 0.5-CPU plan these threads use up the CPU allowance and the
kernel pauses the whole process, including the thread that answers the health check. The evidence index (BM25 + LSA)
was also rebuilt for every cost estimate, the gap check and the run itself.
**Decision.** (1) Limit native thread pools to 1 (`app/__init__.py` before numpy loads, and Dockerfile `ENV`;
override with `WFD_NATIVE_THREADS`). (2) Build the evidence index once per case and evidence set, share it, rebuild
automatically when passages change (`retrieval.get_index`). (3) Run the background worker at lower CPU priority
(nice 10) than web requests. (4) After a restart, a job that was running is **paused** (`needs_input`,
`awaiting = interrupted`) and only continues when the owner clicks Resume; a job being cancelled ends cancelled.
(5) Every model request is written to `model_calls` with status `sending` and its worst-case cost **before** it is
sent; at startup any `sending` row becomes `interrupted_possibly_billed` and a worst-case `usage` row is added, so a
request cut off by a crash still counts toward the case budget and attempt limits.
**Not chosen (yet).** A larger instance or a separate worker service would also isolate the web server from heavy
work, but costs money; revisit only if the problem recurs after this fix (needs owner approval).
