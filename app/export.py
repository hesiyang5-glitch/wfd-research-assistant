"""Result assembly (shared by the API and exports) and export writers."""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import re
import time

from . import db
from .coding import schema_for_case

VALUE_STATUSES = ("suggested", "derived", "admin_generated", "rule_unclear")
INSUFFICIENT = ("insufficient_evidence", "manual_needed", "not_coded_budget", "model_error", "validation_failed")


def _load(js, default):
    try:
        return json.loads(js) if js else default
    except Exception:
        return default


def review_category(f: dict, sugg: dict | None, review: dict | None) -> str:
    if review and review["action"] in ("accepted", "edited", "cleared"):
        return "confirmed"
    if f.get("rule_missing") or (sugg and sugg["status"] == "rule_missing"):
        return "rule_missing"
    if sugg and (sugg["status"] == "disputed" or (sugg["status"] in VALUE_STATUSES and sugg.get("counter"))):
        return "disputed"
    if sugg and sugg["status"] in VALUE_STATUSES and sugg["value"]:
        return "pending"
    if review and review["action"] == "deferred":
        return "pending"
    if sugg and sugg["status"] == "analyst_note":
        return "pending"
    return "insufficient"


def case_results(case_id: int) -> dict:
    case = db.q1("SELECT * FROM cases WHERE id=?", (case_id,))
    schema = schema_for_case(case)
    sugg_rows = db.q("SELECT * FROM suggestions WHERE case_id=? ORDER BY id", (case_id,))
    latest, previous = {}, {}
    for s in sugg_rows:
        s["evidence"] = _load(s.pop("evidence_json"), [])
        s["counter"] = _load(s.pop("counter_json"), [])
        s["validation"] = _load(s.pop("validation_json"), {})
        s.pop("raw_json", None)
        if s["variable"] in latest:
            previous[s["variable"]] = latest[s["variable"]]
        latest[s["variable"]] = s
    reviews = {r["variable"]: r for r in db.q("SELECT * FROM reviews WHERE case_id=?", (case_id,))}
    srcs = {s["id"]: s for s in db.q("SELECT id,title,url,final_url,source_type,excluded,relevance_status FROM sources WHERE case_id=?", (case_id,))}
    rows = []
    for f in schema["fields"]:
        s = latest.get(f["name"])
        p = previous.get(f["name"])
        r = reviews.get(f["name"])
        changed = bool(s and p and (s["value"] != p["value"] or s["status"] != p["status"]))
        rows.append({
            "name": f["name"], "position": f["position"], "raw_header": f["raw_header"], "type": f["type"], "multi": f.get("multi"),
            "field_class": f.get("field_class"), "section": f.get("section"), "definition": f.get("definition"),
            "codes": f.get("codes", []), "open_options": f.get("open_options", []), "missing_codes": f.get("missing_codes", []),
            "codebook_ref": f.get("codebook_ref"), "issues": f.get("issues", []), "rule_missing": f.get("rule_missing"),
            "suggestion": s, "previous": p if changed else None, "review": r,
            "category": review_category(f, s, r),
        })
    return {"case": case, "schema_label": schema.get("label"), "schema_id": schema.get("id"), "rows": rows, "sources": srcs}


def export_value(row: dict, include_unreviewed: bool) -> tuple[str, str]:
    r = row["review"]
    if r and r["action"] in ("accepted", "edited", "cleared"):
        return r["value"] or "", "reviewed"
    s = row["suggestion"]
    if include_unreviewed and s and s["status"] in VALUE_STATUSES and s["value"]:
        return s["value"], "UNREVIEWED"
    return "", "blank"


def source_cell(row: dict, srcs: dict) -> str:
    s = row["suggestion"]
    if not s:
        return ""
    out = []
    for ev in s.get("evidence", []):
        if ev.get("stance") not in ("supports", None):
            continue
        src = srcs.get(ev.get("source_id"), {})
        loc = f"p.{ev['page']}" if ev.get("page") else (f"para {ev['para']}" if ev.get("para") else "")
        out.append(f"{ev['id']} {loc} {src.get('final_url') or src.get('url') or src.get('title') or ''}".strip())
    if not out and s.get("basis") in ("derived", "generated"):
        return f"({s['basis']})"
    return "; ".join(dict.fromkeys(out))


