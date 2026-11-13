"""Search only vs Search & analyze (DECISIONS D-045). Run:  python -m tests.test_search_only

Offline: TEST-FIXTURE search + a local web server with the Texas-flood PDFs; no model key; model coding replaced by a
counter so the test proves whether coding was STARTED, without any paid call. Checks:
  [1] API: run_mode stored; default for older clients is the full pipeline; invalid values refused; Search only needs
      no coding-provider choice
  [2] Search only: discovery, de-duplication, relevance screening, ranking, retrieval and passages happen; the
      codebook gap check, follow-up searches and coding do not; no model request is recorded; case status
      "sources_ready"; coverage says gaps were not checked
  [3] Sources export (Excel / CSV) works with no analysis: About / Sources / Search_Log sheets only, no coding values,
      type-priority order, excluded sources left out unless asked for
  [4] Continue to analysis later: Re-analyze starts coding on the sources already read, with no new search
  [5] Search & analyze: continues into the gap check and coding with no pause after retrieval (pause is opt-in)
  [6] Re-run uses the case's mode; the request can switch it; cases from before this change keep the full pipeline
  [7] Interface: default Search only, button labels follow the mode, model choice only in Search & analyze, the pause
      box is unticked, Progress offers Continue to analysis / View sources, Sources tab exports
"""
from __future__ import annotations

import glob
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="wfdso_"))
os.environ["WFD_DATA_DIR"] = str(TMP / "data")
for k in ("ANTHROPIC_API_KEY", "TAVILY_API_KEY", "BRAVE_API_KEY", "OPENAI_API_KEY", "OPENAI_BASE_URL", "WFD_PASSWORD"):
    os.environ.pop(k, None)
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
UP = os.environ.get("WFD_TEST_PDFS", "/mnt/user-data/uploads")
SITE = TMP / "site"
SITE.mkdir()

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS " if cond else "  FAIL ") + name + (f"  — {detail}" if detail and not cond else ""))


