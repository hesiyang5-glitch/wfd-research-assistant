"""German search: specialist terms, official bodies, retrieval-quality report (DECISIONS D-047). Run:
    python3 -m tests.test_german_search

Offline: TEST-FIXTURE search replays saved results; every non-local network connection is refused; no model. Checks:
  [1] queries aimed at German official bodies (DWD, BBK, Bundestag, BfG for floods, Landtag) and specialist German
      terms; state parliament / government domains only when the state is typed; none outside Germany; English
      geographic words removed; each labelled "authority:" or "local terms:" in the search log
  [2] end-to-end run: the new queries ran, are logged and counted, the per-run query limit still holds, and keyword
      discovery queries still all ran (no crowding out)
  [3] classification of German official / legislative hosts; German specialist words count as hazard words
  [4] language estimate from saved text (de / en / et / ro / too short)
  [5] retrieval-quality report: languages (declared vs estimated), document types, query yield, official bodies
      searched / saved / usable, gaps (bilingual), read-only (database unchanged), API 404 for unknown case
  [6] browser: the Retrieval quality panel loads on opening, shows gaps and official bodies, Chinese labels, no writes
"""
from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="wfdde_"))
os.environ["WFD_DATA_DIR"] = str(TMP / "data")
for k in ("ANTHROPIC_API_KEY", "TAVILY_API_KEY", "BRAVE_API_KEY", "OPENAI_API_KEY", "WFD_PASSWORD"):
    os.environ.pop(k, None)
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_real_connect = socket.socket.connect
OUTSIDE: list = []


def _guard(self, addr):
    host = addr[0] if isinstance(addr, tuple) else addr
    if host not in ("127.0.0.1", "localhost", "::1"):
        OUTSIDE.append(addr)
        raise OSError("network blocked in test")
    return _real_connect(self, addr)


socket.socket.connect = _guard

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS " if cond else "  FAIL ") + name + (f"  — {str(detail)[:400]}" if detail and not cond else ""))


AHR = {"name": "Ahr valley disaster flood", "location": "germany Ahr valley", "date_text": "july 15 2021"}
RESULTS = [
    {"url": "https://www.swr.de/ahr-1", "title": "Flutkatastrophe im Ahrtal: Warnung kam zu spät",
     "snippet": "Der Kreis Ahrweiler warnte erst spät, Juli 2021", "match": []},
    {"url": "https://www.tagesschau.de/ahr-2", "title": "Ahrtal-Flut 2021: Untersuchungsausschuss",
     "snippet": "Landrat und die Flutkatastrophe in Ahrweiler, Bad Neuenahr", "match": []},
    {"url": "https://www.dw.com/ahr-3", "title": "Ahr valley flood 2021: warnings failed",
     "snippet": "In Ahrweiler district the Flutkatastrophe killed 135 people", "match": []},
    {"url": "https://nhess.copernicus.org/ahr-4", "title": "Flood warning in Germany July 2021 Ahr valley",
     "snippet": "Residents of Ahrweiler and Bad Neuenahr received warnings late in the Ahrtal", "match": []},
    {"url": "https://example.com/ahr-5", "title": "Bad Neuenahr flood Ahr valley 2021", "snippet": "Ahrtal Ahrweiler", "match": []},
]
DE_TEXT = ("Am 14. Juli 2021 gab der Deutsche Wetterdienst eine Unwetterwarnung für Starkregen heraus. Die Warnung wurde "
           "nicht rechtzeitig an die Bevölkerung im Ahrtal weitergegeben, und der Katastrophenfall wurde erst spät "
           "ausgerufen. Das Hochwasser an der Ahr war für die Menschen in Ahrweiler eine Katastrophe. ") * 8
EN_TEXT = ("The flood in the Ahr valley in July 2021 was one of the worst in Germany. Warnings were issued by the weather "
           "service but were not passed on to the residents of Ahrweiler in time, and this was a failure of the system. ") * 6
ET_TEXT = ("Üleujutus oli suur ja see oli ootamatu. Hoiatus ei jõudnud inimesteni ja ka päästeamet ei olnud valmis, "
           "mis on ka põhjus, miks kahju oli nii suur. See oli raske aeg ning seda ei unustata. ") * 6
