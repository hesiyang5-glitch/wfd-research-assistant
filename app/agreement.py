"""Human-in-the-loop bulk confirmation of INDEPENDENT model agreement (DECISIONS D-032).

Model agreement is never a final value by itself. A variable is only *eligible*; a researcher must explicitly confirm
the selected variables, which writes Human final values with full audit records. Eligibility is re-checked at the
moment of writing, so nothing that changed in between can slip through.

Eligible only when ALL hold (D-036, replaces the D-035 separate-runs rule of 2026-10-02):
 1. Both results are INDEPENDENT provider results (neither model saw the other's answer). Cross-model review results
    (historical only) never qualify.
 2. Both interpreted the SAME evidence snapshot and the SAME analysis version (prompt version, shared rules, response
    schema, batching, codebook). They may come from different jobs — e.g. Claude earlier and OpenAI later, or results
    reused from the validated cache — and keep their original provenance; they are never relabelled "same run".
    Results with different or unrecorded versions are "Not comparable".
 3. Both results have status 'suggested' with a non-blank value that passed server validation (codebook values,
    verbatim quotes, valid passage ids), no counter-evidence, and are not stale (no cited source excluded since);
    same codebook version; identical batch evidence for this variable.
 4. Normalized values are equal (order-insensitive codes, trimmed/case-insensitive; numbers numerically; ISO dates).
 5. The field is model-coded and of type categorical, numeric, date, or open list with ONLY codebook-listed options.
    Free text, administrative, generated and derived fields are never eligible.
 6. No review exists for the variable (accepted, edited, cleared or deferred).
 7. (D-038) Both providers reported evidence status SUPPORTED. INFERRED, AMBIGUOUS, CONFLICTING, INSUFFICIENT or a
    missing status are never confirmed in bulk — agreement does not upgrade an evidence status. Results stored before
    evidence statuses existed (status "not recorded") keep their earlier eligibility, with that disclosed.
Two blank answers are 'Both insufficient', never an agreed value.
"""
from __future__ import annotations

import datetime as dt
import json
import time
import uuid

from . import db
from . import evidence_status as es_mod
from .validator import _num, split_values

METHOD = "bulk_independent_agreement"
METHOD_SEPARATE = "bulk_separate_run_agreement"  # D-035 (2026-10-02 only): kept so earlier confirmations stay labelled
BULK_METHODS = (METHOD, METHOD_SEPARATE)
FINAL_ACTIONS = ("accepted", "edited", "cleared")
ELIGIBLE_TYPES = ("categorical", "numeric", "date", "open_list")
LABELS = {
    "eligible": "Independent agreement — matched analysis version",
    "eligible_cross_version": "Cross-version agreement — review version differences",
    "cross_version_disagreement": "Cross-version disagreement — model and input differences may both contribute",
    "eligible_evidence_difference": "Independent agreement — matched analysis version (different supporting sources)",
    "confirmed": "Independent model agreement — human confirmed",
    "cross_model_review": "Cross-model review (audit only) — not independent",
    "value_disagreement": "Value disagreement",
    "both_insufficient": "Both insufficient",
    "claude_only": "Claude only",
    "openai_only": "GPT only",
    "validation_failed": "Validation failed",
    "pending": "Pending human review",
}
COMPLETED = ("suggested", "rule_unclear", "disputed", "insufficient_evidence", "validation_failed", "partially_valid")


def normalize(field: dict, value: str):
    """Comparable form of a value, or None when it cannot be normalized safely (then it is never eligible)."""
    v = (value or "").strip()
    if not v:
        return None
    t = field["type"]
    if t in ("categorical", "open_list"):
        parts = [p.strip().upper() for p in split_values(v) if p.strip()]
        return ("set", frozenset(parts)) if parts and len(parts) == len(set(parts)) else None
    if t == "numeric":
        n = _num(v)
        return ("num", n) if n is not None else None
    if t == "date":
        try:
            return ("date", dt.date.fromisoformat(v).isoformat())
        except ValueError:
            return None
    return None  # free text: never compared automatically


