"""Strict JSON Schema for one coding batch (OpenAI Structured Outputs), built from the active codebook entries.

- Every variable in the batch is a REQUIRED property, so a schema-valid reply cannot omit one.
- Categorical values are enums of the codebook's codes; a special missing value (e.g. -9) is included ONLY when that
  variable's codebook entry defines it. Single-select = one string (or "" for blank); multi-select = array of codes.
- Cited passage ids are an enum of exactly the passages sent in this batch.
- Property keys are sanitized (codebook names contain spaces, "/" and parentheses); the exact variable name is kept in
  a one-value `variable` enum inside each entry.
The schema narrows what the model can return; the server validator (app/validator.py) still checks every value,
quote and evidence id afterwards, exactly as for Claude.
"""
from __future__ import annotations

import hashlib
import json
import re

RESPONSE_SCHEMA_VERSION = "wfd-batch-v2"  # v2 (D-038): evidence_status, rule_unclear, alternatives, missing_evidence
EVIDENCE_STATUSES = ["SUPPORTED", "INFERRED", "AMBIGUOUS", "INSUFFICIENT", "CONFLICTING"]
STATUSES = ["suggested", "insufficient_evidence", "disputed", "rule_unclear"]  # v1 replies (read only)
STANCES = ["supports", "contradicts", "alternative"]


def prop_key(i: int, name: str) -> str:
    return f"v{i + 1:02d}_" + re.sub(r"[^A-Za-z0-9_]", "_", name)[:48]


def _codes(f: dict) -> list[str]:
    out = []
    for c in (f.get("codes") or []):
        if str(c["code"]) not in out:
            out.append(str(c["code"]))
    for m in (f.get("missing_codes") or []):
        if str(m) not in out:
            out.append(str(m))
    return out


def _value_schema(f: dict) -> dict:
    codes = _codes(f)
    if f["type"] == "categorical" and codes:
        if f.get("multi"):
            return {"type": "array", "items": {"type": "string", "enum": codes},
                    "description": "Selected codebook codes; empty array = blank (insufficient evidence)."}
        return {"type": "string", "enum": [""] + codes, "description": "One codebook code, or \"\" = blank."}
    desc = {"numeric": "A number or numeric range as text, or \"\" = blank.",
            "date": "ISO date YYYY-MM-DD, or \"\" = blank.",
            "open_list": "Value(s) separated by '; ', or \"\" = blank.",
            "text": "Text grounded in the cited passages, or \"\" = blank."}.get(f["type"], "Value, or \"\" = blank.")
    if f.get("missing_codes"):
        desc += f" Special missing value(s) defined for this variable: {', '.join(f['missing_codes'])}."
    return {"type": "string", "description": desc}


def build_batch_schema(fields: list[dict], passage_ids: list[str]) -> dict:
    ev_ref = {"$ref": "#/$defs/evidence"}
    props, keys = {}, []
    for i, f in enumerate(fields):
        k = prop_key(i, f["name"])
        keys.append(k)
        codes = _codes(f)
        opt_code = {"type": "string", "enum": codes} if (f["type"] == "categorical" and codes) else {"type": "string"}
        props[k] = {
            "type": "object", "additionalProperties": False,
            "description": f"Coding of variable {f['name']}",
            "required": ["variable", "value", "evidence_status", "rule_unclear", "evidence", "options",
                         "alternatives", "missing_evidence", "rationale", "unresolved"],
            "properties": {
                "variable": {"type": "string", "enum": [f["name"]]},
                "value": _value_schema(f),
                "evidence_status": {"type": "string", "enum": EVIDENCE_STATUSES},
                "rule_unclear": {"type": "boolean"},
                "evidence": {"type": "array", "items": ev_ref},
                "options": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False, "required": ["code", "evidence"],
                    "properties": {"code": opt_code, "evidence": {"type": "array", "items": ev_ref}}}},
                "alternatives": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False, "required": ["value", "evidence"],
                    "properties": {"value": opt_code if (f["type"] == "categorical" and codes) else {"type": "string"},
                                   "evidence": {"type": "array", "items": ev_ref}}}},
                "missing_evidence": {"type": "string"},
                "rationale": {"type": "string"},
                "unresolved": {"type": "string"},
            },
        }
    return {
        "type": "object", "additionalProperties": False, "required": ["results"],
        "properties": {"results": {"type": "object", "additionalProperties": False, "required": keys,
                                   "properties": props}},
        "$defs": {"evidence": {
            "type": "object", "additionalProperties": False, "required": ["id", "quote", "stance"],
            "properties": {"id": {"type": "string", "enum": list(passage_ids) or ["NONE"]},
                           "quote": {"type": "string", "description": "Verbatim text copied from that passage."},
                           "stance": {"type": "string", "enum": STANCES}}}},
    }


def schema_hash(schema: dict) -> str:
    return hashlib.sha256(json.dumps(schema, sort_keys=True).encode()).hexdigest()[:16]


class SchemaViolation(ValueError):
    pass


def normalize_structured(data, fields: list[dict]) -> list[dict]:
    """Convert a schema-shaped reply into the provider-neutral item list the validator expects.
    Raises SchemaViolation when the reply does not have the required shape (it is then not cached)."""
    if not isinstance(data, dict) or not isinstance(data.get("results"), dict):
        raise SchemaViolation("reply does not match the response schema (missing 'results' object)")
    res = data["results"]
    out = []
    for i, f in enumerate(fields):
        item = res.get(prop_key(i, f["name"]))
        if not isinstance(item, dict):
            raise SchemaViolation(f"reply does not match the response schema (no entry for {f['name']})")
        if item.get("variable") != f["name"]:
            raise SchemaViolation(f"reply entry for {f['name']} names a different variable")
        es = item.get("evidence_status")
        if es is not None and es not in EVIDENCE_STATUSES:
            raise SchemaViolation(f"invalid evidence_status for {f['name']}")
        if es is None and item.get("status") not in STATUSES:  # a v1-shaped reply must at least carry a v1 status
            raise SchemaViolation(f"invalid status for {f['name']}")
        v = item.get("value")
        if isinstance(v, list):
            v = ", ".join(str(x) for x in v)
        elif v is None:
            v = ""
        elif not isinstance(v, str):
            raise SchemaViolation(f"invalid value type for {f['name']}")
        for ev in (item.get("evidence") or []):
            if not isinstance(ev, dict) or ev.get("stance") not in STANCES:
                raise SchemaViolation(f"invalid evidence entry for {f['name']}")
        alts = []
        for a in (item.get("alternatives") or []):
            if isinstance(a, dict) and isinstance(a.get("value"), list):
                a = {**a, "value": ", ".join(str(x) for x in a["value"])}
            alts.append(a)
        row = {"variable": f["name"], "value": v, "evidence": item.get("evidence") or [],
               "options": item.get("options") or [], "alternatives": alts,
               "missing_evidence": item.get("missing_evidence") or "", "rule_unclear": item.get("rule_unclear") is True,
               "rationale": item.get("rationale") or "", "unresolved": item.get("unresolved") or ""}
        if es is not None:
            row["evidence_status"] = es
        if item.get("status") in STATUSES:
            row["status"] = item["status"]
        out.append(row)
    return out