RO_TEXT = ("Inundația a fost una dintre cele mai grave și nu a fost anunțată la timp. Avertizarea care a fost trimisă "
           "pentru populație nu este suficientă și mai sunt multe de făcut în această privință cu autoritățile din zonă. ") * 6


def main():
    from app.search import expansion as ex

    print("\n[1] Queries aimed at official bodies and specialist terms")
    de = ex.detect_country(AHR["location"])
    q = ex.authority_templates(AHR, de, "2021")
    txt = " | ".join(x[1] for x in q)
    check("DWD, BBK, Bundestag and BfG (flood) are searched by site", all(f"site:{d}" in txt for d in ("dwd.de", "bbk.bund.de", "bundestag.de", "bafg.de")), txt)
    check("a Landtag inquiry query without a site when no state is typed", any("Landtag Untersuchungsausschuss" in x[1] and "site:" not in x[1] for x in q), txt)
    check("specialist German terms are used (Starkregen, Unwetterwarnung, Katastrophenfall)",
          all(w in txt for w in ("Starkregen", "Unwetterwarnung", "Katastrophenfall")), txt)
    check("English geographic words removed (no 'valley')", "valley" not in txt.lower(), txt)
    check("each query is labelled authority: or local terms:", all(x[0].startswith(("authority:", "local terms:")) for x in q), [x[0] for x in q])
    check("at most 9 extra queries", len(q) <= 9, len(q))
    rp = {"name": "2021 flood", "location": "Ahrweiler, Rheinland-Pfalz, Germany"}
    q2 = " | ".join(x[1] for x in ex.authority_templates(rp, ex.detect_country(rp["location"]), "2021"))
    check("with the state typed: state parliament and state government sites", "site:landtag.rlp.de" in q2 and "site:rlp.de" in q2, q2)
    check("the state name is not used as a search word", "Rheinland" not in q2, q2)
    fire = {"name": "forest fire", "location": "Brandenburg, Germany"}
    q3 = " | ".join(x[1] for x in ex.authority_templates(fire, ex.detect_country(fire["location"]), "2022"))
    check("BfG (river gauges) only for floods", "bafg.de" not in q3 and "Waldbrand" in q3, q3)
    check("no such queries outside Germany or for the U.S.",
          ex.authority_templates({"name": "flood", "location": "Paris, France"}, ex.detect_country("Paris, France"), "2021") == []
          and ex.authority_templates({"name": "Marshall Fire", "location": "Boulder County, Colorado"}, None, "2021") == [])
    check("Austria / Switzerland unchanged (German language, no German federal bodies)",
          ex.authority_templates({"name": "flood", "location": "Tyrol, Austria"}, ex.detect_country("Tyrol, Austria"), "2021") == [])

    print("\n[2] End-to-end run (TEST-FIXTURE search, no model)")
    from app import coding, db, jobs, research
    from app.config import DEFAULT_SETTINGS
    from app.server import bootstrap_schema
    db.conn()
    bootstrap_schema()
    schema = coding.active_schema()
    fx = TMP / "fx.json"
    fx.write_text(json.dumps({"results": RESULTS}), encoding="utf-8")
    os.environ["WFD_TEST_FIXTURE"] = str(fx)
    s = {**DEFAULT_SETTINGS, "model_provider": "none", "max_search_rounds": 0, "max_fetch": 0, "follow_links": False}
    cid = db.insert("cases", {"name": AHR["name"], "location": AHR["location"], "date_text": AHR["date_text"], "details": "",
                              "known_links": "", "aliases": "Flutkatastrophe Ahrtal", "schema_version_id": schema["id"],
                              "status": "new", "identity_json": "{}", "settings_json": json.dumps(s),
                              "created_at": time.time(), "updated_at": time.time()})
    jid = jobs.enqueue(cid, "research", {"identity_confirmed": True})
    research.run_research(db.q1("SELECT * FROM jobs WHERE id=?", (jid,)))
    qs = db.q("SELECT purpose, query FROM search_queries WHERE case_id=?", (cid,))
    purposes = [x["purpose"] for x in qs]
    log = " ".join(r["message"] for r in db.q("SELECT message FROM job_log WHERE job_id=?", (jid,)))
    check("official-body queries ran and are logged", sum(p.startswith("authority:") for p in purposes) >= 5
          and "queries aimed at official bodies" in log, purposes)
    check("specialist-term queries ran", any(p.startswith("local terms:") for p in purposes), purposes)
    check("each search is counted (usage rows = queries)",
          db.q1("SELECT COUNT(*) n FROM usage WHERE case_id=? AND kind='search'", (cid,))["n"] == len(qs), len(qs))
    check("still within the per-run query limit", len(qs) <= int(s["max_queries"]), f"{len(qs)} of {s['max_queries']}")
    ident = json.loads(db.q1("SELECT identity_json FROM cases WHERE id=?", (cid,))["identity_json"])
    planned = ex.discovery_queries(ident.get("discovered_keywords") or [], db.q1("SELECT * FROM cases WHERE id=?", (cid,)), de, "2021")
    ran = sum(p.startswith("discovered keyword") for p in purposes)
    check("keyword-discovery queries were not crowded out", planned and ran >= len(planned), f"{ran} ran / {len(planned)} planned; total {len(qs)}")
    # a tight query limit: official-body queries are the ones cut (they run last), and the log says so
    s2 = {**s, "max_queries": len(qs) - 3}
    cid2 = db.insert("cases", {"name": AHR["name"] + " (limit)", "location": AHR["location"], "date_text": AHR["date_text"], "details": "",
                               "known_links": "", "aliases": "Flutkatastrophe Ahrtal", "schema_version_id": schema["id"],
                               "status": "new", "identity_json": "{}", "settings_json": json.dumps(s2),
                               "created_at": time.time(), "updated_at": time.time()})
    jid2 = jobs.enqueue(cid2, "research", {"identity_confirmed": True})
    research.run_research(db.q1("SELECT * FROM jobs WHERE id=?", (jid2,)))
    p2 = [x["purpose"] for x in db.q("SELECT purpose FROM search_queries WHERE case_id=?", (cid2,))]
    log2 = " ".join(r["message"] for r in db.q("SELECT message FROM job_log WHERE job_id=?", (jid2,)))
    check("tight limit: the limit holds, keyword discovery still ran, the cut is logged",
          len(p2) <= s2["max_queries"] and sum(x.startswith("discovered keyword") for x in p2) == ran
          and "before the per-run query limit" in log2, f"{len(p2)} queries; {log2[-300:]}")
    os.environ.pop("WFD_TEST_FIXTURE", None)

    print("\n[3] Classification and hazard words")
    from app import source_review as sr
    cls = {u: sr.classify_v2(u, t)[0] for u, t in [
        ("https://www.dwd.de/DE/presse/2021.pdf", "Pressemitteilung Unwetter"), ("https://www.bbk.bund.de/warnung", "Warnung der Bevölkerung"),
        ("https://www.landtag.rlp.de/drucksache-18-1234.pdf", "Abschlussbericht"), ("https://mdi.rlp.de/hochwasser", "Hochwasser 2021"),
        ("https://www.bafg.de/hochwasser2021.pdf", "Hochwasser Juli 2021"), ("https://www.bundestag.de/presse", "Ahr Hochwasser"),
        ("https://www.tagesschau.de/ahr-2", "Ahrtal-Flut 2021")]}
    check("DWD, BBK, BfG and state ministry are government", [cls[k] for k in list(cls)[:2] + [list(cls)[3], list(cls)[4]]] == ["government"] * 4, cls)
    check("Landtag and Bundestag are legislative", cls["https://www.landtag.rlp.de/drucksache-18-1234.pdf"] == "legislative"
          and cls["https://www.bundestag.de/presse"] == "legislative", cls)
    check("tagesschau stays news", cls["https://www.tagesschau.de/ahr-2"] == "media", cls)
    hz = sr._hazard_terms({"name": "Ahr valley flood", "location": "Ahr valley, Germany"})
    check("German specialist flood words count as hazard words (not Pegel alone)", "starkregen" in hz and "sturzflut" in hz and "pegel" not in hz, hz)
    check("rule version bumped for the changed rules", sr.RULE_VERSION.endswith(".2"), sr.RULE_VERSION)

    print("\n[4] Language estimate")
    from app.retrieval_quality import guess_language
    got = [guess_language(t) for t in (DE_TEXT, EN_TEXT, ET_TEXT, RO_TEXT, "Hochwasser Ahr")]
    check("German, English, Estonian, Romanian recognised; too short → unknown", got == ["de", "en", "et", "ro", None], got)

    print("\n[5] Retrieval-quality report")
    rid = db.insert("cases", {"name": "Ahr flood 2021", "location": "Ahrweiler, Rheinland-Pfalz, Germany", "date_text": "July 2021",
                              "details": "", "known_links": "", "aliases": "", "schema_version_id": schema["id"], "status": "new",
                              "identity_json": "{}", "settings_json": json.dumps(s), "created_at": time.time(), "updated_at": time.time()})
    def src(url, typ, status, text=None, lang="", rel="relevant", content=None):
        sid = db.insert("sources", {"case_id": rid, "url": url, "title": url, "source_type": typ, "fetch_status": status,
                                    "relevance_status": rel, "excluded": 0, "language": lang, "content_status": content,
                                    "n_passages": 1 if text else 0})
        if text:
            db.insert("passages", {"id": f"S{sid}-P1", "case_id": rid, "source_id": sid, "seq": 0, "page": None, "para": 1, "text": text})
        return sid
    s_dwd = src("https://www.dwd.de/ahr.pdf", "government", "ok", DE_TEXT, content="full_text")
    src("https://www.bbk.bund.de/x", "government", "failed", rel="unchecked", content="not_retrieved")
    src("https://www.tagesschau.de/ahr", "media", "ok", DE_TEXT, lang="de", content="full_text")
    src("https://www.dw.com/ahr", "media", "ok", EN_TEXT, lang="en", content="full_text")
    src("https://news.example.com/err", "media", "ok", "Access denied", rel="uncertain", content="no_usable_text")
    def qrow(purpose, query, urls):
        qid = db.insert("search_queries", {"case_id": rid, "job_id": None, "round": 0, "purpose": purpose, "query": query,
                                           "status": "ok", "result_count": len(urls), "created_at": time.time()})
        for i, u in enumerate(urls):
            db.insert("search_results", {"query_id": qid, "case_id": rid, "url": u, "title": u, "rank": i})
    qrow("authority: Deutscher Wetterdienst (DWD)", "Hochwasser Ahrweiler 2021 Warnung site:dwd.de", ["https://www.dwd.de/ahr.pdf"])
    qrow("authority: Bundesamt für Bevölkerungsschutz und Katastrophenhilfe (BBK)", "Ahrweiler 2021 Warnung site:bbk.bund.de", ["https://www.bbk.bund.de/x"])
    qrow("authority: Deutscher Bundestag", "Hochwasser Ahrweiler 2021 Drucksache site:bundestag.de", [])
    qrow("local language: warning", "Hochwasser Ahrweiler 2021 Warnung", ["https://www.tagesschau.de/ahr", "https://www.dwd.de/ahr.pdf"])
    qrow("initial: news", "Ahr flood 2021", ["https://www.dw.com/ahr", "https://news.example.com/err", "https://other.example/x"])
    from app.retrieval_quality import report
    dbfile = Path(os.environ["WFD_DATA_DIR"]) / "wfd.sqlite3"
    db.conn().execute("PRAGMA wal_checkpoint(FULL)")
    before = hashlib.sha256(dbfile.read_bytes()).hexdigest()
    r = report(rid)
    db.conn().execute("PRAGMA wal_checkpoint(FULL)")
    check("report is read-only (database file unchanged)", hashlib.sha256(dbfile.read_bytes()).hexdigest() == before)
    langs = {l["code"]: l for l in r["languages"]}
    check("German: 1 declared + 1 estimated (the DWD PDF), both usable", langs["de"]["saved"] == 2 and langs["de"]["declared"] == 1
          and langs["de"]["estimated"] == 1 and langs["de"]["usable"] == 2, langs)
    check("unknown language counted separately (failed + error page)", langs.get("unknown", {}).get("saved") == 2, langs)
    t = {x["group"]: x for x in r["types"]}
    check("types: government 2 saved / 1 usable; news 3 saved / 2 usable", (t["gov"]["saved"], t["gov"]["usable"], t["media"]["saved"], t["media"]["usable"]) == (2, 1, 3, 2), t)
    b = {x["site"]: x for x in r["official_bodies"]}
    check("DWD searched, saved and usable (S%d)" % s_dwd, b["dwd.de"]["searched"] == 1 and b["dwd.de"]["usable"] == 1 and f"S{s_dwd}" in b["dwd.de"]["examples"], b["dwd.de"])
    check("BBK searched but nothing readable", b["bbk.bund.de"]["searched"] == 1 and b["bbk.bund.de"]["saved"] == 1 and b["bbk.bund.de"]["usable"] == 0, b["bbk.bund.de"])
    check("state parliament and state government listed when the state is typed", "landtag.rlp.de" in b and "rlp.de" in b, list(b))
    gaps_en = " ".join(g["en"] for g in r["gaps"])
    check("gaps: no AAR, no legislative, BBK searched without result, Bundestag searched 0 results, Landtag not searched",
          "No after-action report" in gaps_en and "No legislative" in gaps_en and "bbk.bund.de) was searched 1×" in gaps_en
          and "bundestag.de) was searched 1× (0 results)" in gaps_en and "landtag.rlp.de) has not been searched" in gaps_en, gaps_en)
    check("no false gap for German-language sources", "German-language" not in gaps_en, gaps_en)
    check("every gap is also in Chinese", all(g.get("zh") for g in r["gaps"]))
    y = {x["kind"]: x for x in r["query_yield"]}
    check("query yield: official bodies 3 queries / 2 results / 1 usable; local-language 1 query / 2 usable",
          (y["Official bodies (site-restricted)"]["queries"], y["Official bodies (site-restricted)"]["results"], y["Official bodies (site-restricted)"]["usable"],
           y["Local-language queries"]["usable"]) == (3, 2, 1, 2), y)
    check("the note says gaps are about saved data, not existence", "not that no such document exists" in r["note"])
    check("no network connection was attempted", not OUTSIDE, OUTSIDE)

    print("\n[6] Browser panel")
    shots = os.environ.get("WFD_SHOTS")
    env = {**os.environ, "WFD_PORT": "18875", "HTTPS_PROXY": "http://127.0.0.1:9", "HTTP_PROXY": "http://127.0.0.1:9",
           "NO_PROXY": "127.0.0.1,localhost"}
    env.pop("WFD_TEST_FIXTURE", None)
    srv = subprocess.Popen([sys.executable, "-m", "app.server"], cwd=str(ROOT), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    time.sleep(3)
    U = "http://127.0.0.1:18875/"
    try:
        import urllib.error
        import urllib.request
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            op.open(U + "api/cases/99999/retrieval_quality", timeout=10); code = 200
        except urllib.error.HTTPError as e:
            code = e.code
        check("API: unknown case → 404", code == 404, code)
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            br = p.chromium.launch()
            ctx = br.new_context(viewport={"width": 1300, "height": 1000})
            ctx.add_init_script("if (!localStorage.getItem('wfd_lang')) localStorage.setItem('wfd_lang','en')")
            pg = ctx.new_page()
            errs, writes = [], []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.on("request", lambda rq: writes.append(rq.url) if rq.method != "GET" else None)
            pg.goto(U + f"#/case/{rid}/sources"); pg.wait_for_selector("#rqPanel")
            check("panel is closed until opened", not pg.eval_on_selector("#rqPanel", "e => e.open"))
            pg.click("#rqPanel summary"); pg.wait_for_selector("#rqBody h4")
            body = pg.inner_text("#rqBody")
            check("panel shows gaps, official bodies and languages", "Gaps" in body and "Deutscher Wetterdienst" in body and "German" in body
                  and "local language" in body, body[:500])
            if shots:
                pg.locator("#rqPanel").screenshot(path=os.path.join(shots, "retrieval_quality_panel.png"))
            pg.evaluate("localStorage.setItem('wfd_lang','zh')"); pg.reload(); pg.wait_for_selector("#rqPanel")
            pg.click("#rqPanel summary"); pg.wait_for_selector("#rqBody h4")
            zb = pg.inner_text("#rqBody")
            check("Chinese labels and Chinese gap text", "缺口" in zb and "没有保存到有可用正文的事后评估报告" in zb, zb[:300])
            check("opening the panel sent no write request", not writes, writes)
            check("no JavaScript errors", not errs, errs)
            ctx.close(); br.close()
    finally:
        srv.terminate()

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED:", *FAIL, sep="\n  ")
        sys.exit(1)


if __name__ == "__main__":
    main()