def _run(run_id):
    return db.q1("SELECT * FROM runs WHERE id=?", (run_id,)) if run_id else None


def _batch_hash(run_id, variable):
    for c in db.q("SELECT variables_json, evidence_hash FROM model_calls WHERE run_id=? ORDER BY id DESC", (run_id,)):
        try:
            if variable in json.loads(c["variables_json"] or "[]"):
                return c["evidence_hash"]
        except Exception:
            continue
    return None


def assess(case_id: int, field: dict, sset: dict | None, review: dict | None) -> dict | None:
    """Agreement status for one variable. Returns None for fields no model codes."""
    from .coding import comparison_kind, is_cached, version_differences
    if field.get("field_class") not in ("sourced", "judgment") or field.get("rule_missing"):
        return None
    cells = (sset or {}).get("cells") or {}
    a = (cells.get("anthropic") or {}).get("row")
    b = (cells.get("openai") or {}).get("row")
    sa = (cells.get("anthropic") or {}).get("state")
    sb = (cells.get("openai") or {}).get("state")
    final = bool(review and review.get("action") in FINAL_ACTIONS)

    def out(status, reason="", **kw):
        return {"status": status, "label": LABELS[status], "eligible": status.startswith("eligible"), "reason": reason,
                "human_final": final, **kw}

    a_done = a is not None and a["status"] in COMPLETED and sa != "stopped"
    b_done = b is not None and b["status"] in COMPLETED and sb != "stopped"
    if not a_done and not b_done:
        return None if (a is None and b is None) else out("pending", "neither provider completed this variable")
    if a_done and not b_done:
        return out("claude_only", "GPT has no completed result for this variable")
    if b_done and not a_done:
        return out("openai_only", "Claude has no completed result for this variable")
    kind = comparison_kind(a, b)
    if kind == "cross_model_review":
        return out("cross_model_review", "one model saw the other's answer; excluded from independent agreement")
    if a["status"] == "validation_failed" or b["status"] == "validation_failed":
        return out("validation_failed", "a provider's output failed server validation")
    vs = ("suggested", "rule_unclear", "disputed", "partially_valid")
    na = normalize(field, a["value"]) if a["status"] in vs else None
    nb = normalize(field, b["value"]) if b["status"] in vs else None
    if not (a["value"] or "").strip() and not (b["value"] or "").strip():
        return out("both_insufficient", "neither provider found a supported value")
    if not (a["value"] or "").strip() or not (b["value"] or "").strip():
        return out("pending", "one provider found no supported value")
    if field["type"] not in ELIGIBLE_TYPES:
        return out("pending", "free-text field: never confirmed in bulk")
    if na is None or nb is None:
        return out("pending", "value could not be normalized safely")
    ra, rb = _run(a.get("run_id")), _run(b.get("run_id"))
    cross = kind == "cross_version"
    diffs = version_differences(a, b, ra, rb) if cross else []
    vinfo = {"comparison_class": "cross_version" if cross else "matched_version", "differences": diffs,
             "claude": _prov_info(a, ra), "openai": _prov_info(b, rb),
             "evidence_statuses": {"claude": es_mod.evidence_status_of(a), "openai": es_mod.evidence_status_of(b)}}
    if na != nb:
        if cross:  # never attributed to Claude vs OpenAI alone (D-035/D-036)
            return out("cross_version_disagreement", "Results differ, but the models also used different analysis "
                                                     "inputs (" + ", ".join(diffs) + ")", **vinfo)
        return out("value_disagreement", "the providers' values differ", **vinfo)
    if not (ra and rb):
        return out("pending", "a run record is missing", **vinfo)
    if final:
        conf = review.get("method") in BULK_METHODS or (normalize(field, review.get("value") or "") == na)
        return out("confirmed" if conf else "pending", "Human final already set" if not conf else "",
                   method=review.get("method"), **vinfo)
    problems = []
    if "partially_valid" in (a["status"], b["status"]):
        problems.append("a provider's multi-select output was only partially valid (some selections were rejected)")
    elif a["status"] != "suggested" or b["status"] != "suggested":
        problems.append("a provider marked it disputed or the rule unclear")
    if a.get("counter") or b.get("counter"):
        problems.append("a provider reported contradicting or alternative evidence")
    not_recorded = []
    for who, r in (("Claude", a), ("GPT", b)):
        es = es_mod.evidence_status_of(r)
        if es_mod.recorded(r):
            if es is None:
                problems.append(f"{who} gave no evidence status")
            elif es != "SUPPORTED":
                problems.append(f"{who} marked the evidence {es} — agreement does not upgrade it to SUPPORTED")
        else:
            not_recorded.append(who)
    if a.get("stale") or b.get("stale"):
        problems.append("cites a source that was excluded later")
    if not a.get("evidence") or not b.get("evidence"):
        problems.append("missing validated supporting evidence")
    if ((a.get("validation") or {}).get("errors")) or ((b.get("validation") or {}).get("errors")):
        problems.append("validation errors")
    if field["type"] == "open_list":
        listed = {c["code"].upper() for c in field.get("codes", [])} | \
                 {o.split("(")[0].strip().upper() for o in field.get("open_options", [])}
        if any(p.split("(")[0].strip().upper() not in listed for p in na[1]):
            problems.append("open-list value not among the codebook's listed options")
    if ra.get("schema_version_id") != rb.get("schema_version_id"):
        # owner choice 2026-10-05: compared and shown, but never bulk-confirmed — the same code may mean different
        # things in two codebook versions; confirm such a variable individually
        problems.append("codebook versions differ — the same code may mean different things; confirm individually")
    if not cross:
        ha, hb = _batch_hash(ra["id"], field["name"]), _batch_hash(rb["id"], field["name"])
        if (ha or hb) and ha != hb:
            problems.append("evidence given to the two models for this variable was not identical")
    if review and review.get("action") == "deferred":
        problems.append("deferred by a reviewer")
    if problems:
        return out("pending", "; ".join(problems), **vinfo)
    src_a = {e.get("source_id") for e in a.get("evidence") or []}
    src_b = {e.get("source_id") for e in b.get("evidence") or []}
    diff = not (src_a & src_b)
    cached = [p for p, r in (("claude", a), ("openai", b)) if is_cached(r)]
    notes = (["Same suggested value, different analysis versions (" + ", ".join(diffs) + ")"] if cross else []) + \
            (["One or more results reused from validated cache"] if cached else []) + \
            ([f"Evidence status not recorded for {' and '.join(not_recorded)} (result predates evidence statuses)"]
             if not_recorded else [])
    status = "eligible_cross_version" if cross else ("eligible_evidence_difference" if diff else "eligible")
    return out(status, "; ".join(notes), evidence_difference=diff, reused_from_cache=bool(cached),
               cached_providers=cached, value=a["value"],
               group_id=a.get("group_id") if a.get("group_id") == b.get("group_id") else f"runs {ra['id']} + {rb['id']}",
               prompt_version=ra.get("prompt_version") if ra.get("prompt_version") == rb.get("prompt_version") else
               f"claude:{ra.get('prompt_version') or 'not recorded'} / openai:{rb.get('prompt_version') or 'not recorded'}",
               codebook_version=str(ra.get("schema_version_id")) if ra.get("schema_version_id") == rb.get("schema_version_id")
               else f"claude:{ra.get('schema_version_id')} / openai:{rb.get('schema_version_id')}",
               evidence_snapshot_id=a.get("evidence_snapshot_id") if not cross else None,
               analysis_spec_id=a.get("analysis_spec_id") if not cross else None, **vinfo)


