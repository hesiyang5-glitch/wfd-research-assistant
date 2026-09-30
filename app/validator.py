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


def check_evidence_list(items, passages: dict, errors: list, who: str, need_support=True) -> list[dict]:
    good = []
    for ev in items or []:
        pid = str(ev.get("id", "")).strip()
        quote = str(ev.get("quote", "")).strip()
        if pid not in passages:
            errors.append(f"{who}: evidence id '{pid}' was not among the passages provided")
            continue
        if not (QUOTE_MIN <= len(quote) <= QUOTE_MAX):
            errors.append(f"{who}: quote for {pid} has invalid length ({len(quote)} chars)")
            continue
        if not quote_in_passage(quote, passages[pid]["text"]):
            errors.append(f"{who}: quote not found verbatim in {pid}")
            continue
        p = passages[pid]
        good.append({"id": pid, "quote": quote, "stance": ev.get("stance", "supports"),
                     "source_id": p["source_id"], "page": p.get("page"), "para": p.get("para")})
    if need_support and not any(g["stance"] == "supports" for g in good):
        errors.append(f"{who}: no valid supporting evidence")
    return good


def validate(field: dict, item: dict, passages: dict) -> dict:
    """Returns dict(ok, value, errors, warnings, evidence, counter, options)."""
    errors, warnings = [], []
    raw_value = item.get("value")
    value = "" if raw_value is None else str(raw_value).strip()
    if value.lower() in ("null", "none", "n/a", "blank", "unknown", ""):
        if value and value.lower() in ("n/a", "unknown"):
            warnings.append(f"model wrote '{value}' — treated as blank (not a codebook code)")
        value = ""
    evidence = check_evidence_list([e for e in item.get("evidence", []) if e.get("stance", "supports") == "supports"],
                                   passages, errors, "value", need_support=bool(value))
    counter = check_evidence_list([e for e in item.get("evidence", []) if e.get("stance") in ("contradicts", "alternative")],
                                  passages, warnings, "counter-evidence", need_support=False)
    options_out = []

    if field.get("rule_missing"):
        if value:
            errors.append("no codebook rule for this field — values cannot be suggested")
        return {"ok": not value, "value": "", "errors": errors, "warnings": warnings, "evidence": evidence,
                "counter": counter, "options": []}
    if not value:
        return {"ok": True, "value": "", "errors": [], "warnings": warnings, "evidence": evidence, "counter": counter,
                "options": []}

    t = field["type"]
    missing = set(field.get("missing_codes", []))
    parts = split_values(value) if t in ("categorical", "open_list") else [value]

    if any(p in missing for p in parts):
        if len(parts) > 1:
            errors.append("special missing value mixed with other values")
        warnings.append(f"special missing value {value} used — allowed for this variable only when sources indicate the "
                        f"information is unknown/not applicable; confirm")
    elif t == "categorical":
        allowed = {c["code"].upper(): c["code"] for c in field["codes"]}
        for p in parts:
            if p.upper() not in allowed:
                errors.append(f"code '{p}' is not defined for this variable in the codebook")
        if not field.get("multi") and len(parts) > 1:
            errors.append("several codes given for a single-select variable")
        if len(set(p.upper() for p in parts)) != len(parts):
            errors.append("duplicate codes")
        # each selected option needs its own supporting evidence
        opt_map = {str(o.get("code", "")).strip().upper(): o for o in item.get("options", [])}
        for p in parts:
            o = opt_map.get(p.upper())
            if len(parts) == 1 and not o:
                options_out.append({"code": allowed.get(p.upper(), p), "evidence": evidence})
                continue
            if not o:
                errors.append(f"option {p}: no option-specific evidence given")
                continue
            ev = check_evidence_list(o.get("evidence", []), passages, errors, f"option {p}")
            options_out.append({"code": allowed.get(p.upper(), p), "evidence": ev})
        value = ", ".join(allowed.get(p.upper(), p) for p in parts)
    elif t == "open_list":
        listed = {c["code"].upper() for c in field.get("codes", [])} | {o.split("(")[0].strip().upper() for o in field.get("open_options", [])}
        for p in parts:
            if p.split("(")[0].strip().upper() not in listed:
                warnings.append(f"'{p}' is not one of the codebook's listed examples (list is open) — confirm wording")
        opt_map = {str(o.get("code", "")).strip().upper(): o for o in item.get("options", [])}
        if len(parts) > 1:
            for p in parts:
                o = opt_map.get(p.upper())
                if o:
                    options_out.append({"code": p, "evidence": check_evidence_list(o.get("evidence", []), passages, errors, f"option {p}")})
                else:
                    warnings.append(f"option '{p}': no option-specific evidence")
    elif t == "numeric":
        n = _num(value)
        if n is None:
            errors.append(f"'{value}' is not a number or numeric range")
        elif field.get("bands") and isinstance(n, float) and not (0 <= n <= 100):
            errors.append("percentage must be between 0 and 100")
    elif t == "date":
        try:
            date.fromisoformat(value)
        except ValueError:
            errors.append(f"'{value}' is not an ISO date (YYYY-MM-DD)")
    elif t == "text":
        if len(value) > 4000:
            warnings.append("long text value")

    ok = not errors
    return {"ok": ok, "value": value, "errors": errors, "warnings": warnings, "evidence": evidence,
            "counter": counter, "options": options_out}
