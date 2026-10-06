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
| K-40 | Fixed on branch `feature/independent-providers` (D-036, not merged): cache identity is the model-visible input, not the role; a single-provider result is reused when that provider joins a dual run. Verified offline only. | — |
| K-41 | Claude LESSONS_IDENTIFIED (Marshall Fire) shows "invalid output" (validation failed). Most likely a quote not found verbatim, as earlier with SUMMARY / INCLUSION_CRITERIA_INDICATORS; exact validator message not yet read. OpenAI's suggestion for that field is usable for review. | Low |
| K-42 | Re-analyze can run one variable or all; there is no multi-select. Starting a second variable while one is running does not queue it (duplicate-submission guard returns the running job). Possible feature: "Re-analyze selected" (not started). | Low |
| K-43 | Resolved by the cross-version class (D-036): existing results without recorded versions stay comparable as "cross-version (version not recorded)" and can be bulk-confirmed with the warning and acknowledgement. Re-analysis on unchanged evidence is expected to come from cache at ~$0 — not yet verified on production data. | Low |