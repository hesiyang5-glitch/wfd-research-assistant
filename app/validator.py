"""Server-side validation of coding suggestions. A value can be legal and still unsupported — both are checked.
Nothing that fails validation is presented as a suggestion."""
from __future__ import annotations

import re
from datetime import date

QUOTE_MIN, QUOTE_MAX = 8, 500


def _norm_q(s: str) -> str:
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = s.replace("–", "-").replace("—", "-").replace(" ", " ").replace("­", "")
    s = re.sub(r"-\s+", "-", s)
    return re.sub(r"\s+", " ", s).strip().lower()


def quote_in_passage(quote: str, text: str) -> bool:
    q = _norm_q(quote).strip(" .\"'")
    if not q:
        return False
    t = _norm_q(text)
    if q in t:
        return True
    # tolerate an ellipsis joining two exact fragments from the same passage
    parts = [p.strip(" .\"'") for p in re.split(r"\s*(?:\.\.\.|…)\s*", q) if p.strip(" .\"'")]
    return len(parts) > 1 and all(len(p) >= 6 and p in t for p in parts)


def split_values(value: str) -> list[str]:
    return [p.strip() for p in re.split(r"[;,]", value or "") if p.strip()]


def _num(s: str):
    s = s.replace(",", "").replace("%", "").strip()
    m = re.fullmatch(r"-?\d+(\.\d+)?", s)
    if m:
        return float(s)
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*[–-]\s*(\d+(?:\.\d+)?)", s)
    if m:
        return (float(m.group(1)), float(m.group(2)))
    return None


# Machine-readable validation reason codes (stored in suggestions.validation_json -> "reason_codes" / "selections").
REASONS = {
    "invalid_code": "the code is not defined for this variable in the active codebook",
    "evidence_id_not_supplied": "a cited passage id was not among the passages sent to the model",
    "quote_not_found": "a quotation is not found verbatim in the cited passage",
    "quote_invalid_length": "a quotation is too short or too long to be checked",
    "evidence_does_not_support_selection": "the selection's valid citations are not marked as supporting it",
    "no_supporting_evidence": "no valid supporting citation was given for the value or selection",
    "malformed_output": "the model's output does not have the expected structure",
    "single_select_multiple_codes": "several codes given for a single-select variable",
    "special_missing_mixed": "a special missing value is mixed with other values",
    "duplicate_codes": "the same code is given more than once",
    "not_a_number": "not a number or numeric range",
    "percentage_out_of_range": "percentage must be between 0 and 100",
    "not_iso_date": "not an ISO date (YYYY-MM-DD)",
    "rule_missing": "no codebook rule for this field",
}


def _check(items, passages: dict, who: str) -> tuple[list[dict], list[tuple[str, str]]]:
    """Check citations one by one. Returns (valid citations, [(reason_code, message)] for rejected ones)."""
    good, bad = [], []
    for ev in items or []:
        pid = str(ev.get("id", "")).strip()
        quote = str(ev.get("quote", "")).strip()
        if pid not in passages:
            bad.append(("evidence_id_not_supplied", f"{who}: evidence id '{pid}' was not among the passages provided"))
            continue
        if not (QUOTE_MIN <= len(quote) <= QUOTE_MAX):
            bad.append(("quote_invalid_length", f"{who}: quote for {pid} has invalid length ({len(quote)} chars)"))
            continue
        if not quote_in_passage(quote, passages[pid]["text"]):
            bad.append(("quote_not_found", f"{who}: quote not found verbatim in {pid}"))
            continue
        p = passages[pid]
        good.append({"id": pid, "quote": quote, "stance": ev.get("stance", "supports"),
                     "source_id": p["source_id"], "page": p.get("page"), "para": p.get("para")})
    return good, bad