def _prov_info(row: dict, run: dict | None) -> dict:
    run = run or {}
    return {"suggestion_id": row["id"], "model": row.get("model") or run.get("model"), "run_id": run.get("id"),
            "original_run_id": row.get("cache_source_run_id") or run.get("id"),
            "generated_at": row.get("generated_at") or row.get("created_at"),
            "cache_status": row.get("cache_status") or "new",
            "evidence_snapshot_id": row.get("evidence_snapshot_id"), "analysis_spec_id": row.get("analysis_spec_id"),
            "codebook_version": run.get("schema_version_id"), "prompt_version": run.get("prompt_version"),
            "evidence_status": es_mod.evidence_status_of(row), "validation_status": es_mod.validation_status_of(row)}


def case_assessments(case_id: int) -> dict:
    from .coding import schema_for_case, suggestion_sets
    case = db.q1("SELECT * FROM cases WHERE id=?", (case_id,))
    fields = {f["name"]: f for f in schema_for_case(case)["fields"]}
    sets = suggestion_sets(case_id)
    reviews = {r["variable"]: r for r in db.q("SELECT * FROM reviews WHERE case_id=?", (case_id,))}
    out = {}
    for name, f in fields.items():
        a = assess(case_id, f, sets.get(name), reviews.get(name))
        if a:
            out[name] = a
    return out


