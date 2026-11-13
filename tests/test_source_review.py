"""Source review rules on saved data (DECISIONS D-046). Run:  python -m tests.test_source_review

Synthetic local examples only. Network access is blocked for the whole test (any attempt fails the test), so it also
proves that assessing, reassessing, viewing, filtering and exporting never search, fetch, download or call a model.
"""
from __future__ import annotations

import io
import json
import os
import socket
import sys
import tempfile
import time
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="wfdsr_"))
os.environ["WFD_DATA_DIR"] = str(TMP / "data")
for k in ("ANTHROPIC_API_KEY", "TAVILY_API_KEY", "BRAVE_API_KEY", "OPENAI_API_KEY", "WFD_PASSWORD", "WFD_TEST_FIXTURE"):
    os.environ.pop(k, None)
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PASS, FAIL = [], []
NET = []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS " if cond else "  FAIL ") + name + (f"  — {detail}" if detail and not cond else ""))


_real_connect = socket.socket.connect


def _no_net(self, addr):  # block every outgoing connection except the local test server
    host = addr[0] if isinstance(addr, tuple) else str(addr)
    if host not in ("127.0.0.1", "localhost", "::1"):
        NET.append(addr)
        raise OSError("network blocked by test")
    return _real_connect(self, addr)


socket.socket.connect = _no_net

LONG_FLOOD = ("On 14 July 2021 the Ahr river rose within hours. In the Ahrtal, villages such as Schuld and Altenahr were "
              "flooded before any warning reached residents. The district of Ahrweiler issued its disaster alert late in "
              "the evening. ") * 30
GENERAL_HAZARD = ("River floods in mountainous catchments can rise quickly. Hydrological forecasting of flash floods "
                  "depends on rainfall estimates and gauge networks. ") * 30
TOURISM = ("The Ahr valley is famous for red wine, hiking trails and the picturesque old town of Ahrweiler. Visitors can "
           "explore wine cellars, cycle along the river and enjoy regional cuisine in cosy restaurants. ") * 12
OTHER_TOPIC = ("The city council discussed the new bicycle lanes in downtown Denver and the budget for public parks. "
               "Residents asked about parking rules near the stadium. ") * 20


