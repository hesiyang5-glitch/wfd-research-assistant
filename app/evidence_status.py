"""Provider-neutral evidence status (D-038).

Every model suggestion carries two INDEPENDENT dimensions:

- evidence status (epistemic): how well the supplied case evidence supports the suggested value —
  SUPPORTED, INFERRED, AMBIGUOUS, INSUFFICIENT, CONFLICTING. Reported by the model, checked for consistency here.
- validation status (mechanical): whether the reply passed the server validator — valid, partially_valid, invalid
  (system/validation errors are never an evidence status).

Rules enforced here and in app/agreement.py / app/export.py:
1. INFERRED is never turned into a human-final value (it is not exported unreviewed and not bulk-confirmable).
2. AMBIGUOUS, INSUFFICIENT and CONFLICTING never force a value: INSUFFICIENT always stores a blank value; AMBIGUOUS
   and CONFLICTING keep at most the model's best candidate, stored with status "disputed" (human review).
3. A model may name a best candidate while still marking it INFERRED or AMBIGUOUS.
4. Human-approved final values live in the `reviews` table and are never touched by this module.
5. Agreement between providers never upgrades an evidence status (agreement is not verification).
6. Each variable is classified on its own evidence, so cause uncertainty cannot erase a supported failure phenomenon.

Rows stored before this layer existed have NULL evidence/validation status: shown as "not recorded" and never
rewritten (the validation status of such rows is derived from their stored status at read time).
"""
from __future__ import annotations

import json

EVIDENCE_STATUSES = ("SUPPORTED", "INFERRED", "AMBIGUOUS", "INSUFFICIENT", "CONFLICTING")
VALIDATION_STATUSES = ("valid", "partially_valid", "invalid")
LEGACY_MODEL_STATUSES = ("suggested", "insufficient_evidence", "disputed", "rule_unclear")

LABELS = {
    "SUPPORTED": "Supported — the cited evidence directly satisfies the codebook definition",
    "INFERRED": "Inferred — best interpretation, but it needs an inference the evidence does not directly establish",
    "AMBIGUOUS": "Ambiguous — more than one permitted value remains reasonably supported",
    "INSUFFICIENT": "Insufficient — the evidence does not establish a defensible value",
    "CONFLICTING": "Conflicting — credible evidence supports incompatible interpretations",
    None: "Evidence status not recorded (result predates evidence statuses or the reply omitted it)",
}
VALIDATION_LABELS = {
    "valid": "Passed server validation",
    "partially_valid": "Partly passed validation — some selections or citations were rejected",
    "invalid": "Failed server validation",
    "not_applicable": "Not a model suggestion (error, stopped, derived or generated)",
    None: "Validation status not recorded",
}

WARN = {
    "evidence_status_missing": "the reply did not give an evidence status — shown as not recorded; needs human review",
    "value_with_insufficient": "the model marked the evidence INSUFFICIENT but proposed a value — the value was not kept",
    "status_without_value": "the model marked the evidence {es} but gave no value — stored blank",
    "ambiguous_without_alternatives": "marked AMBIGUOUS but no supported alternative value was given",
    "conflicting_without_counter_evidence": "marked CONFLICTING but no valid contradicting or alternative citation was given",
    "alternative_rejected": "alternative value {value!r} was not kept: {why}",
    "missing_evidence_not_described": "marked {es} but did not say what evidence is missing",
}


def read_evidence_status(item: dict) -> tuple[str | None, list[str], list[str]]:
    """(evidence status or None, error messages, reason codes). An unknown value is a malformed reply."""
    raw = item.get("evidence_status")
    if raw is None or raw == "":
        return None, [], []
    if not isinstance(raw, str) or raw.strip().upper() not in EVIDENCE_STATUSES:
        return None, [f"malformed output: evidence_status {raw!r} is not one of {', '.join(EVIDENCE_STATUSES)}"], \
            ["invalid_evidence_status"]
    return raw.strip().upper(), [], []


def validate_alternatives(field: dict, item: dict, passages: dict, chosen_value: str, validate) -> tuple[list, list]:
    """Each alternative is checked like a value: a permitted code with at least one valid supporting citation.
    Rejected alternatives are reported as warnings and do not affect the main value. Returns (kept, warnings)."""
    raw = item.get("alternatives")
    if raw in (None, ""):
        return [], []
    if not isinstance(raw, list):
        return [], [WARN["alternative_rejected"].format(value="(all)", why="alternatives is not a list")]
    kept, warns, seen = [], [], set()
    for a in raw:
        if not isinstance(a, dict):
            warns.append(WARN["alternative_rejected"].format(value=str(a)[:40], why="not a {value, evidence} entry"))
            continue
        val = a.get("value")
        if isinstance(val, list):
            val = ", ".join(str(x) for x in val)
        val = str(val or "").strip()
        if not val:
            continue
        v = validate(field, {"value": val, "evidence": a.get("evidence") or [], "options": a.get("options") or []},
                     passages)
        if not v["ok"] or v.get("outcome") != "valid" or not v["value"]:
            why = "; ".join(v.get("errors") or ["no valid supporting citation"])[:200]
            warns.append(WARN["alternative_rejected"].format(value=val, why=why))
            continue
        if v["value"].upper() == (chosen_value or "").upper() or v["value"].upper() in seen:
            continue
        seen.add(v["value"].upper())
        kept.append({"value": v["value"], "evidence": v["evidence"]})
    return kept, warns


