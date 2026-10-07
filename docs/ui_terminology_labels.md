# Interface terminology — changed labels (2026-10-06, branch `ui/terminology-labels`)

This change modifies interface labels and explanatory copy only. It does not change provider behavior, model requests,
evidence handling, caching, pricing, database structure, or coding results.

Naming levels: **provider** = company (Anthropic, OpenAI) · **API** = programming interface (Anthropic API, OpenAI API) ·
**model** = the identifier the backend already supplies (Claude: the `model_name` setting; OpenAI: `OPENAI_MODEL`).
Chinese labels follow the same pattern (e.g. "Claude 编码 — Anthropic API").

| Where | Before | After |
|---|---|---|
| Provider name everywhere (`PROV` map) | Claude (Anthropic) / OpenAI | Claude / OpenAI, with "— Anthropic API" / "— OpenAI API" where the API is meant |
| Services | Services (one flat list) | Services → External services / AI coding providers / Internal processing |
| Services | Web search — tavily | Web search — Tavily Search API |
| Services | Claude (Anthropic) — configured | Claude coding — Anthropic API · Model: `claude-…` · Status: configured |
| Services | OpenAI — configured · gpt-6.1-sol | GPT coding — OpenAI API · Model: `gpt-…` · Status: configured (owner choice 2026-10-06: coding lines name the model family) |
| Services | OCR (scanned PDFs) — tesseract | Scanned-document text recognition — Tesseract OCR |
| Services | Semantic retrieval — LSA approximation (not neural) + BM25 keywords | Evidence retrieval — LSA + BM25 (LSA approximation, not neural embeddings) |
| Services | — | API / OCR / LSA / BM25 expanded (tooltips + one line) |
| Services (no key configured) | Language model | AI coding providers |
| Research form legend | Coding provider | Coding-provider selection |
| Research form / Re-analyze / Settings option | Claude only | Claude only — Anthropic API (+ "Model: `claude-…`" on the card) |
| same | OpenAI only | OpenAI only — OpenAI API (+ "Model: `gpt-…`") |
| same | Claude + OpenAI — independent comparison | unchanged (+ "Claude: Anthropic API · `claude-…`", "OpenAI: OpenAI API · `gpt-…`") |
| Card help (Claude only) | One shared research process, then Claude interprets the evidence. | One shared research process, followed by coding with Claude. |
| Card help (OpenAI only) | … then OpenAI interprets the evidence. | One shared research process, followed by coding with OpenAI. |
| Card help (dual) | Both providers will independently analyze the same evidence. To protect server responsiveness, their requests may be processed sequentially. | Both providers independently analyze the same available evidence. Requests may be processed sequentially to protect server responsiveness. |
| Cost estimate | Shared web search (runs once) | Shared web research — Tavily Search API (runs once) |
| Cost estimate | Claude (Anthropic) · claude-… / OpenAI · gpt-… | Claude coding — Anthropic API · `claude-…` / GPT coding — OpenAI API · `gpt-…` |
| Cost estimate | $low – **$high** | Expected cost $low · Maximum estimated cost **$high** (tooltip explains both) |
| Cost estimate | Claude (Anthropic) — $0.00 — not selected | Claude coding — Anthropic API — Not selected — $0.00 |
| Cost estimate | Combined (worst case) … models $a – $b | Combined — maximum estimated cost … models: expected $a · maximum $b |
| Cost estimate | (OpenAI cap $3.00) | (OpenAI coding budget $3.00) |
| Cost estimate | all models 100 · OpenAI 50 | all providers 100 · OpenAI API 50 |
| Confirm dialog | Coding provider / Web search | Coding-provider selection (+ model lines) / Web research |
| Re-analyze (whole case and one variable) | Coding provider (only options whose keys are configured on the server) | Coding-provider selection (only options configured on the server) |
| Re-analyze | Claude (Anthropic) · claude-… | Claude coding — Anthropic API · Claude model: `claude-…` |
| Re-analyze | effort medium | OpenAI reasoning effort: medium (tooltip) |
| Re-analyze | 9 call(s) (9 new) · $low – $high | 9 request(s) · Cached requests 0 · New paid requests 9 · Expected cost … · Maximum estimated cost … |
| Re-analyze (dual) | (dual card help) | Both providers independently analyze the same available evidence. Neither provider is labeled as primary or secondary. Requests may be processed sequentially to protect server responsiveness. |
| Re-analyze | Spent: Claude / OpenAI / search | Spent: Claude coding / GPT coding / web search |
| Re-analyze | OpenAI budget · Model attempts (this case) | OpenAI coding budget · Model requests (this case) |
| Re-analyze limits | Combined budget ($) / OpenAI budget ($) / OpenAI attempts / All model attempts | Research budget limit ($) / OpenAI coding budget per case ($) / OpenAI request limit per case / Model-request limit per case |
| Progress | Mode / Coding provider | Coding-provider selection |
| Progress | Model providers; row "Claude (Anthropic)" | AI coding providers; row "Claude — Anthropic API" |
| Progress | Search provider: tavily | Search service: Tavily Search API |
| Progress — Stop dialog title | Stop Claude (Anthropic) | Stop Claude coding — Anthropic API (buttons stay "Stop Claude" / "Resume OpenAI") |
| Progress — coding report | · Claude (Anthropic) claude-… | · Claude — Anthropic API · `claude-…` |
| Review — per-model panel | Claude (Anthropic) | Claude suggestion · Anthropic API · `claude-…` |
| Search log column | Provider | Search service |
| Settings | `search_provider` | Search service (options: Automatic (first configured service) / Tavily Search API / Brave Search API / SearXNG / None (manual sources only)) |
| Settings | `model_provider` | Configured model provider (+ note: used only by the older "One provider" setting; options Automatic / Anthropic API (Claude) / OpenAI API / None (manual coding)) |
| Settings | `model_name` | Configured model (+ note: Claude model identifier used with the Anthropic API; OpenAI model from OPENAI_MODEL) |
| Settings | `max_search_rounds` · `max_queries` · `pages_per_query` · `results_per_query` · `max_fetch` | Maximum search rounds · Maximum search queries · Pages per search query · Results per search query · Maximum pages to retrieve |
| Settings | `time_limit_minutes` · `budget_usd` | Research time limit (minutes) · Research budget limit (USD) (+ note: per case, all providers + search, all re-runs) |
| Settings | `passages_per_variable` · `max_passages_per_call` | Evidence passages per variable · Evidence passages per model request |
| Settings | `coding_mode` · `max_model_attempts_per_case` | Coding-provider selection · Model-request limit per case |
| Settings | `openai_budget_usd` · `max_openai_attempts_per_case` | OpenAI coding budget per case (USD) · OpenAI request limit per case |
| Settings | `openai_reasoning_effort` · `openai_reasoning_reserve_tokens` | OpenAI reasoning effort · OpenAI reasoning-token allowance (+ explanations) |
| Settings | `openai_max_output_tokens` · `openai_timeout_seconds` | OpenAI maximum output tokens per request · OpenAI request timeout (seconds) |
| Settings | `follow_links` · `require_approval_over_budget` (true/false) | Follow links found in sources · Pause for approval when over budget (yes/no; submitted values still true/false) |
| Settings note | max_passages_per_call is a batch size … more calls. | Evidence passages per model request is a batch size … more requests. |
| Server reason (mode unavailable / provider check) | Claude is not configured on the server … | Claude coding (Anthropic API) is not configured on the server … |
| Run log / job messages | [anthropic] / [openai]; estimate [anthropic claude-…, primary]; Claude (Anthropic) | [Claude — Anthropic API] / [OpenAI — OpenAI API]; estimate [… · model, independent]; "No AI coding provider configured" |