def main():
    from app import db, server, research, source_review as sr, export
    from app.config import DEFAULT_SETTINGS
    db.conn()
    server.bootstrap_schema()

    print("\n[1] Content validity")
    q = lambda paras, **kw: sr.content_quality({"fetch_status": "ok", **kw}, paras)
    check("loading-error page is not document text",
          q(["A required part of this site couldn’t load. This may be due to a browser extension, network issues, or browser settings."])[0] == "no_usable_text")
    check("bot check / JavaScript page is not document text", q(["Just a moment...", "Enable JavaScript and cookies to continue"])[0] == "no_usable_text")
    notice = ("Flood warning for the district of Ahrweiler: residents along the Ahr must leave ground floors immediately. "
              "Emergency shelters are open at the town hall and the sports hall.")
    check("a short official notice is kept (partial, not rejected for length)", q([notice])[0] == "partial", str(q([notice])))
    abstract = ("Abstract. The July 2021 flood in the Ahr valley caused 135 deaths. We analyse warning dissemination using a "
                "survey of 1,315 residents and show that most received no warning or did not expect severe impacts. "
                "Keywords: flood warning, risk communication, Germany.")
    check("an abstract is kept as partial content", q([abstract])[0] == "partial")
    long_article = [LONG_FLOOD, "Access denied to the evacuation route was a problem reported by firefighters during the night."]
    check("a long article that contains 'access denied' stays full text", q(long_article)[0] == "full_text", str(q(long_article)))
    check("recorded failure keeps its recorded reason", sr.content_quality({"fetch_status": "failed", "fetch_error": "access restricted (HTTP 403)"}, [])[1]
          .endswith("access restricted (HTTP 403))"))
    ir = sr.content_quality({"fetch_status": "failed", "fetch_error": "skipped: the server restarted while reading this source (it may be too large)"}, [])
    check("interrupted retrieval: 'retrieval incomplete', possible cause kept as recorded, not diagnosed",
          ir[0] == "interrupted" and "may be too large" in ir[1] and "out of memory" not in ir[1])

    print("\n[2] Incident relevance")
    case = {"name": "Ahr valley disaster flood", "location": "germany Ahr valley", "date_text": "july 15 2021", "aliases": "",
            "details": "", "identity_json": json.dumps({"auto_aliases": ["Ahrtal", "Ahrweiler", "Disasters", "Germany Ahr"]})}
    terms = research.case_terms(case)
    rel = lambda paras, quality="full_text", **kw: sr.relevance_v2(case, terms, paras, quality, **kw)
    check("an article about the flood at the place in 2021 is directly relevant", rel([LONG_FLOOD])[0] == "relevant", rel([LONG_FLOOD])[1])
    tour = rel([TOURISM])
    check("a tourism page is not relevant just because it names the place", tour[0] != "relevant", tour[1])
    check("…and with substantial text but no hazard at all it is irrelevant, with a reason", tour[0] == "irrelevant" and "never the hazard" in tour[1])
    pub2025 = [LONG_FLOOD.replace("14 July 2021", "14 July"), "Published 2025. Received 3 March 2025."]
    check("a 2025 publication about the incident is still relevant (publication date ≠ incident date)",
          rel([LONG_FLOOD + " Published 2025."])[0] == "relevant")
    nodate = rel([LONG_FLOOD.replace("2021", "")])
    check("a source without the year is not rejected when place and hazard clearly match", nodate[0] in ("relevant", "background"), nodate[1])
    err = rel(["A required part of this site couldn’t load."], "no_usable_text", title="Warning failures in the Ahrtal flood 2021")
    check("missing / invalid text → needs review, never irrelevant", err[0] == "uncertain" and "needs review" in err[1])
    check("…with a clearly labelled preliminary hint from the title", "preliminary (title/search snippet only)" in err[1])
    check("genuinely unrelated substantive text stays irrelevant", rel([OTHER_TOPIC])[0] == "irrelevant")
    check("general hazard background without the place is not 'directly relevant'", rel([GENERAL_HAZARD])[0] != "relevant")
    check("keyword counts are labelled as keyword-match measures", "keyword match:" in rel([LONG_FLOOD])[1])
    check("a bad automatic alias ('Disasters') is not used as a place name", "disasters" not in sr._place_tokens(terms, case))
    tags = sr.topic_tags([LONG_FLOOD], "full_text")
    check("topic tags are optional hints from saved text", "warning_evacuation" in tags and sr.topic_tags([LONG_FLOOD], "no_usable_text") == [])

    print("\n[3] Document type")
    c = sr.classify_v2
    check("a paper on a government repository stays academic (USDA Treesearch)",
          c("https://research.fs.usda.gov/download/treesearch/80940.pdf", "Flood risk in forested catchments")[0] == "academic")
    check("a journal article on a .org publisher is academic, not ngo_technical",
          c("https://nhess.copernicus.org/articles/23/973/2023/", "Performance of the flood warning system in Germany in July 2021")[0:2] == ("academic", "journal_article"))
    check("an MDPI article (.com) is academic", c("https://www.mdpi.com/2071-1050/15/2/1407", "Adaptation after extreme flooding")[0] == "academic")
    check("a paper in a university repository is academic, never media by default",
          c("https://publishup.uni-potsdam.de/opus4-ubp/frontdoor/index/index/docId/1", "Flood warnings in Germany")[0] == "academic")
    check("…and a university page with article structure too", c("https://www.uni-example.de/paper", "x",
          "Abstract We study warnings. Keywords: flood. 1 Introduction ... References")[0] == "academic")
    check("a preprint is recognised as a preprint", c("https://nhess.copernicus.org/preprints/nhess-2022-80/", "Ahr flood")[1] == "preprint")
    check("a news story about a government report stays news", c("https://www.tagesschau.de/inland/ahr-bericht-101.html",
          "Untersuchungsausschuss legt Abschlussbericht zur Flut vor")[0] == "media")
    check("a state parliament inquiry is legislative", c("https://dokumente.landtag.rlp.de/landtag/drucksachen/1234-18.pdf",
          "Abschlussbericht des Untersuchungsausschusses 18/1 Flutkatastrophe")[0] == "legislative")
    check("an explicit after-action report is aar", c("https://www.county.example.us/aar.pdf", "After-Action Report: Marshall Fire")[0] == "aar")
    check("an official government website is government", c("https://www.bbk.bund.de/DE/warnung", "Warnung der Bevölkerung")[0] == "government")
    check("a post-disaster publication is not automatically an AAR", c("https://www.example.org/news", "Five years after the flood")[0] != "aar")
    check("a tourism page is other, not media", c("https://www.visit-koblenz.de/ahr", "Ahr Valley – Discover the Region – Visit Koblenz")[0:2] == ("unknown", "tourism"))
    check("an unfamiliar site is unclassified, not media", c("https://www.example-unknown.net/page", "Something")[0] == "unknown")
    check("social media is other", c("https://www.facebook.com/GermanEmbassyUK/posts/1", "The flood disaster")[1] == "social_media")
    check("the search query that found a source is not an input", "found_via" not in sr.classify_v2.__code__.co_varnames)

    print("\n[4] Saved case: reassessment dry run → apply, history, human labels, groups, duplicates")
    s = {**DEFAULT_SETTINGS}
    cid = db.insert("cases", {"name": case["name"], "location": case["location"], "date_text": case["date_text"], "details": "",
                              "known_links": "", "aliases": "", "schema_version_id": 1, "status": "sources_ready",
                              "identity_json": case["identity_json"], "settings_json": json.dumps(s),
                              "created_at": time.time(), "updated_at": time.time()})

    def add(url, title, paras, ftype="government", ok=True, rel_status="relevant", rel_reason="name 50%, location 100%", dup=None,
            content_hash=None, excluded=0, err=""):
        sid = db.insert("sources", {"case_id": cid, "url": url, "final_url": url, "title": title, "publisher": "",
                                    "fetch_status": "ok" if ok else "failed", "fetch_error": err, "source_type": ftype,
                                    "relevance_status": rel_status, "relevance_reason": rel_reason, "excluded": excluded,
                                    "duplicate_of": dup, "content_hash": content_hash, "n_passages": len(paras),
                                    "origin": "search", "retrieved_at": time.time(), "job_id": 7})
        for i, p in enumerate(paras, 1):
            db.insert("passages", {"id": f"S{sid}-P{i}", "case_id": cid, "source_id": sid, "seq": i, "page": None, "para": i, "text": p})
        return sid
    ERR = "A required part of this site couldn’t load. This may be due to a browser extension, network issues, or browser settings."
    s_err = add("https://doi.org/10.1111/jfr3.70021", "Warning performance across districts in the 2021 Ahr flood", [ERR],
                "media", rel_status="irrelevant", rel_reason="name 0%, location 0%, no year stated", content_hash="h-err")
    s_err2 = add("https://onlinelibrary.wiley.com/doi/10.1111/other.1", "A different paper about risk perception in Belgium", [ERR],
                 "media", rel_status="irrelevant", dup=s_err, content_hash="h-err")
    s_gov_paper = add("https://research.fs.usda.gov/download/treesearch/80940.pdf", "Forest hydrology and flood generation in "
                      "small catchments", [GENERAL_HAZARD], "government", rel_status="uncertain")
    s_tour = add("https://www.visit-koblenz.de/ahr", "Ahr Valley – Discover the Region – Visit Koblenz", [TOURISM], "media")
    s_news = add("https://www.tagesschau.de/ahr-flut-2021", "Flut im Ahrtal: Warnung kam zu spät", [LONG_FLOOD], "media")
    s_pdf = add("https://nhess.copernicus.org/articles/23/973/2023/nhess-23-973-2023.pdf", "Performance of the flood warning "
                "system in Germany in July 2021", ["This study analyses the warning chain. " + LONG_FLOOD], "ngo_technical", content_hash="h-paper")
    s_html = add("https://nhess.copernicus.org/articles/23/973/2023/", "Performance of the flood warning system in Germany in "
                 "July 2021", ["Abstract. This study analyses the warning chain. " + LONG_FLOOD], "ngo_technical", content_hash="h-paper-html")
    s_human = add("https://www.example.net/page", "Some page", [LONG_FLOOD], "legislative", rel_status="relevant",
                  rel_reason="set by reviewer: checked by hand")
    s_other = add("https://www.denverite.com/bikes", "Denver bike lanes", [OTHER_TOPIC], "media", rel_status="irrelevant")
    s_fail = add("https://table.media/x", "Five years since the Ahr valley flood", [], "media", ok=False, rel_status="unchecked",
                 err="access restricted (HTTP 403)", excluded=0)
    # a finished analysis that used the error-page source
    snap = db.insert("evidence_snapshots", {"case_id": cid, "fingerprint": "fp1", "n_sources": 2, "n_passages": 2,
                                           "sources_json": json.dumps([s_err, s_news]), "passages_json": "{}",
                                           "codebook_version": "x", "retrieval_json": "{}", "created_at": time.time()})
    run_id = db.insert("runs", {"case_id": cid, "job_id": 1, "mode": "manual", "provider": "anthropic", "schema_version_id": 1,
                                "created_at": time.time(), "evidence_snapshot_id": snap})
    before = {r["id"]: dict(r) for r in db.q("SELECT * FROM sources WHERE case_id=?", (cid,))}
    excl_before = {k: v["excluded"] for k, v in before.items()}
    dry = server.api_source_review_preview(type("H", (), {"user": "x"})(), str(cid))
    check("dry run changes nothing", {r["id"]: dict(r) for r in db.q("SELECT * FROM sources WHERE case_id=?", (cid,))} == before
          and db.q1("SELECT COUNT(*) n FROM source_label_history")["n"] == 0)
    check("dry run reports counts and before/after examples", dry["sources_changing"] > 0 and dry["examples"] and not dry["applied"], json.dumps(dry)[:300])
    check("dry run flags the finished analysis that used now-unusable text (flag only)",
          any(f["run"] == run_id and f"S{s_err}" in f["sources"] for f in dry["analyses_to_review"]), str(dry["analyses_to_review"]))
    try:
        server.api_source_review_apply(type("H", (), {"user": "x"})(), str(cid), {})
        check("apply needs confirmation", False)
    except server.ApiError as e:
        check("apply needs explicit confirmation after the preview", e.status == 400)
    res = server.api_source_review_apply(type("H", (), {"user": "curator"})(), str(cid), {"confirm": True})
    after = {r["id"]: dict(r) for r in db.q("SELECT * FROM sources WHERE case_id=?", (cid,))}
    g = lambda sid, f: after[sid][f]
    check("error-page source: no usable text, relevance needs review (not irrelevant)",
          g(s_err, "content_status") == "no_usable_text" and g(s_err, "relevance_status") == "uncertain", str((g(s_err, "content_status"), g(s_err, "relevance_status"))))
    check("different papers sharing an error template are no longer duplicates", g(s_err2, "duplicate_of") is None)
    check("government-hosted paper → academic", g(s_gov_paper, "source_type") == "academic")
    check("tourism page → other, not relevant", g(s_tour, "source_type") == "unknown" and g(s_tour, "relevance_status") != "relevant")
    check("news about the flood stays news and directly relevant", g(s_news, "source_type") == "media" and g(s_news, "relevance_status") == "relevant")
    check("journal article (was ngo_technical) → academic, journal article", g(s_pdf, "source_type") == "academic" and g(s_pdf, "type_subtype") == "journal_article")
    check("PDF and web page of the same paper are grouped (originals kept)", g(s_pdf, "doc_group") and g(s_pdf, "doc_group") == g(s_html, "doc_group")
          and len(after) == len(before))
    check("error-template papers are not grouped together", g(s_err, "doc_group") is None or g(s_err, "doc_group") != g(s_err2, "doc_group"))
    check("human relevance kept and marked as human", g(s_human, "relevance_status") == "relevant" and g(s_human, "relevance_basis") == "human")
    check("a type that differs from the old rule is kept as a probable human correction",
          g(s_human, "source_type") == "legislative" and g(s_human, "type_basis") == "human")
    check("genuinely irrelevant source keeps irrelevant with a reason", g(s_other, "relevance_status") == "irrelevant" and "never mentions" in g(s_other, "relevance_reason"))
    check("failed source stays visible: not retrieved, needs review", g(s_fail, "content_status") == "not_retrieved" and g(s_fail, "relevance_status") == "uncertain")
    check("selections unchanged", {k: v["excluded"] for k, v in after.items()} == excl_before)
    check("no source deleted", len(after) == len(before))
    hist = db.q("SELECT * FROM source_label_history WHERE source_id=? AND field='relevance_status'", (s_err,))
    check("every change recorded with old value, new value, rule version and who applied it",
          hist and hist[0]["old_value"] == "irrelevant" and hist[0]["new_value"] == "uncertain" and hist[0]["changed_by"] == "curator"
          and hist[0]["rule_version"] == sr.RULE_VERSION)
    check("finished analysis untouched", db.q1("SELECT evidence_snapshot_id FROM runs WHERE id=?", (run_id,))["evidence_snapshot_id"] == snap
          and json.loads(db.q1("SELECT sources_json FROM evidence_snapshots WHERE id=?", (snap,))["sources_json"]) == [s_err, s_news])
    elig = {r["id"]: r["eligible"] for r in server.api_sources(None, str(cid))}
    check("error-page source is not eligible for future analysis; usable relevant ones are", not elig[s_err] and elig[s_news])
    check("next analysis evidence excludes error text", all(p["source_id"] != s_err for p in __import__("app.retrieval", fromlist=["x"]).load_case_passages(cid)))
    again = sr.reassess_case(cid)
    check("re-running the dry run after apply finds nothing more to change", again["sources_changing"] == 0, json.dumps(again["changes"]))
    server.api_patch_source(type("H", (), {"user": "curator"})(), str(s_tour), {"source_type": "government", "reason": "tourist board of the state"})
    sr.reassess_case(cid, apply=True, actor="x")
    check("rules never overwrite a human type correction", db.q1("SELECT source_type, type_basis FROM sources WHERE id=?", (s_tour,)) == {"source_type": "government", "type_basis": "human"})
    check("human change recorded in history", db.q1("SELECT COUNT(*) n FROM source_label_history WHERE source_id=? AND basis='human'", (s_tour,))["n"] == 1)

    print("\n[5] New sources are assessed when saved; error pages never become duplicates")
    sid_a = research.save_source(cid, {"url": "https://a.example/p1", "title": "Paper A on the Ahr flood 2021", "origin": "search"},
                                 {"title": "", "pages": [{"page": None, "paragraphs": [ERR]}], "links": []}, "ok")
    sid_b = research.save_source(cid, {"url": "https://b.example/p2", "title": "Different paper B", "origin": "search"},
                                 {"title": "", "pages": [{"page": None, "paragraphs": [ERR]}], "links": []}, "ok")
    nb = db.q1("SELECT * FROM sources WHERE id=?", (sid_b,))
    check("new error-page source saved as no usable text, needs review", nb["content_status"] == "no_usable_text" and nb["relevance_status"] == "uncertain")
    check("…and not marked a duplicate of another error page", nb["duplicate_of"] is None and nb["near_duplicate_of"] is None)

    print("\n[6] Export and read-only views make no external calls and keep semantics")
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(export.sources_xlsx(cid)))
    hdr = [c.value for c in wb["Sources"][1]]
    rows = [dict(zip(hdr, [c.value for c in r])) for r in wb["Sources"].iter_rows(min_row=2)]
    check("export lists selected sources only by default (semantics unchanged)", all(r["Selected for analysis"] == "yes" for r in rows))
    check("export shows content, relevance and who set each label",
          all(k in hdr for k in ("Content", "Relevance set by", "Type set by", "Document subtype", "Document group")))
    order = [research.TYPE_PRIORITY.get({v: k for k, v in export.SOURCE_TYPE_LABEL.items()}.get(r["Source type"], "unknown"), 5) for r in rows]
    check("export keeps authority group order", order == sorted(order), str(order))
    server.api_source_counts(None, str(cid))
    check("no network connection was attempted at any point", not NET, str(NET))

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED:", *FAIL, sep="\n  ")
        sys.exit(1)


if __name__ == "__main__":
    main()
