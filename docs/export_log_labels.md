# Readable names in exports and run logs (2026-10-06, branch `ui/export-log-labels`)

Display only. Internal provider ids (`anthropic`, `openai`), roles (`independent`; historical `primary` / `reviewer`),
mode names, database values, API routes, request payloads and cache keys are unchanged. New runs keep storing
`anthropic` / `openai` with role `independent`. The mapping lives in `app/display.py` and is applied only when a value
is written into the Excel/TSV export or a run-log line. The machine-readable JSON export keeps the raw ids.

| Where | Before (raw) | After (display) |
|---|---|---|
| Excel Provider_Suggestions · Provider | `anthropic` / `openai` | Anthropic API / OpenAI API |
| Excel Provider_Suggestions · Interpretation | `independent` / `cross_model_review` | Independent provider result / Cross-model review (audit only — saw another model's answer) |
| Excel Evidence · Provider, Interpretation | same raw values | same display values |
| Excel Results · Accepted from provider | `anthropic`, `openai`, `anthropic+openai` | Anthropic API, OpenAI API, Anthropic API + OpenAI API |
| Excel Results · Evidence status (two providers) | `anthropic: SUPPORTED; openai: SUPPORTED` | Anthropic API: SUPPORTED; OpenAI API: SUPPORTED |
| Excel Results · Explanation (and TSV) | `[accepted from anthropic+openai suggestion]` | [accepted from Anthropic API + OpenAI API suggestion] |
| Excel Results · Explanation (and TSV) | `[providers: value_disagreement; human decision needed]` | [providers: Value disagreement; human decision needed] |
| Excel Bulk_Confirmations · headers | `batch_id`, `claude_suggestion_id`, `openai_model`, `comparison_class`, … (30) | Batch ID, Claude suggestion ID (Anthropic API), OpenAI model (OpenAI API), Comparison class, … |
| Excel Bulk_Confirmations · Confirmation method | `bulk_independent_agreement` / `bulk_separate_run_agreement` | Human-approved model agreement (bulk) / Human-approved cross-version agreement (bulk, D-035) |
| Excel Bulk_Confirmations · Comparison class | `matched_version` / `cross_version` | Matched analysis version / Cross-version |
| Excel Search_Log · header and value | Provider · `tavily` | Search service · Tavily Search API |
| Excel Runs_Usage · usage Provider | `anthropic` / `openai` | Anthropic API / OpenAI API |
| Excel Runs_Usage · runs Provider | `anthropic` / `openai` | Anthropic API / OpenAI API |
| Excel Runs_Usage · runs Interpretation | `independent` (also for a historical `primary` run), `cross_model_review` | Independent provider result; **primary (historical role) — Independent provider result**; **reviewer (historical role) — Cross-model review (…)** |
| Excel Runs_Usage · runs Coding mode | `dual_independent`, `anthropic_only`, `openai_only`, `single`, `anthropic_primary_openai_review` | Claude + OpenAI — independent comparison, Claude only — Anthropic API, OpenAI only — OpenAI API, One provider (default of older cases), Cross-model review (historical, audit only) |
| Run log | `mode dual_independent: combined worst case …` | Claude + OpenAI — independent comparison: combined worst case … |
| Run log | `could not check anthropic model availability now …` | could not check Claude — Anthropic API model availability now … |
| Coding error message | `Coding mode 'openai_only' needs …` | Coding mode 'OpenAI only — OpenAI API' needs … |
| API error (mode cannot run) | `coding mode 'dual_independent' cannot run: …` | coding mode 'Claude + OpenAI — independent comparison' cannot run: … |
| Review panel / export notes (two providers) | `anthropic: evidence status INFERRED …`, `openai: …` | Claude — Anthropic API: evidence status INFERRED …, OpenAI — OpenAI API: … |

Not changed (raw values kept on purpose): the JSON export; stored data; suggestion status codes such as
`insufficient_evidence` / `providers_differ` in the "Suggestion status" column and explanation notes (status codes,
not provider/role/mode ids); cache status `new` / `hit`; Sources-sheet columns; the API error for an unknown mode
(it repeats the value that was sent).