Not changed (would alter stored data, prompts or exports — see KNOWN_ISSUES K-52): the stored rationale "No language model
configured: …" on manual-coding rows, `PROVIDER_LABELS` ("Claude (Anthropic)") inside historical cross-model prompts and
the Excel Provider_Suggestions sheet, internal ids/roles/mode names, environment-variable names in the Keys panel.

## Update 2026-10-07 — the coder is named "GPT" where the model is meant (owner rule)

Display text only (`web/app.js` `PROV`, mode / help text; `app/display.py`; `app/agreement.py` labels and reasons;
`app/server.py` Stop/Resume messages; `app/export.py` explanation). Stored ids (`openai`, `openai_only`,
`dual_independent`), payloads, cache, costs and the database are unchanged.

| Before | After |
|---|---|
| OpenAI only — OpenAI API | GPT only — OpenAI API |
| Claude + OpenAI — independent comparison | Claude + GPT — independent comparison |
| One shared research process, followed by coding with OpenAI. | … followed by coding with GPT. |
| OpenAI suggestion (Review table, detail panel) | GPT suggestion |
| OpenAI: OpenAI API · gpt-… / OpenAI model: gpt-… | GPT: OpenAI API · gpt-… / GPT model: gpt-… |
| Stop OpenAI / Resume OpenAI (buttons, job messages) | Stop GPT / Resume GPT |
| Agreement "OpenAI only"; "OpenAI has no completed result…"; "OpenAI marked the evidence …" | "GPT only"; "GPT has no completed result…"; "GPT marked the evidence …" |
| Version tables: Claude / OpenAI columns; "only in OpenAI's version" | Claude / GPT; "only in GPT's version" |
| Excel Bulk_Confirmations: "OpenAI model (OpenAI API)", "OpenAI run ID …", "OpenAI cache status" … | "GPT model (OpenAI API)", "GPT run ID …", "GPT cache status" … |
| Run log: "Claude + OpenAI — independent comparison: combined worst case …"; "[OpenAI — OpenAI API]" | "Claude + GPT — …"; "[GPT — OpenAI API]" |
| Explanation "[independent providers: Claude=…; OpenAI=…]" | "[independent providers: Claude=…; GPT=…]" |

Kept as **OpenAI** (company, account, API or bill): "OpenAI API", "OpenAI coding budget (per case)", "OpenAI request
limit per case", "OpenAI reasoning effort" and other OpenAI request settings, budget/limit pause messages
("OpenAI case budget"), `OPENAI_API_KEY` / `OPENAI_MODEL`, the Excel Provider column ("OpenAI API").
