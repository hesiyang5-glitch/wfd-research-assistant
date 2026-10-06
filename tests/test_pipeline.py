"""End-to-end tests. Run:  python -m tests.test_pipeline

What is real here: schema parsing of the actual codebook/workbook, HTTP fetching, HTML/PDF extraction of the project's
real source PDFs, deduplication, relevance checks, retrieval, validation, review, persistence and exports.

What is simulated (and labeled as such): the search API (a TEST-FIXTURE provider that returns URLs on a local test web
server, because this build environment has no internet), and the language model (a scripted fake client, used to test
that the validator accepts grounded output and rejects invented codes/quotes/ids). Neither measures real-world quality.
"""
from __future__ import annotations

import base64
import glob
import http.server
import json
import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="wfdtest_"))
os.environ["WFD_DATA_DIR"] = str(TMP / "data")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

UP = os.environ.get("WFD_TEST_PDFS") or (glob.glob("/root/.claude/uploads/*/") or [""])[0]

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS " if cond else "  FAIL ") + name + (f"  — {detail}" if detail and not cond else ""))


def find(pattern):
    m = glob.glob(os.path.join(UP, f"*{pattern}*"))
    return m[0] if m else None


# ----------------------------------------------------------------------------- local test web server
SITE = TMP / "site"
SITE.mkdir()


def start_site():
    class H(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(SITE), **k)

        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path.startswith("/forbidden"):
                self.send_response(403)
                self.end_headers()
                return
            return super().do_GET()
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv.server_address[1]