def eligible_summary(case_id: int) -> dict:
    """What the confirmation dialog shows. Read-only: never writes."""
    from .coding import schema_for_case
    case = db.q1("SELECT * FROM cases WHERE id=?", (case_id,))
    codes = {f["name"]: {c["code"].upper(): c["label"] for c in f.get("codes", [])} for f in schema_for_case(case)["fields"]}
    items, excluded = [], {}
    for name, a in case_assessments(case_id).items():
        if a["eligible"]:
            labels = [codes.get(name, {}).get(p.strip().upper()) for p in split_values(a["value"])]
            items.append({"variable": name, "value": a["value"], "value_label": "; ".join(x for x in labels if x),
                          "status": a["status"], "label": a["label"], "evidence_difference": a["evidence_difference"],
                          "reused_from_cache": a.get("reused_from_cache", False),
                          "cached_providers": a.get("cached_providers") or [],
                          "comparison_class": a.get("comparison_class"), "differences": a.get("differences") or [],
                          "cross_version": a.get("comparison_class") == "cross_version",
                          "claude": a["claude"], "openai": a["openai"]})
        else:
            excluded[a["label"]] = excluded.get(a["label"], 0) + 1
    return {"eligible": items, "excluded": excluded, "excluded_count": sum(excluded.values()),
            "note": "Agreement between two models does not independently prove a value is correct.",
            "cross_version_warning": CROSS_VERSION_WARNING}


CROSS_VERSION_WARNING = ("These model results were generated using different evidence, codebook, prompt, or analysis "
                         "versions. Agreement does not represent a controlled same-input comparison, and disagreement "
                         "cannot be attributed to the models alone. Review the version differences and supporting "
                         "evidence before confirming.")


class AcknowledgementRequired(Exception):
    pass