def explanation_cell(row: dict, origin: str) -> str:
    s, r = row["suggestion"], row["review"]
    parts = []
    if origin == "UNREVIEWED":
        parts.append("[UNREVIEWED SUGGESTION — not confirmed by a human coder]")
    if r and r["action"] in ("edited", "cleared") and r.get("reason"):
        parts.append(f"Reviewer: {r['reason']}")
    if s:
        if s.get("rationale"):
            parts.append(s["rationale"])
        if s.get("unresolved"):
            parts.append(f"Unresolved: {s['unresolved']}")
        if origin == "blank" and s["status"] not in VALUE_STATUSES:
            parts.append(f"(status: {s['status']})")
    return " ".join(parts)


def tsv(case_id: int, include_unreviewed=False) -> str:
    res = case_results(case_id)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter="\t", lineterminator="\n")
    w.writerow(["Variable", "Value", "Source", "Explanation"])
    for row in res["rows"]:
        v, origin = export_value(row, include_unreviewed)
        w.writerow([row["name"], v, source_cell(row, res["sources"]) if v else "", explanation_cell(row, origin)])
    return buf.getvalue()


def _cell_value(v: str, ftype: str):
    if v == "":
        return None
    if ftype == "date" and re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        return dt.date.fromisoformat(v)
    if re.fullmatch(r"-?\d+", v) and ftype in ("numeric", "categorical"):
        return int(v)
    if re.fullmatch(r"-?\d+\.\d+", v) and ftype == "numeric":
        return float(v)
    return v  # multi-codes like "1, 3" stay text, so Excel cannot turn them into dates