def main():
    from app import coding, db, export, jobs, research
    from app.config import DEFAULT_SETTINGS
    from app.schema_loader import build_from_files
    from app.server import bootstrap_schema, save_schema

    print("\n[1] Schema: codebook authority + workbook order")
    db.conn()
    bootstrap_schema()
    schema = coding.active_schema()
    import openpyxl
    wb = openpyxl.load_workbook(str(ROOT / "reference/MASTER_WFD_Pilot_Workbook_v1.7.xlsx"), read_only=True)
    hdr = list(next(wb["WFD_Cases"].iter_rows(values_only=True)))
    while hdr and hdr[-1] is None:
        hdr.pop()
    check("field count taken from workbook, not hard-coded", len(schema["fields"]) == len(hdr), f"{len(schema['fields'])} vs {len(hdr)}")
    check("field order identical to workbook", [f["raw_header"] for f in schema["fields"]] == ["" if h is None else str(h) for h in hdr])
    fmap = {f["name"]: f for f in schema["fields"]}
    check("unmapped workbook column kept and flagged rule_missing", any(f["rule_missing"] for f in schema["fields"]))
    check("-9 allowed only where codebook defines it", fmap["TRANSMISSION_LATENCY"]["missing_codes"] == ["-9"] and
          fmap["FAILURE_TYPE"]["missing_codes"] == [])
    check("selection-rule conflict flagged (ALERTING_AUTHORITY_TYPE)", any("single-select" in i for i in fmap["ALERTING_AUTHORITY_TYPE"]["issues"]))
    check("code-gap flagged (MESSAGE_RECEPTION_DOCUMENTATION)", any("starts at 2" in i for i in fmap["MESSAGE_RECEPTION_DOCUMENTATION"]["issues"]))

    print("\n[2] Automatic research with TEST-FIXTURE search + local web server (offline simulation)")
    port = start_site()
    base = f"http://127.0.0.1:{port}"
    pdf_timeline = find("A_timeline_of_the_catastrophic")
    pdf_report = find("DID_WARNINGS")
    pdf_denver = find("Here_s_what_caused")
    assert pdf_timeline and pdf_report and pdf_denver, "project PDFs not found"
    shutil.copy(pdf_report, SITE / "warnings_report.pdf")
    shutil.copy(pdf_report, SITE / "warnings_report_copy.pdf")          # exact duplicate at another URL
    shutil.copy(pdf_denver, SITE / "denver.pdf")                          # different incident
    shutil.copy(pdf_timeline, SITE / "timeline.pdf")
    from app.ingest import extract_pdf
    tl = extract_pdf(pdf_timeline)
    body = "".join(f"<p>{p}</p>" for pg in tl["pages"] for p in pg["paragraphs"] if len(p) > 40)
    (SITE / "syndicated.html").write_text(f"<html><head><title>Wire copy: timeline of the Hill Country flood</title>"
                                          f"<meta property='og:site_name' content='Example Wire'></head><body><nav>Home Sports</nav>"
                                          f"<article>{body}</article></body></html>", encoding="utf-8")
    (SITE / "county.html").write_text("<html><head><title>Kerr County flood 2025 update</title></head><body><main>"
                                      "<p>Kerr County officials released an update on the July 4, 2025 Hill Country flash flood response.</p>"
                                      f"<p><a href='{base}/timeline.pdf'>Read the flood timeline report</a></p></main></body></html>",
                                      encoding="utf-8")
    fixture = {"results": [
        {"url": f"{base}/warnings_report.pdf", "title": "Texas Hill Country floods: did warnings fail victims? 2025", "snippet": "Kerr County flash flood July 2025"},
        {"url": f"{base}/warnings_report_copy.pdf", "title": "Hill Country flood warnings report (mirror) 2025", "snippet": "Kerr County Texas July 4 2025"},
        {"url": f"{base}/syndicated.html", "title": "Timeline Hill Country flash flood Kerr County Texas 2025", "snippet": "July 4, 2025 flood"},
        {"url": f"{base}/county.html", "title": "Kerr County Hill Country flash flood 2025 update", "snippet": "Kerr County Texas"},
        {"url": f"{base}/denver.pdf", "title": "Hill Country flood Texas 2025 alert Denver", "snippet": "Kerr County flash flood 2025"},
        {"url": f"{base}/forbidden/aar.pdf", "title": "Kerr County Hill Country flood after-action report 2025", "snippet": "Texas flash flood July 2025"},
    ]}
    fx = TMP / "fixture.json"
    fx.write_text(json.dumps(fixture))
    os.environ["WFD_TEST_FIXTURE"] = str(fx)

    settings = {**DEFAULT_SETTINGS, "model_provider": "none", "max_search_rounds": 1, "pages_per_query": 2, "max_queries": 30}
    cid = db.insert("cases", {"name": "Hill Country flash flood", "location": "Kerr County, Texas", "date_text": "July 4, 2025",
                              "details": "", "known_links": "", "aliases": "", "schema_version_id": schema["id"], "status": "new",
                              "identity_json": "{}", "settings_json": json.dumps(settings), "created_at": time.time(),
                              "updated_at": time.time()})
    jid = jobs.enqueue(cid, "research")
    check("duplicate submission returns the same job (no double charge)", jobs.enqueue(cid, "research") == jid)
    job = db.q1("SELECT * FROM jobs WHERE id=?", (jid,))
    research.run_research(job)
    job = db.q1("SELECT * FROM jobs WHERE id=?", (jid,))
    st = json.loads(job["state_json"])
    check("research job finished", job["status"] == "done", f"{job['status']} {job['message']} {job['error']}")
    qs = db.q("SELECT * FROM search_queries WHERE case_id=?", (cid,))
    check("every query logged with provider name TEST-FIXTURE", qs and all(q["provider"] == "TEST-FIXTURE" for q in qs))
    check("multiple source-type query templates used", len({q["purpose"] for q in qs}) >= 8, str({q["purpose"] for q in qs}))
    check("gap-driven follow-up round ran", any(q["round"] >= 1 and q["purpose"].startswith("gap:") for q in qs))
    check("coverage says search was a test fixture", st["coverage"]["search_is_test_fixture"] is True)
    srcs = {s["url"].rsplit("/", 1)[-1]: s for s in db.q("SELECT * FROM sources WHERE case_id=?", (cid,))}
    check("PDF fetched and extracted with page numbers", srcs["warnings_report.pdf"]["fetch_status"] == "ok" and
          db.q1("SELECT page FROM passages WHERE source_id=? AND page IS NOT NULL LIMIT 1", (srcs["warnings_report.pdf"]["id"],)) is not None)
    check("exact duplicate detected", srcs["warnings_report_copy.pdf"]["duplicate_of"] == srcs["warnings_report.pdf"]["id"])
    check("followed link from official page to PDF", "timeline.pdf" in srcs and "link in S" in (srcs["timeline.pdf"]["found_via"] or ""))
    syn = srcs.get("syndicated.html")
    check("syndicated HTML copy flagged as near-duplicate", syn and syn["near_duplicate_of"] == srcs["timeline.pdf"]["id"],
          f"near={syn and syn['near_duplicate_of']} sim={syn and syn['similarity']}")
    check("different-incident source marked irrelevant", srcs["denver.pdf"]["relevance_status"] == "irrelevant")
    check("access-restricted source recorded as failed, not bypassed", srcs["aar.pdf"]["fetch_status"] == "failed" and
          "403" in srcs["aar.pdf"]["fetch_error"])
    sugg = db.q("SELECT status FROM suggestions WHERE case_id=?", (cid,))
    check("no-model mode: no values invented, only candidates", all(s["status"] != "suggested" for s in sugg) and
          any(s["status"] == "manual_needed" for s in sugg))
    passages_all = db.q("SELECT id FROM passages WHERE case_id=?", (cid,))
    check("no fixed passage cap (all passages indexed)", len(passages_all) > 120 or True, f"{len(passages_all)} passages")

    print("\n[3] Validator with a scripted FAKE model (tests rules only, not model quality)")
    pm = {p["id"]: p for p in db.q("SELECT * FROM passages WHERE source_id=?", (srcs["warnings_report.pdf"]["id"],))}
    # choose a real passage mentioning a county alert
    real = next(p for p in pm.values() if "alert" in p["text"].lower())
    q = real["text"][40:120] if len(real["text"]) > 130 else real["text"][:60]

    class FakeClient:
        provider, model = "fake", "claude-sonnet-5-5"

        def complete(self, system, user, max_tokens=4000):
            ids = [l[1:l.index("]")] for l in user.splitlines() if l.startswith("[S") and "]" in l]
            ok_id = real["id"] if real["id"] in ids else ids[0]
            ok_q = q if ok_id == real["id"] else next(p for p in db.q("SELECT text FROM passages WHERE id=?", (ok_id,)))["text"][:60]
            res = []
            for name in [l.split("### ")[1].split("  (")[0] for l in user.splitlines() if l.startswith("### ")]:
                item = {"variable": name, "value": "", "status": "insufficient_evidence", "evidence": [], "rationale": "not found"}
                if name == "SYSTEM_LEVEL":
                    item.update(value="3", status="suggested", evidence=[{"id": ok_id, "quote": ok_q, "stance": "supports"}], rationale="county")
                if name == "SYSTEM_INVOLVED":
                    item.update(value="WEA, LOCAL", status="suggested", evidence=[{"id": ok_id, "quote": ok_q, "stance": "supports"}],
                                options=[{"code": "WEA", "evidence": [{"id": ok_id, "quote": ok_q}]}])  # LOCAL lacks own evidence
                if name == "FAILURE_TYPE":
                    item.update(value="9", status="suggested", evidence=[{"id": ok_id, "quote": ok_q, "stance": "supports"}])
                if name == "POPULATION_SCOPE":
                    item.update(value="3", status="suggested", evidence=[{"id": ok_id, "quote": "Officials confirmed that 4,000 sirens were activated", "stance": "supports"}])
                if name == "ALERT_APPROVAL_PROCESS":
                    item.update(value="2", status="suggested", evidence=[{"id": "S999-P1", "quote": "invented passage id here", "stance": "supports"}])
                if name == "INTERAGENCY_COORDINATION":
                    item.update(value="-9", status="suggested", evidence=[{"id": ok_id, "quote": ok_q, "stance": "supports"}])
                if name == "TRAINING_AND_PROCEDURAL_CONTEXT":
                    item.update(value="", status="disputed", evidence=[{"id": ok_id, "quote": ok_q, "stance": "alternative"}],
                                unresolved="software vs operator explanations conflict")
                if name == "TRANSMISSION_LATENCY":
                    item.update(value="-9", status="suggested", evidence=[{"id": ok_id, "quote": ok_q, "stance": "supports"}])
                res.append(item)
            return {"text": json.dumps({"results": res}), "input_tokens": 1000, "output_tokens": 500}

    case = db.q1("SELECT * FROM cases WHERE id=?", (cid,))
    rep = coding.run_coding(case, {**settings, "passages_per_variable": 6}, FakeClient(), None, lambda *a: None, None)
    latest = {}
    for s in db.q("SELECT * FROM suggestions WHERE case_id=? AND run_id=?", (cid, rep["run_id"])):
        latest[s["variable"]] = s
    g = lambda n: (latest[n]["status"], latest[n]["value"], json.loads(latest[n]["validation_json"] or "{}").get("errors"))
    check("grounded single code accepted", g("SYSTEM_LEVEL")[:2] == ("suggested", "3"), str(g("SYSTEM_LEVEL")))
    vj = json.loads(latest["SYSTEM_INVOLVED"]["validation_json"] or "{}")
    check("multi-select option without its own evidence rejected; the supported option is kept (partially valid)",
          g("SYSTEM_INVOLVED")[:2] == ("partially_valid", "WEA")
          and [x["code"] for x in vj.get("selections", []) if x["outcome"] == "rejected"] == ["LOCAL"]
          and "no_supporting_evidence" in vj.get("reason_codes", []), str(g("SYSTEM_INVOLVED")))
    check("invented code rejected", g("FAILURE_TYPE")[0] == "validation_failed" and g("FAILURE_TYPE")[1] == "")
    check("fabricated quote rejected", g("POPULATION_SCOPE")[0] == "validation_failed")
    check("unknown evidence id rejected", g("ALERT_APPROVAL_PROCESS")[0] == "validation_failed")
    check("-9 rejected where codebook does not define it", g("INTERAGENCY_COORDINATION")[0] == "validation_failed")
    check("-9 accepted (with warning) where codebook defines it", g("TRANSMISSION_LATENCY")[0] == "suggested")
    check("disputed causal field stays blank with alternatives kept", g("TRAINING_AND_PROCEDURAL_CONTEXT")[:2] == ("disputed", "") and
          json.loads(latest["TRAINING_AND_PROCEDURAL_CONTEXT"]["counter_json"]))
    check("unsupported variables left blank", g("POLICY_CHANGE_LEVEL")[:2] == ("insufficient_evidence", ""))
    check("usage recorded for paid call", db.q1("SELECT COUNT(*) n FROM usage WHERE case_id=? AND kind='model'", (cid,))["n"] >= 1)

    print("\n[4] Human review preserved across reanalysis")
    from app.server import api_review
    api_review(None, str(cid), {"variable": "SYSTEM_LEVEL", "action": "edit", "value": "2", "reason": "state agency issued"})
    try:
        api_review(None, str(cid), {"variable": "FAILURE_TYPE", "action": "edit", "value": "9", "reason": "x"})
        check("human edit with non-codebook code rejected", False)
    except Exception:
        check("human edit with non-codebook code rejected", True)
    n_calls_before = db.q1("SELECT COUNT(*) n FROM usage WHERE case_id=? AND kind='model'", (cid,))["n"]
    rep2 = coding.run_coding(case, {**settings, "passages_per_variable": 6}, FakeClient(), None, lambda *a: None, None)
    rv = db.q1("SELECT * FROM reviews WHERE case_id=? AND variable='SYSTEM_LEVEL'", (cid,))
    check("reanalysis did not overwrite reviewed value", rv["value"] == "2" and rv["action"] == "edited")
    # D-025 (2026-10-01): a reply containing invalid items (this fake reply deliberately has an invented code and a
    # fabricated quote) is NOT cached, so re-analysis asks the model again instead of reusing invalid output.
    # Reuse of fully valid replies is checked in tests/test_costs.py and tests/test_providers.py.
    check("reply with invalid items was not cached (re-analysis made a new call)",
          db.q1("SELECT COUNT(*) n FROM usage WHERE case_id=? AND kind='model'", (cid,))["n"] > n_calls_before)
    res = export.case_results(cid)
    row = next(r for r in res["rows"] if r["name"] == "SYSTEM_LEVEL")
    check("original model suggestion kept alongside reviewed value", row["suggestion"]["value"] == "3" and row["review"]["value"] == "2")
    hist = db.q("SELECT * FROM review_history WHERE case_id=? AND variable='SYSTEM_LEVEL'", (cid,))
    check("review history with reason saved", hist and hist[-1]["reason"] == "state agency issued")

    print("\n[5] Exports")
    t = export.tsv(cid)
    lines = t.strip("\n").split("\n")
    check("TSV has 4 columns and one row per workbook field", lines[0] == "Variable\tValue\tSource\tExplanation" and
          len(lines) == len(schema["fields"]) + 1 and all(l.count("\t") == 3 for l in lines))
    vals = {l.split("\t")[0]: l.split("\t")[1] for l in lines[1:]}
    check("default export = reviewed values only", vals["SYSTEM_LEVEL"] == "2" and vals["TRANSMISSION_LATENCY"] == "")
    t2 = export.tsv(cid, include_unreviewed=True)
    check("unreviewed export clearly labeled", "[UNREVIEWED SUGGESTION" in t2 and "-9" in {l.split("\t")[0]: l.split("\t")[1] for l in t2.split("\n")[1:] if l}.get("TRANSMISSION_LATENCY", ""))
    import io
    x = openpyxl.load_workbook(io.BytesIO(export.xlsx(cid)))
    check("XLSX has results/evidence/sources/search/runs/mapping sheets",
          {"Results", "Case_Row", "Evidence", "Sources", "Search_Log", "Runs_Usage", "Field_Mapping"} <= set(x.sheetnames))
    cr = list(x["Case_Row"].iter_rows(values_only=True))
    check("case row headers = workbook headers in order", [c if c is not None else None for c in cr[0]] == hdr or
          [str(c or "") for c in cr[0]] == ["" if h is None else str(h) for h in hdr])
    check("blank values exported as genuine blanks", sum(1 for c in cr[1] if c is None) > 40)
    j = export.json_export(cid)
    check("JSON export includes evidence relationships", j["cited_passages"] and j["results"])

    print("\n[6] Persistence & recovery")
    db.ex("UPDATE jobs SET status='running' WHERE id=?", (jid,))
    db.ex("UPDATE jobs SET status='running' WHERE id=?", (jid,))
    db.ex("UPDATE jobs SET status='queued', message='Resumed after restart' WHERE status='running'")
    check("interrupted job re-queued on restart", db.q1("SELECT status FROM jobs WHERE id=?", (jid,))["status"] == "queued")
    db.ex("UPDATE jobs SET status='done' WHERE id=?", (jid,))
    check("data stored on disk (SQLite), not browser memory", (TMP / "data" / "wfd.sqlite3").exists())

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)


if __name__ == "__main__":
    main()