def check_evidence_list(items, passages: dict, errors: list, who: str, need_support=True) -> list[dict]:
    """Backward-compatible wrapper: appends human-readable messages to `errors`."""
    good, bad = _check(items, passages, who)
    errors.extend(m for _, m in bad)
    if need_support and not any(g["stance"] == "supports" for g in good):
        errors.append(f"{who}: no valid supporting evidence")
    return good


def _support_reason(good: list[dict]) -> tuple[str, str] | None:
    """Why a selection is unsupported although its citations may be valid."""
    if any(g["stance"] == "supports" for g in good):
        return None
    if good:
        return "evidence_does_not_support_selection", "valid citations are not marked as supporting this selection"
    return "no_supporting_evidence", "no valid supporting citation"


def _malformed(msg: str) -> dict:
    return {"ok": False, "outcome": "invalid", "value": "", "errors": [f"malformed output: {msg}"], "warnings": [],
            "evidence": [], "counter": [], "options": [], "selections": [], "reason_codes": ["malformed_output"],
            "rejected_citations": []}


def _dedupe(evs: list[dict]) -> list[dict]:
    seen, out = set(), []
    for e in evs:
        k = (e["id"], e["quote"])
        if k not in seen:
            seen.add(k)
            out.append(e)
    return out


def validate(field: dict, item: dict, passages: dict) -> dict:
    """Validate one provider item. Returns dict(ok, outcome, value, errors, warnings, evidence, counter, options,
    selections, reason_codes, rejected_citations).

    outcome: 'valid' | 'partially_valid' | 'invalid'. For MULTI-SELECT values (categorical multi, or several open-list
    values) every selected code is validated on its own: a code is kept when it is a codebook code (categorical) and
    has at least one valid citation marked 'supports' — evidence id actually supplied, quotation found verbatim. No
    redundant top-level evidence is required when each kept code has its own; a code that fails is REJECTED and
    reported while the supported codes are kept ('partially_valid', which always goes to human review). Whether a
    passage substantively supports a code cannot be judged mechanically; that stays with the human reviewer.
    Structural problems are 'invalid' with reason 'malformed_output' — never 'insufficient evidence'."""
    errors, warnings = [], []
    raw_value = item.get("value")
    if isinstance(raw_value, list):  # the Claude prompt allows a JSON list of codes for multi-select variables
        if not all(isinstance(x, (str, int, float)) for x in raw_value):
            return _malformed("value list contains non-text entries")
        value = ", ".join(str(x).strip() for x in raw_value if str(x).strip())
    elif raw_value is None:
        value = ""
    elif isinstance(raw_value, (str, int, float)):
        value = str(raw_value).strip()
    else:
        return _malformed("value is not text or a list of codes")
    ev_raw, opts_raw = item.get("evidence"), item.get("options")
    ev_raw = [] if ev_raw is None else ev_raw
    opts_raw = [] if opts_raw is None else opts_raw
    if not isinstance(ev_raw, list) or not all(isinstance(e, dict) for e in ev_raw):
        return _malformed("evidence is not a list of citations")
    if not isinstance(opts_raw, list) or not all(isinstance(o, dict) for o in opts_raw):
        return _malformed("options is not a list of {code, evidence} entries")
    for o in opts_raw:
        oe = o.get("evidence")
        if oe is not None and (not isinstance(oe, list) or not all(isinstance(e, dict) for e in oe)):
            return _malformed(f"evidence for option {o.get('code')} is not a list of citations")
    if value.lower() in ("null", "none", "n/a", "blank", "unknown", ""):
        if value and value.lower() in ("n/a", "unknown"):
            warnings.append(f"model wrote '{value}' — treated as blank (not a codebook code)")
        value = ""
    sup_raw = [e for e in ev_raw if e.get("stance", "supports") == "supports"]
    top_good, top_bad = _check(sup_raw, passages, "value")
    counter, ctr_bad = _check([e for e in ev_raw if e.get("stance") in ("contradicts", "alternative")], passages,
                              "counter-evidence")
    warnings.extend(m for _, m in ctr_bad)
    base = {"warnings": warnings, "counter": counter, "selections": [], "rejected_citations": []}

    def finish(ok, outcome, val, errs, reasons, evidence, options=None, selections=None, rejected_citations=None):
        return {**base, "ok": ok, "outcome": outcome, "value": val, "errors": errs, "evidence": evidence,
                "options": options or [], "selections": selections or [], "reason_codes": sorted(set(reasons)),
                "rejected_citations": rejected_citations or []}

    if field.get("rule_missing"):
        if value:
            return finish(False, "invalid", "", ["no codebook rule for this field — values cannot be suggested"],
                          ["rule_missing"], top_good)
        return finish(True, "valid", "", [], [], top_good)
    t = field["type"]
    if not value:
        listed = [o.get("code") for o in opts_raw if str(o.get("code") or "").strip()]
        if listed and t in ("categorical", "open_list"):
            # codes in "options" but none in "value": a structural mismatch, never "insufficient evidence"
            return finish(False, "invalid", "", [f"malformed output: value is blank but options list {', '.join(map(str, listed))}"],
                          ["malformed_output"], top_good)
        return finish(True, "valid", "", [], [], top_good)

    missing = set(field.get("missing_codes", []))
    parts = split_values(value) if t in ("categorical", "open_list") else [value]
    multi_select = (t == "categorical" and field.get("multi")) or (t == "open_list" and len(parts) > 1)

    if any(p in missing for p in parts):
        if len(parts) > 1:
            return finish(False, "invalid", "", ["special missing value mixed with other values"],
                          ["special_missing_mixed"], top_good)
        warnings.append(f"special missing value {value} used — allowed for this variable only when sources indicate the "
                        f"information is unknown/not applicable; confirm")
        errs = [m for _, m in top_bad]
        sr = _support_reason(top_good)
        if sr:
            errs.append(f"value: {sr[1]}")
        reasons = [c for c, _ in top_bad] + ([sr[0]] if sr else [])
        return finish(not errs, "valid" if not errs else "invalid", value, errs, reasons, top_good)

    if t == "categorical" and not field.get("multi") and len(parts) > 1:
        return finish(False, "invalid", "", ["several codes given for a single-select variable"],
                      ["single_select_multiple_codes"], top_good)
    if t in ("categorical", "open_list") and len({p.upper() for p in parts}) != len(parts):
        return finish(False, "invalid", "", ["duplicate codes"], ["duplicate_codes"], top_good)

    if multi_select:
        allowed = {c["code"].upper(): c["code"] for c in field.get("codes", [])}
        listed = set(allowed) | {o.split("(")[0].strip().upper() for o in field.get("open_options", [])}
        opt_map = {}
        for o in opts_raw:
            opt_map.setdefault(str(o.get("code", "")).strip().upper(), o)
        top_supports = any(g["stance"] == "supports" for g in top_good)
        selections, kept, errs, reasons, options_out, all_ev = [], [], [], [], [], list(top_good)
        for p in parts:
            code = allowed.get(p.upper(), p) if t == "categorical" else p
            sel = {"code": code, "outcome": "valid", "reasons": [], "evidence": []}
            if t == "categorical" and p.upper() not in allowed:
                sel.update(outcome="rejected", reasons=["invalid_code"])
                errs.append(f"code '{p}' is not defined for this variable in the codebook")
            else:
                if t == "open_list" and p.split("(")[0].strip().upper() not in listed:
                    warnings.append(f"'{p}' is not one of the codebook's listed examples (list is open) — confirm wording")
                o = opt_map.get(p.upper())
                if o is not None:
                    good, bad = _check(o.get("evidence") or [], passages, f"option {code}")
                    sr = _support_reason(good)
                    sel["evidence"] = [g for g in good if g["stance"] == "supports"]
                    if bad:
                        sel["reasons"] += [c for c, _ in bad]
                        sel["dropped_citations"] = [m for _, m in bad]
                    if sr:
                        sel.update(outcome="rejected")
                        sel["reasons"].append(sr[0])
                        errs += [m for _, m in bad] + [f"option {code}: {sr[1]}"]
                    elif bad:  # kept on its valid citations; the failed citations are reported
                        errs += [m for _, m in bad]
                elif len(parts) == 1 and top_supports:
                    sel["evidence"] = [g for g in top_good if g["stance"] == "supports"]
                elif t == "open_list" and top_supports:
                    sel["evidence"] = [g for g in top_good if g["stance"] == "supports"]
                    warnings.append(f"option '{p}': no option-specific evidence; supported by the value's evidence")
                else:
                    sel.update(outcome="rejected", reasons=["no_supporting_evidence"])
                    errs.append(f"option {code}: no option-specific evidence given")
            if sel["outcome"] == "valid":
                kept.append(code)
                all_ev += sel["evidence"]
                options_out.append({"code": code, "evidence": sel["evidence"]})
            reasons += sel["reasons"]
            selections.append(sel)
        rejected_citations = [{"reason": c, "message": m} for c, m in top_bad]
        errs += [m for _, m in top_bad]
        reasons += [c for c, _ in top_bad]
        if not kept:
            return finish(False, "invalid", "", errs or ["no selection is supported"], reasons or ["no_supporting_evidence"],
                          _dedupe(all_ev), [], selections, rejected_citations)
        partial = len(kept) < len(parts) or bool(errs)
        return finish(True, "partially_valid" if partial else "valid", ", ".join(kept), errs, reasons,
                      _dedupe(all_ev), options_out, selections, rejected_citations)

    # single value (single-select categorical, single open-list value, numeric, date, text): unchanged rules
    errs = [m for _, m in top_bad]
    reasons = [c for c, _ in top_bad]
    sr = _support_reason(top_good)
    if sr:
        errs.append(f"value: {sr[1]}")
        reasons.append(sr[0])
    options_out = []
    if t == "categorical":
        allowed = {c["code"].upper(): c["code"] for c in field["codes"]}
        p = parts[0]
        if p.upper() not in allowed:
            errs.append(f"code '{p}' is not defined for this variable in the codebook")
            reasons.append("invalid_code")
        o = next((o for o in opts_raw if str(o.get("code", "")).strip().upper() == p.upper()), None)
        if o is not None:
            good, bad = _check(o.get("evidence") or [], passages, f"option {p}")
            errs += [m for _, m in bad]
            reasons += [c for c, _ in bad]
            osr = _support_reason(good)
            if osr:
                errs.append(f"option {p}: {osr[1]}")
                reasons.append(osr[0])
            options_out.append({"code": allowed.get(p.upper(), p), "evidence": good})
        else:
            options_out.append({"code": allowed.get(p.upper(), p), "evidence": top_good})
        value = allowed.get(p.upper(), p)
    elif t == "open_list":
        listed = {c["code"].upper() for c in field.get("codes", [])} | {o.split("(")[0].strip().upper() for o in field.get("open_options", [])}
        if value.split("(")[0].strip().upper() not in listed:
            warnings.append(f"'{value}' is not one of the codebook's listed examples (list is open) — confirm wording")
    elif t == "numeric":
        n = _num(value)
        if n is None:
            errs.append(f"'{value}' is not a number or numeric range")
            reasons.append("not_a_number")
        elif field.get("bands") and isinstance(n, float) and not (0 <= n <= 100):
            errs.append("percentage must be between 0 and 100")
            reasons.append("percentage_out_of_range")
    elif t == "date":
        try:
            date.fromisoformat(value)
        except ValueError:
            errs.append(f"'{value}' is not an ISO date (YYYY-MM-DD)")
            reasons.append("not_iso_date")
    elif t == "text":
        if len(value) > 4000:
            warnings.append("long text value")
    ok = not errs
    return finish(ok, "valid" if ok else "invalid", value, errs, reasons, top_good, options_out)