def main():
    import http.server
    import threading
    for pat, name in [("DID_WARNINGS", "report.pdf"), ("A_timeline_of_the_catastrophic", "timeline.pdf"), ("Here_s_what_caused", "denver.pdf")]:
        shutil.copy(glob.glob(os.path.join(UP, f"*{pat}*"))[0], SITE / name)

    class Site(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(SITE), **k)

        def log_message(self, *a):
            pass
    site = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Site)
    threading.Thread(target=site.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{site.server_address[1]}"
    fx = TMP / "fx.json"
    fx.write_text(json.dumps({"results": [
        {"url": f"{base}/report.pdf", "title": "Texas Hill Country floods: did warnings fail victims? 2025", "snippet": "Kerr County July 2025"},
        {"url": f"{base}/timeline.pdf", "title": "Timeline of the Hill Country flash flood, Kerr County Texas 2025", "snippet": "July 4 2025"},
        {"url": f"{base}/denver.pdf", "title": "Hill Country flood 2025 Kerr County alert", "snippet": "Texas 2025"}]}))
    os.environ["WFD_TEST_FIXTURE"] = str(fx)

    from app import db, research, server, jobs
    db.conn()
    server.bootstrap_schema()

    calls = {"coding": 0, "gaps": 0}
    real_gaps = research.stage_gaps

    def fake_coding(ctx):  # proves whether coding started; never calls a model
        calls["coding"] += 1

    def counting_gaps(ctx):
        calls["gaps"] += 1
        return real_gaps(ctx)
    research.stage_coding = fake_coding
    research.stage_gaps = counting_gaps

    class H:
        user = "curator1"

    def new(run_mode=None, **extra):
        body = {"name": "Hill Country flash flood", "location": "Kerr County, Texas", "date_text": "July 4, 2025",
                "settings": {"max_search_rounds": 1}, **extra}
        if run_mode is not None:
            body["run_mode"] = run_mode
        return server.api_new_case(H(), body)

    def run(jid):
        research.run_research(db.q1("SELECT * FROM jobs WHERE id=?", (jid,)))
        return db.q1("SELECT * FROM jobs WHERE id=?", (jid,))

    print("\n[1] API")
    r = new("search_only", mode="does_not_exist")
    st = json.loads(db.q1("SELECT settings_json FROM cases WHERE id=?", (r["id"],))["settings_json"])
    check("Search only stored on the case and the job", st["run_mode"] == "search_only" and json.loads(
        db.q1("SELECT params_json FROM jobs WHERE id=?", (r["job_id"],))["params_json"]).get("search_only") is True)
    check("Search only needs no coding-provider choice (an unknown mode is ignored)", r["mode"] is None, str(r))
    r_old = new(None, start=False)
    check("older clients without run_mode keep the full pipeline", json.loads(
        db.q1("SELECT settings_json FROM cases WHERE id=?", (r_old["id"],))["settings_json"])["run_mode"] == "search_analyze")
    try:
        new("analyze_everything")
        check("invalid run_mode refused", False)
    except server.ApiError as e:
        check("invalid run_mode refused (400)", e.status == 400)

    print("\n[2] Search only stops after retrieval")
    cid = r["id"]
    j = run(r["job_id"])
    st = json.loads(j["state_json"])
    srcs = db.q("SELECT * FROM sources WHERE case_id=?", (cid,))
    log = " ".join(x["message"] for x in db.q("SELECT message FROM job_log WHERE job_id=?", (j["id"],)))
    check("job finished at 'sources'", j["status"] == "done" and j["stage"] == "sources", f"{j['status']} {j['stage']} {j['message']}")
    check("case status is 'sources ready'", db.q1("SELECT status FROM cases WHERE id=?", (cid,))["status"] == "sources_ready")
    check("sources were retrieved and split into passages (not just links)",
          sum(1 for s in srcs if s["fetch_status"] == "ok") >= 2
          and db.q1("SELECT COUNT(*) n FROM passages WHERE case_id=?", (cid,))["n"] > 20)
    check("relevance screening ran (the Denver article is flagged)",
          any(s["relevance_status"] == "irrelevant" for s in srcs) and all(s["relevance_status"] for s in srcs if s["fetch_status"] == "ok"),
          str([(s["id"], s["relevance_status"]) for s in srcs]))
    check("source types assigned for ranking", all(s["source_type"] for s in srcs))
    check("no coding was started", calls["coding"] == 0)
    check("no codebook evidence-gap check was run", calls["gaps"] == 0 and "evidence gaps" not in log)
    check("no follow-up searches", db.q1("SELECT COUNT(*) n FROM search_queries WHERE case_id=? AND round>0", (cid,))["n"] == 0)
    check("no model request recorded", db.q1("SELECT COUNT(*) n FROM usage WHERE case_id=? AND kind<>'search'", (cid,))["n"] == 0)
    check("no suggestions were created", db.q1("SELECT COUNT(*) n FROM suggestions WHERE case_id=?", (cid,))["n"] == 0)
    check("coverage reports the gap check as not run", st["coverage"]["search_only"] and st["coverage"]["gaps_checked"] is False)
    check("run log says what was not run", "search only: stopping after retrieval" in log)

    print("\n[3] Sources export without analysis")
    from app import export
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(export.sources_xlsx(cid)))
    check("sheets: About, Sources, Search_Log (no coding sheets)", wb.sheetnames == ["About", "Sources", "Search_Log"], str(wb.sheetnames))
    rows = list(wb["Sources"].iter_rows(values_only=True))
    check("header row as documented", list(rows[0]) == export.SOURCE_COLUMNS)
    ranks = [research.TYPE_PRIORITY.get(next(s["source_type"] for s in srcs if f"S{s['id']}" == row[1]), 5) for row in rows[1:]]
    check("ordered by source-type priority", ranks == sorted(ranks), str(ranks))
    check("every source listed when none excluded", len(rows) - 1 == len(srcs))
    about = " ".join(str(c) for row in wb["About"].iter_rows(values_only=True) for c in row)
    check("About sheet says type priority is not proof of accuracy and there are no coding values",
          "not proof" in about and "no coding suggestions" in about)
    check("search log included", wb["Search_Log"].max_row - 1 == db.q1("SELECT COUNT(*) n FROM search_queries WHERE case_id=?", (cid,))["n"])
    ex_id = srcs[0]["id"]
    server.api_patch_source(H(), str(ex_id), {"excluded": True, "reason": "not needed for the country profile"})
    ids_default = [row[1] for row in list(openpyxl.load_workbook(io.BytesIO(export.sources_xlsx(cid)))["Sources"].iter_rows(values_only=True))[1:]]
    ids_all = [row[1] for row in list(openpyxl.load_workbook(io.BytesIO(export.sources_xlsx(cid, True)))["Sources"].iter_rows(values_only=True))[1:]]
    check("excluded source left out by default", f"S{ex_id}" not in ids_default and len(ids_default) == len(srcs) - 1)
    check("excluded source included (marked) when asked", f"S{ex_id}" in ids_all)
    csv_txt = export.sources_csv(cid)
    check("CSV export has the same columns and rows", csv_txt.splitlines()[0].startswith("Rank,Source ID,Title")
          and len(csv_txt.strip().splitlines()) == len(ids_default) + 1)
    server.api_patch_source(H(), str(ex_id), {"excluded": False})

    print("\n[4] Continue to analysis later")
    nq = db.q1("SELECT COUNT(*) n FROM search_queries WHERE case_id=?", (cid,))["n"]
    jr = run(server.api_recode(H(), str(cid), {})["job_id"])
    check("analysis started on the sources already read", calls["coding"] == 1, f"{calls} {jr['status']} {jr['message']}")
    check("no new search when continuing to analysis", db.q1("SELECT COUNT(*) n FROM search_queries WHERE case_id=?", (cid,))["n"] == nq)

    print("\n[5] Search & analyze runs straight through")
    calls.update(coding=0, gaps=0)
    ra = new("search_analyze")
    ja = run(ra["job_id"])
    sta = json.loads(ja["state_json"])
    check("gap check and coding ran automatically", calls["gaps"] >= 1 and calls["coding"] == 1, str(calls))
    check("no pause for confirmation after retrieval (pause is opt-in)", sta.get("awaiting") != "coding_approval"
          and json.loads(db.q1("SELECT settings_json FROM cases WHERE id=?", (ra["id"],))["settings_json"])["pause_before_coding"] is False)

    print("\n[6] Re-run")
    rr = server.api_research(H(), str(cid), {})
    check("re-run of a Search only case stays Search only", rr["run_mode"] == "search_only" and json.loads(
        db.q1("SELECT params_json FROM jobs WHERE id=?", (rr["job_id"],))["params_json"]).get("search_only") is True)
    db.update("jobs", rr["job_id"], {"status": "cancelled"})
    rr2 = server.api_research(H(), str(cid), {"run_mode": "search_analyze"})
    check("re-run can switch to Search & analyze and the case remembers it", rr2["run_mode"] == "search_analyze" and json.loads(
        db.q1("SELECT settings_json FROM cases WHERE id=?", (cid,))["settings_json"])["run_mode"] == "search_analyze"
          and "search_only" not in json.loads(db.q1("SELECT params_json FROM jobs WHERE id=?", (rr2["job_id"],))["params_json"]))
    db.update("jobs", rr2["job_id"], {"status": "cancelled"})
    legacy = db.insert("cases", {"name": "Legacy", "location": "", "date_text": "", "details": "", "known_links": "", "aliases": "",
                                 "schema_version_id": 1, "status": "review", "identity_json": "{}",
                                 "settings_json": json.dumps({"max_fetch": 60}), "created_at": time.time(), "updated_at": time.time()})
    rl = server.api_research(H(), str(legacy), {})
    check("a case made before this change re-runs the full pipeline", rl["run_mode"] == "search_analyze")
    db.update("jobs", rl["job_id"], {"status": "cancelled"})
    os.environ.pop("WFD_TEST_FIXTURE", None)

    print("\n[7] Interface")
    env = {**os.environ, "WFD_DATA_DIR": str(TMP / "ui"), "WFD_TEST_FIXTURE": str(fx), "WFD_PORT": "8793"}
    srv = subprocess.Popen([sys.executable, "-m", "app.server"], cwd=str(ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    ub = "http://127.0.0.1:8793"
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(ub + "/healthz", timeout=2)
                break
            except Exception:
                time.sleep(0.5)
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page(viewport={"width": 1400, "height": 950}, accept_downloads=True)
            errors = []
            pg.on("pageerror", lambda e: errors.append(str(e)))
            pg.goto(ub + "/")
            pg.evaluate("localStorage.setItem('wfd_lang','en')")
            pg.reload()
            pg.wait_for_selector("#runModeChoice")
            pg.wait_for_timeout(500)
            check("Search only is selected by default", pg.is_checked("input[name=rmode][value=search_only]"))
            check("start button reads 'Search sources'", pg.inner_text("#startBtn").strip() == "Search sources")
            choice = pg.inner_text("#runModeChoice")
            check("both options with their descriptions", "Find and organize relevant sources without running coding analysis." in choice
                  and "Find relevant sources and generate coding suggestions for human review." in choice)
            check("model choice hidden in Search only", not pg.is_visible("#analyzeOpts"))
            check("estimate shows no coding-model cost", "Coding-model requests" in pg.inner_text("#estBox"))
            pg.screenshot(path=str(TMP / "home_search_only.png"))
            pg.check("input[name=rmode][value=search_analyze]")
            pg.wait_for_timeout(400)
            check("start button reads 'Search & analyze'", pg.inner_text("#startBtn").strip() == "Search & analyze")
            check("model options shown in Search & analyze", pg.is_visible("#analyzeOpts"))
            check("pause-after-research box is unticked by default",
                  (not pg.query_selector("#pauseChk")) or not pg.is_checked("#pauseChk"))
            pg.check("input[name=rmode][value=search_only]")
            pg.fill("#f_name", "Hill Country flash flood")
            pg.fill("#f_location", "Kerr County, Texas")
            pg.fill("#f_date", "July 4, 2025")
            pg.click("#startBtn")
            pg.wait_for_url("**/progress", timeout=10000)
            txt = ""
            for _ in range(90):
                txt = pg.inner_text("#tabBody")
                if "Sources ready" in txt and "Continue to analysis" in txt:
                    break
                pg.wait_for_timeout(1000)
            pg.screenshot(path=str(TMP / "progress_search_only.png"))
            check("Progress shows Sources ready with Continue to analysis and View sources",
                  "Continue to analysis" in txt and "View sources" in txt and "not checked (search only)" in txt, txt[:400])
            pg.click("text=View sources")
            pg.wait_for_selector("#srcExport")
            check("Sources tab offers the export", "Source list (Excel)" in pg.inner_text("#srcExport"))
            with pg.expect_download() as dl:
                pg.click("#srcXlsx button")
            path = TMP / "dl.xlsx"
            dl.value.save_as(str(path))
            import openpyxl
            check("Excel download is the sources workbook", openpyxl.load_workbook(path).sheetnames == ["About", "Sources", "Search_Log"])
            pg.screenshot(path=str(TMP / "sources_export.png"), full_page=False)
            check("no JavaScript errors", not errors, str(errors))
            b.close()
    finally:
        srv.terminate()
    print(f"\nscreenshots in {TMP}")
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED:", *FAIL, sep="\n  ")
        sys.exit(1)


if __name__ == "__main__":
    main()
