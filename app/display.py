"""Presentation names for internal identifiers shown to researchers in exports and run logs (display only, 2026-10-06).

The internal identifiers themselves — provider ids (`anthropic`, `openai`), roles (`independent`, and the historical
`primary` / `reviewer`), mode names (`dual_independent` …), database values, API routes and cache keys — are NOT
changed by this module; it only maps them to readable text at the moment they are written into an Excel/TSV export or
a run-log line. The machine-readable JSON export keeps the raw identifiers on purpose.
"""
from __future__ import annotations

PROVIDER_API = {"anthropic": "Anthropic API", "openai": "OpenAI API", "openai_compatible": "OpenAI-compatible API",
                "tavily": "Tavily Search API", "brave": "Brave Search API", "searxng": "SearXNG"}
PROVIDER_CODING = {"anthropic": "Claude — Anthropic API", "openai": "GPT — OpenAI API",
                   "openai_compatible": "OpenAI-compatible API"}
MODE_DISPLAY = {
    "single": "One provider (default of older cases)",
    "anthropic_only": "Claude only — Anthropic API",
    "openai_only": "GPT only — OpenAI API",
    "dual_independent": "Claude + GPT — independent comparison",
    "anthropic_primary_openai_review": "Cross-model review (historical, audit only)",
    "openai_primary_anthropic_review": "Cross-model review (historical, audit only)",
}
COMPARISON_CLASS = {"matched_version": "Matched analysis version", "cross_version": "Cross-version",
                    "cross_model_review": "Cross-model review (audit only)"}
CONFIRM_METHOD = {"bulk_independent_agreement": "Human-approved model agreement (bulk)",
                  "bulk_separate_run_agreement": "Human-approved cross-version agreement (bulk, D-035)"}
BULK_HEADERS = {
    "batch_id": "Batch ID", "variable": "Variable", "value": "Confirmed value",
    "claude_suggestion_id": "Claude suggestion ID (Anthropic API)", "openai_suggestion_id": "GPT suggestion ID (OpenAI API)",
    "claude_model": "Claude model (Anthropic API)", "openai_model": "GPT model (OpenAI API)",
    "group_id": "Comparison group", "codebook_version": "Codebook version", "prompt_version": "Prompt version",
    "evidence_difference": "Different supporting sources (1 = yes)", "previous_value": "Previous value",
    "reviewer": "Reviewer", "at": "Confirmed at", "method": "Confirmation method",
    "evidence_snapshot_id": "Evidence version", "analysis_spec_id": "Analysis version",
    "claude_run_id": "Claude run ID (Anthropic API)", "openai_run_id": "GPT run ID (OpenAI API)",
    "claude_cache_status": "Claude cache status", "openai_cache_status": "GPT cache status",
    "claude_generated_at": "Claude result generated at", "openai_generated_at": "GPT result generated at",
    "comparison_class": "Comparison class", "differences_json": "Version differences (JSON)",
    "warning_shown": "Cross-version warning shown (1 = yes)", "acknowledged": "Warning acknowledged (1 = yes)",
    "claude_versions_json": "Claude analysis versions (JSON)", "openai_versions_json": "GPT analysis versions (JSON)",
    "selected_json": "Selected variables (JSON)",
}


def provider_api(p) -> str:
    """'anthropic' -> 'Anthropic API'; 'anthropic+openai' -> 'Anthropic API + OpenAI API'; unknown values unchanged."""
    if not p:
        return ""
    return " + ".join(PROVIDER_API.get(x, x) for x in str(p).split("+"))


def provider_coding(p) -> str:
    return PROVIDER_CODING.get(p, p or "")


def mode_display(m) -> str:
    return MODE_DISPLAY.get(m, m or "")


def interpretation_display(interp: str | None, role: str | None = None) -> str:
    """Readable interpretation. Historical roles are shown as recorded (never relabelled as 'independent')."""
    from .coding import INTERPRETATION_LABELS
    if not interp:
        return ""
    label = INTERPRETATION_LABELS.get(interp, interp)
    if role in ("primary", "reviewer"):
        # the role exactly as the older run recorded it comes first; the interpretation follows (D-036)
        return f"{role} (historical role) — {label}"
    return label