def bulk_confirm(case_id: int, variables: list[str], reviewer: str | None, acknowledged_cross_version: bool = False) -> dict:
    """Write Human final for the selected variables that are STILL eligible right now. Never touches a variable that
    has any review. One transaction; returns what was confirmed and what was skipped (with reasons).
    Cross-version agreements (D-035, retained) need the reviewer's explicit acknowledgement of CROSS_VERSION_WARNING;
    without it nothing is written."""
    batch = uuid.uuid4().hex[:12]
    now = time.time()
    confirmed, skipped = [], []
    selected = list(dict.fromkeys(variables or []))
    with db._lock:
        current = case_assessments(case_id)
        if any((current.get(v) or {}).get("status") == "eligible_cross_version" for v in selected) \
                and not acknowledged_cross_version:
            raise AcknowledgementRequired("cross-version results were selected: the version warning must be "
                                          "acknowledged before confirming")
        with db.tx() as c:
            for var in dict.fromkeys(variables or []):
                a = current.get(var)
                if not a or not a["eligible"]:
                    skipped.append({"variable": var, "reason": (a or {}).get("reason") or (a or {}).get("label") or "not eligible"})
                    continue
                if c.execute("SELECT 1 FROM reviews WHERE case_id=? AND variable=?", (case_id, var)).fetchone():
                    skipped.append({"variable": var, "reason": "a review already exists"})
                    continue
                cross = a.get("comparison_class") == "cross_version"
                method = METHOD_SEPARATE if cross else METHOD
                if cross:
                    reason = (f"Bulk confirmation of CROSS-VERSION agreement (D-035): same suggested value, different "
                              f"analysis versions ({', '.join(a.get('differences') or [])}); Claude {a['claude']['model']} "
                              f"+ GPT {a['openai']['model']}; version warning acknowledged by the reviewer")
                else:
                    reason = (f"Bulk confirmation of independent agreement — matched analysis version "
                              f"(Claude {a['claude']['model']} + GPT {a['openai']['model']}; evidence snapshot "
                              f"{a['evidence_snapshot_id']}, analysis version {a['analysis_spec_id']})"
                              + ("; evidence differed but both sets passed validation" if a["evidence_difference"] else ""))
                reason += (f"; reused from validated cache: {', '.join(a['cached_providers'])}" if a.get("cached_providers") else "")
                c.execute("INSERT INTO reviews (case_id,variable,value,action,reason,suggestion_id,updated_at,reviewer,"
                          "source_provider,method) VALUES (?,?,?,?,?,?,?,?,?,?)",
                          (case_id, var, a["value"], "accepted", reason, a["claude"]["suggestion_id"], now, reviewer,
                           "anthropic+openai", method))
                c.execute("INSERT INTO review_history (case_id,variable,old_value,new_value,action,reason,suggestion_id,at,"
                          "reviewer,source_provider,method) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                          (case_id, var, None, a["value"], "accepted", reason, a["claude"]["suggestion_id"], now, reviewer,
                           "anthropic+openai", method))
                ca, oa = a["claude"], a["openai"]
                c.execute("INSERT INTO bulk_confirmations (batch_id,case_id,variable,value,claude_suggestion_id,"
                          "openai_suggestion_id,claude_model,openai_model,group_id,codebook_version,prompt_version,"
                          "evidence_difference,previous_value,reviewer,at,method,evidence_snapshot_id,analysis_spec_id,"
                          "claude_run_id,openai_run_id,claude_cache_status,openai_cache_status,claude_generated_at,"
                          "openai_generated_at,comparison_class,differences_json,warning_shown,acknowledged,"
                          "claude_versions_json,openai_versions_json,selected_json) "
                          "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          (batch, case_id, var, a["value"], ca["suggestion_id"], oa["suggestion_id"],
                           ca["model"], oa["model"], a["group_id"], a["codebook_version"],
                           a["prompt_version"], 1 if a["evidence_difference"] else 0, None, reviewer, now, method,
                           a["evidence_snapshot_id"], a["analysis_spec_id"], ca["original_run_id"], oa["original_run_id"],
                           ca["cache_status"], oa["cache_status"], ca["generated_at"], oa["generated_at"],
                           a.get("comparison_class"), json.dumps(a.get("differences") or []),
                           CROSS_VERSION_WARNING if cross else None, 1 if (cross and acknowledged_cross_version) else 0,
                           json.dumps(ca, default=str), json.dumps(oa, default=str), json.dumps(selected)))
                confirmed.append({"variable": var, "value": a["value"]})
    return {"batch_id": batch, "confirmed": confirmed, "skipped": skipped}