def xlsx(case_id: int, include_unreviewed=False) -> bytes:
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill
    res = case_results(case_id)
    case = res["case"]
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "README"
    info = [["WFD Coding Assistant export"], ["Case", case["name"]], ["Location", case["location"]], ["Date", case["date_text"]],
            ["Schema version", res["schema_label"]], ["Exported at", dt.datetime.now().isoformat(timespec="seconds")],
            ["Values exported", "Reviewed values + UNREVIEWED model suggestions (marked)" if include_unreviewed else
             "Human-reviewed values only; everything else left blank"],
            ["Note", "Blank cells are genuine blanks (not established or not reviewed). The original workbook was not modified."]]
    for r in info:
        ws.append(r)
    ws["A1"].font = Font(bold=True, size=13)

    wr = wb.create_sheet("Results")
    wr.append(["Variable", "Value", "Source", "Explanation", "Review status", "Value origin", "Suggestion status"])
    yellow = PatternFill("solid", fgColor="FFF2CC")
    for row in res["rows"]:
        v, origin = export_value(row, include_unreviewed)
        wr.append([row["name"], v, source_cell(row, res["sources"]) if v else "", explanation_cell(row, origin), row["category"],
                   origin, (row["suggestion"] or {}).get("status", "")])
        if origin == "UNREVIEWED":
            for c in wr[wr.max_row]:
                c.fill = yellow

    wc = wb.create_sheet("Case_Row")
    wc.append([row["raw_header"] for row in res["rows"]])
    wc.append([_cell_value(export_value(row, include_unreviewed)[0], row["type"]) for row in res["rows"]])
    for c in wc[2]:
        if isinstance(c.value, dt.date):
            c.number_format = "yyyy-mm-dd"

    we = wb.create_sheet("Evidence")
    we.append(["Variable", "Stance", "Passage", "Source", "Page", "Paragraph", "Quote", "URL", "Source type"])
    for row in res["rows"]:
        s = row["suggestion"]
        if not s:
            continue
        for ev in s.get("evidence", []) + s.get("counter", []):
            src = res["sources"].get(ev.get("source_id"), {})
            we.append([row["name"], ev.get("stance"), ev.get("id"), f"S{ev.get('source_id')}", ev.get("page"), ev.get("para"),
                       ev.get("quote"), src.get("final_url") or src.get("url"), src.get("source_type")])

    wsr = wb.create_sheet("Sources")
    cols = ["id", "title", "publisher", "published_date", "source_type", "origin", "found_via", "url", "final_url", "fetch_status",
            "fetch_error", "relevance_status", "relevance_reason", "duplicate_of", "near_duplicate_of", "similarity", "excluded",
            "exclude_reason", "ocr_status", "n_pages", "n_passages", "text_chars", "content_hash", "retrieved_at"]
    wsr.append(cols)
    for s in db.q("SELECT * FROM sources WHERE case_id=? ORDER BY id", (case_id,)):
        s["retrieved_at"] = dt.datetime.fromtimestamp(s["retrieved_at"]).isoformat(timespec="seconds") if s.get("retrieved_at") else ""
        wsr.append([s.get(c) for c in cols])

    wq = wb.create_sheet("Search_Log")
    wq.append(["Round", "Purpose", "Query", "Page", "Provider", "Status", "Results", "Error", "Target variables", "Time"])
    for q in db.q("SELECT * FROM search_queries WHERE case_id=? ORDER BY id", (case_id,)):
        wq.append([q["round"], q["purpose"], q["query"], q["page"], q["provider"], q["status"], q["result_count"], q["error"],
                   q["target_vars"], dt.datetime.fromtimestamp(q["created_at"]).isoformat(timespec="seconds")])

    wu = wb.create_sheet("Runs_Usage")
    wu.append(["Kind", "Provider", "Model", "Input tokens", "Output tokens", "Units", "Cost USD", "Estimated?", "Note", "Time"])
    for u in db.q("SELECT * FROM usage WHERE case_id=? ORDER BY id", (case_id,)):
        wu.append([u["kind"], u["provider"], u["model"], u["input_tokens"], u["output_tokens"], u["units"], u["cost_usd"],
                   "yes" if u["estimated"] else "no", u["note"], dt.datetime.fromtimestamp(u["at"]).isoformat(timespec="seconds")])
    wu.append([])
    wu.append(["Run id", "Mode", "Model", "Schema version", "Created"])
    for r in db.q("SELECT * FROM runs WHERE case_id=? ORDER BY id", (case_id,)):
        wu.append([r["id"], r["mode"], r["model"], r["schema_version_id"], dt.datetime.fromtimestamp(r["created_at"]).isoformat(timespec="seconds")])

    wm = wb.create_sheet("Field_Mapping")
    wm.append(["Position", "Workbook header", "Codebook variable", "Type", "Multi", "Class", "Codebook reference", "Issues"])
    for row in res["rows"]:
        wm.append([row["position"], row["raw_header"], row["name"] if not row["rule_missing"] else "(no rule)", row["type"],
                   "yes" if row["multi"] else "no", row["field_class"], row["codebook_ref"], " | ".join(row["issues"])])
    for sh in wb.worksheets:
        for c in sh[1]:
            c.font = Font(bold=True)
        for col in sh.columns:
            letter = col[0].column_letter
            sh.column_dimensions[letter].width = 18 if sh.title == "Case_Row" else min(70, max(10, max(len(str(c.value or ""))
                                                                                                      for c in col[:50]) + 2))
        if sh.title in ("Results", "Evidence"):
            for r_ in sh.iter_rows(min_row=2):
                for c in r_:
                    c.alignment = Alignment(wrap_text=True, vertical="top")
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def json_export(case_id: int, include_unreviewed=False) -> dict:
    res = case_results(case_id)
    cited = set()
    for row in res["rows"]:
        s = row["suggestion"]
        if s:
            for ev in s.get("evidence", []) + s.get("counter", []):
                cited.add(ev.get("id"))
    passages = [p for p in db.q("SELECT * FROM passages WHERE case_id=?", (case_id,)) if p["id"] in cited]
    out_rows = []
    for row in res["rows"]:
        v, origin = export_value(row, include_unreviewed)
        out_rows.append({**row, "export_value": v, "export_origin": origin})
    return {
        "export": {"at": dt.datetime.now().isoformat(timespec="seconds"), "include_unreviewed": include_unreviewed,
                   "schema_version": res["schema_label"], "tool": "WFD Coding Assistant"},
        "case": res["case"], "results": out_rows,
        "review_history": db.q("SELECT * FROM review_history WHERE case_id=? ORDER BY id", (case_id,)),
        "sources": db.q("SELECT * FROM sources WHERE case_id=? ORDER BY id", (case_id,)),
        "cited_passages": passages,
        "search_log": db.q("SELECT * FROM search_queries WHERE case_id=? ORDER BY id", (case_id,)),
        "usage": db.q("SELECT * FROM usage WHERE case_id=? ORDER BY id", (case_id,)),
        "runs": db.q("SELECT * FROM runs WHERE case_id=? ORDER BY id", (case_id,)),
    }
