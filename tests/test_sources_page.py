"""Sources page layout and the reassessment flow in the browser (D-046, 2026-11-13). Run:  python3 -m tests.test_sources_page

Uses a COPY of the legacy fixture database with extra source rows and saved text written straight into the copy, fake
keys and a dead proxy, so nothing can leave the machine and nothing is billed. No search, retrieval or model call is
made (the page has no way to start one except the existing Analyze button, which is never clicked here). Checks:
  1  sources are shown in authority groups with counts; groups collapse and expand; Add sources is collapsible
  2  the summary separates case-wide counts from the selected run and from what is displayed; denominators explained
  3  filters change the view only: no write request, same stored rows, export link and note unchanged
  4  "Selected" and "Eligible for analysis" are shown separately
  5  rows not yet checked by the current rules say so instead of claiming "Document text available"
  6  Preview reassessment is a dry run (GET only); Cancel writes nothing; Apply sends exactly one POST with confirm
  7  after Apply: an error page shows "No usable document text" (red), needs review, not eligible; history is shown
  8  a human relevance correction is kept by a later reassessment and recorded with the reviewer
  9  Chinese labels; no JavaScript errors
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="wfdsrcpage_"))
FIXTURE = ROOT / "tests" / "fixtures" / "legacy_c57214a_marshall.sqlite3"
PORT = "18874"
FAILS: list[str] = []

AAR_TEXT = ("The Marshall Fire began on December 30, 2021 in Boulder County, Colorado. Wind gusts exceeded 100 mph and the "
            "wildfire spread east into Louisville and Superior. Evacuation orders were sent through the county alert system; "
            "many residents reported receiving no warning before the fire reached their neighborhoods. ") * 12
ERROR_TEXT = "Loading error. Please enable JavaScript and cookies to continue. Access denied."
TOURISM_TEXT = ("Boulder County offers hundreds of miles of hiking trails, scenic overlooks and family friendly picnic areas. "
                "Visit the farmers market downtown and enjoy local breweries and restaurants. ") * 8
# id, title, url, type, fetch_status, relevance, excluded, passages
EXTRA = [
    (2, "Marshall Fire After-Action Review", "https://www.bouldercounty.gov/marshall-fire-aar.pdf", "government", "ok", "relevant", 0, [AAR_TEXT]),
    (3, "News story (page did not load)", "https://news.example.com/marshall-fire-alerts", "media", "ok", "irrelevant", 0, [ERROR_TEXT]),
    (4, "Things to do in Boulder County", "https://visitboulder.example.org/things-to-do", "media", "ok", "relevant", 0, [TOURISM_TEXT]),
    (5, "Deselected news copy", "https://news2.example.com/marshall", "media", "ok", "relevant", 1, [AAR_TEXT[:900]]),
]


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond or not detail else f"  — {str(detail)[:400]}"))
    if not cond:
        FAILS.append(name)


def main():
    d = TMP / "d"; d.mkdir()
    shutil.copy(FIXTURE, d / "wfd.sqlite3")
    con = sqlite3.connect(d / "wfd.sqlite3")
    for sid, title, url, typ, st, rel, excl, paras in EXTRA:
        con.execute("INSERT INTO sources (id, case_id, url, title, source_type, origin, fetch_status, relevance_status, n_passages, excluded) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)", (sid, 1, url, title, typ, "search", st, rel, len(paras), excl))
        for i, t in enumerate(paras):
            con.execute("INSERT INTO passages (id, case_id, source_id, seq, page, para, text) VALUES (?,?,?,?,?,?,?)", (f"S{sid}-P{i+1}", 1, sid, i, None, i + 1, t))
    con.commit(); con.close()
    env = {**os.environ, "WFD_DATA_DIR": str(d), "WFD_PORT": PORT, "ANTHROPIC_API_KEY": "test-not-a-real-key",
           "OPENAI_API_KEY": "test-not-a-real-key", "TAVILY_API_KEY": "test-not-a-real-key",
           "HTTPS_PROXY": "http://127.0.0.1:9", "HTTP_PROXY": "http://127.0.0.1:9", "NO_PROXY": "127.0.0.1,localhost"}
    for k in ("WFD_PASSWORD", "OPENAI_BASE_URL", "WFD_TEST_FIXTURE"):
        env.pop(k, None)
    srv = subprocess.Popen([sys.executable, "-m", "app.server"], cwd=str(ROOT), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    time.sleep(3)
    U = f"http://127.0.0.1:{PORT}/"

    def stored():
        c = sqlite3.connect(d / "wfd.sqlite3")
        r = c.execute("SELECT id, source_type, relevance_status, excluded, content_status FROM sources ORDER BY id").fetchall(); c.close()
        return r

    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch()
            errors, writes, outside = [], [], []
            ctx = b.new_context(viewport={"width": 1400, "height": 1000})
            ctx.add_init_script("if (!localStorage.getItem('wfd_lang')) localStorage.setItem('wfd_lang','en')")
            pg = ctx.new_page()
            pg.on("pageerror", lambda e: errors.append(str(e)))
            pg.on("request", lambda r: (writes.append(f"{r.method} {r.url.split('/api/')[-1]}") if r.method != "GET" else None,
                                        outside.append(r.url) if not r.url.startswith(U) else None))
            pg.on("dialog", lambda dl: dl.dismiss())
            pg.goto(U + "#/case/1/sources"); pg.wait_for_selector("#srcTable")
            pg.wait_for_timeout(400)

            print("\n[1] Groups")
            groups = pg.eval_on_selector_all("#srcTable tbody.src-group", "els => els.map(e => [e.dataset.group, e.querySelectorAll('tr[data-sid]').length])")
            check("1 groups appear in authority order with their sources", groups == [["aar", 1], ["gov", 1], ["legis", 0], ["acad", 0], ["media", 3], ["other", 0]], groups)
            check("1b each group header shows a count", "3" in pg.inner_text("tbody[data-group='media'] tr.grp-h"), pg.inner_text("tbody[data-group='media'] tr.grp-h"))
            pg.click("[data-grp='media']"); pg.wait_for_timeout(400)
            check("1c a group collapses (rows hidden, header stays)", pg.locator("tbody[data-group='media'] tr[data-sid]").count() == 0 and pg.locator("tbody[data-group='media'] tr.grp-h").count() == 1)
            pg.click("[data-grp='media']"); pg.wait_for_timeout(400)
            check("1d and expands again", pg.locator("tbody[data-group='media'] tr[data-sid]").count() == 3)
            check("1e Add sources is a collapsed section", pg.eval_on_selector("#srcAdd", "e => e.tagName === 'DETAILS' && !e.open"))
            check("1f collapsing sent nothing", not writes, writes)

            print("\n[2] Summary scopes")
            head = pg.inner_text("#srcCounts")
            check("2 case-wide and selected-run columns are separate", "Case-wide (all runs)" in head and "Selected run" in head, head[:300])
            check("2b denominators are explained (not one funnel)", "not one funnel" in head and "Shown now" in head, head[-500:])
            check("2c the header states the count scope", "all search runs of this case" in pg.inner_text("#srcHead"))

            print("\n[3] Filters are view only")
            before_rows, before_href, before_note = stored(), pg.get_attribute("#srcXlsx", "href"), pg.inner_text("#srcExpNote")
            pg.select_option("#fRel", "irrelevant"); pg.wait_for_timeout(400)
            ids = pg.eval_on_selector_all("#srcTable tr[data-sid]", "els => els.map(e => +e.dataset.sid)")
            check("3 relevance filter shows only matching sources", ids == [3], ids)
            check("3b the summary reports what is displayed", "Shown now: 1" in pg.inner_text("#srcCounts"), pg.inner_text("#srcCounts")[-300:])
            pg.fill("#fQ", "boulder"); pg.press("#fQ", "Enter"); pg.wait_for_timeout(400)
            check("3c keyword + relevance together can show none (explained)", "No sources match the filters" in pg.inner_text("#srcTable"))
            pg.click("#fClear"); pg.wait_for_timeout(400)
            check("3d clearing filters brings all back", pg.locator("#srcTable tr[data-sid]").count() == 5)
            check("3e filters sent no write request", not writes, writes)
            check("3f stored rows, export link and export note are unchanged", stored() == before_rows and pg.get_attribute("#srcXlsx", "href") == before_href
                  and pg.inner_text("#srcExpNote") == before_note and "filters above do not apply" in before_note, before_note)

            print("\n[4-5] Selected vs eligible; not yet checked")
            r5 = pg.inner_text("tr[data-sid='5']"); r2 = pg.inner_text("tr[data-sid='2']")
            check("4 a deselected source says Not selected and Not used in analysis", "Not selected" in r5 and "Not used in analysis" in r5, r5)
            check("4b a selected usable source says Selected and Eligible", "Selected" in r2 and "Eligible for analysis" in r2, r2)
            check("5 unchecked rows say they are not yet checked (no green claim)", "not yet checked by current rules" in r2 and "Document text available" not in r2, r2)
            check("5b the page offers a reassessment preview", pg.locator("#srPreview").count() == 1)

            print("\n[6] Dry run, cancel, apply")
            pg.click("#srPreview"); pg.wait_for_selector("#dlgOk")
            dlg = pg.inner_text(".modal")
            check("6 preview lists affected counts and before/after examples", "sources would change" in dlg and "S3" in dlg and "no_usable_text" in dlg, dlg[:600])
            check("6b preview says nothing is searched, retrieved or sent to a model", "no search, no retrieval, no model" in dlg, dlg[:300])
            check("6c preview made no write request", not writes and stored() == before_rows, writes)
            pg.click("#dlgCancel"); pg.wait_for_timeout(300)
            check("6d Cancel writes nothing", not writes and stored() == before_rows, writes)
            pg.click("#srPreview"); pg.wait_for_selector("#dlgOk"); pg.click("#dlgOk"); pg.wait_for_timeout(1200)
            check("6e Apply sends exactly one POST to source_review", writes == ["POST cases/1/source_review"], writes)

            if os.environ.get("WFD_SHOTS"):
                pg.screenshot(path=os.path.join(os.environ["WFD_SHOTS"], "sources_after_apply.png"), full_page=True)
            print("\n[7] After apply")
            r3 = pg.inner_text("tr[data-sid='3']")
            check("7 the error page shows No usable document text", "No usable document text" in r3, r3)
            check("7b ...is marked Needs review, not Irrelevant", "Needs review" in pg.inner_text("tr[data-sid='3'] td:nth-child(4) .badge"), r3)
            check("7c ...uses the red retrieval colour, while relevance stays neutral",
                  pg.locator("tr[data-sid='3'] .badge.bad").count() >= 1 and pg.locator("tr[data-sid='3'] td:nth-child(4) .badge.bad").count() == 0)
            check("7d ...and is not eligible for analysis", "Not used in analysis" in r3, r3)
            check("7e selections were not changed by reassessment", [r[3] for r in stored()] == [r[3] for r in before_rows], stored())
            check("7f the tourism page is no longer Directly relevant", stored()[3][2] != "relevant", stored()[3])
            pg.click("tr[data-sid='3'] details summary"); pg.click("[data-hist='3']"); pg.wait_for_selector("#dlgOk")
            hist = pg.inner_text(".modal")
            check("7g the change history shows old and new values and the rule version", "no_usable_text" in hist and "SR-" in hist, hist[:500])
            pg.click("#dlgOk"); pg.wait_for_timeout(200)

            print("\n[8] Human correction is kept")
            n = len(writes)
            pg.select_option("select[data-rel='4']", "background"); pg.wait_for_timeout(900)
            check("8 a relevance correction is one PATCH", writes[n:] == ["PATCH sources/4"], writes[n:])
            r4 = pg.inner_text("tr[data-sid='4']")
            check("8b it shows Background, human-confirmed", "Background" in r4 and "human-confirmed" in r4, r4)
            con = sqlite3.connect(d / "wfd.sqlite3")
            con.execute("UPDATE sources SET rule_version='old' WHERE id=4"); con.commit(); con.close()  # make the preview appear again
            pg.reload(); pg.wait_for_selector("#srPreview"); pg.click("#srPreview"); pg.wait_for_selector("#dlgOk"); pg.click("#dlgOk"); pg.wait_for_timeout(1200)
            check("8c a later reassessment keeps the human label", stored()[3][2] == "background", stored()[3])

            print("\n[9] Chinese; no errors")
            pg.evaluate("localStorage.setItem('wfd_lang','zh')"); pg.reload(); pg.wait_for_selector("#srcTable"); pg.wait_for_timeout(400)
            zh = pg.inner_text("#srcTable") + pg.inner_text("#srcCounts")
            check("9 group and status labels in Chinese", "新闻媒体" in zh and "没有可用的文档正文" in zh and "全案例" in zh, zh[:300])
            check("9b nothing was requested outside this machine", not outside, outside[:3])
            check("9c no JavaScript errors", not errors, errors)
            ctx.close(); b.close()
    finally:
        srv.terminate()
        shutil.rmtree(TMP, ignore_errors=True)
    print("\nSOURCES PAGE:", "PASS" if not FAILS else f"FAIL ({len(FAILS)}): {FAILS}")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