def resolve(field: dict, item: dict, v: dict, passages: dict, validate, *, require_status: bool = True) -> dict:
    """Combine the validator result `v` with the model's evidence status. Returns
    {status, value, evidence_status, validation_status, alternatives, missing_evidence, warnings, reason_codes,
     errors, complete} where `status` is the legacy stored status used by the review workbench."""
    es, es_err, es_codes = read_evidence_status(item)
    warnings, codes, errors = [], list(es_codes), list(es_err)
    proposed = item.get("value")
    if es == "INSUFFICIENT" and proposed not in (None, "", []):
        # rule 2: never force a value — the proposed value is reported, not validated or kept
        warnings.append(WARN["value_with_insufficient"])
        codes.append("value_with_insufficient")
        v = validate(field, {**item, "value": "", "options": []}, passages)
    rule_unclear = item.get("rule_unclear") is True or item.get("status") == "rule_unclear"
    legacy = item.get("status") if item.get("status") in LEGACY_MODEL_STATUSES else None
    missing_evidence = item.get("missing_evidence")
    missing_evidence = missing_evidence.strip() if isinstance(missing_evidence, str) else ""
    complete = True
    if es is None and not es_err and require_status:
        warnings.append(WARN["evidence_status_missing"])
        codes.append("evidence_status_missing")
        complete = False

    if es_err or not v["ok"]:
        validation_status = "invalid"
    else:
        validation_status = "partially_valid" if v.get("outcome") == "partially_valid" else "valid"

    if validation_status == "invalid":
        return {"status": "validation_failed", "value": "", "evidence_status": es, "validation_status": "invalid",
                "alternatives": [], "missing_evidence": missing_evidence, "warnings": warnings,
                "reason_codes": codes, "errors": errors, "complete": False}

    value = v["value"]
    alternatives, alt_warn = validate_alternatives(field, item, passages, value, validate)
    warnings += alt_warn
    if alt_warn:
        codes.append("alternative_rejected")

    if es == "INSUFFICIENT":
        status, value = "insufficient_evidence", ""
        if not missing_evidence:
            warnings.append(WARN["missing_evidence_not_described"].format(es=es))
    elif es in ("AMBIGUOUS", "CONFLICTING"):
        status = "partially_valid" if validation_status == "partially_valid" else "disputed"
        if es == "AMBIGUOUS" and not alternatives and len(v.get("options") or []) < 2:
            warnings.append(WARN["ambiguous_without_alternatives"])
            codes.append("ambiguous_without_alternatives")
        if es == "CONFLICTING" and not v.get("counter") and not alternatives:
            warnings.append(WARN["conflicting_without_counter_evidence"])
            codes.append("conflicting_without_counter_evidence")
    elif es in ("SUPPORTED", "INFERRED"):
        if not value:
            warnings.append(WARN["status_without_value"].format(es=es))
            codes.append("status_without_value")
            status = "insufficient_evidence"
        elif validation_status == "partially_valid":
            status = "partially_valid"
        else:
            status = "rule_unclear" if rule_unclear else "suggested"
    else:  # no evidence status: fall back to the reply's legacy status (results from earlier prompt versions)
        if validation_status == "partially_valid":
            status = "partially_valid"
        elif not value:
            status = "disputed" if legacy == "disputed" else "insufficient_evidence"
        else:
            status = "disputed" if legacy == "disputed" else ("rule_unclear" if rule_unclear else "suggested")
    return {"status": status, "value": value, "evidence_status": es, "validation_status": validation_status,
            "alternatives": alternatives, "missing_evidence": missing_evidence, "warnings": warnings,
            "reason_codes": codes, "errors": errors, "complete": complete}


MODEL_ROW_STATUSES = ("suggested", "rule_unclear", "disputed", "insufficient_evidence", "partially_valid",
                      "validation_failed")


def validation_status_of(row: dict) -> str | None:
    """Stored validation status, or one derived at read time for rows saved before 2026-10-06 (never written back)."""
    if row.get("validation_status"):
        return row["validation_status"]
    st = row.get("status")
    if st not in MODEL_ROW_STATUSES:
        return "not_applicable"
    if st == "validation_failed":
        return "invalid"
    if st == "partially_valid":
        return "partially_valid"
    return "valid"


def evidence_status_of(row: dict) -> str | None:
    es = row.get("evidence_status")
    return es if es in EVIDENCE_STATUSES else None


def recorded(row: dict) -> bool:
    """True when the row was stored by the evidence-status layer (it then always has a validation status)."""
    return bool(row.get("validation_status"))


def alternatives_of(row: dict) -> list:
    try:
        out = json.loads(row.get("alternatives_json") or "[]")
        return out if isinstance(out, list) else []
    except (TypeError, ValueError):
        return []


def review_required(row: dict) -> str:
    """Non-empty reason when the evidence status forbids treating this suggestion as a value without a human decision
    (rule 1: INFERRED is never exported or derived from unreviewed; rule 2: no forced value). Rows stored before
    evidence statuses existed keep their earlier behaviour."""
    if not recorded(row):
        return ""
    es = evidence_status_of(row)
    if es == "SUPPORTED":
        return ""
    return f"evidence status {es or 'missing'} — needs human review"
