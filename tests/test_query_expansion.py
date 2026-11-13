"""Search expansion without a model (DECISIONS D-043). Run:  python -m tests.test_query_expansion

Offline: the TEST-FIXTURE search provider replays saved results; no paid calls, no internet. Checks:
  [1] country / language detection from the location (non-U.S. only; U.S. and unknown → unchanged behaviour)
  [2] local-language and official-domain queries for a non-U.S. incident; none for a U.S. incident
  [3] long descriptive names are not searched as one exact phrase; short names still are
  [4] keyword discovery: recurring place names and phrases across several websites; generic words ignored;
      single-website words ignored; incident-anchored words (Ahrtal ← Ahr) become automatic aliases
  [5] relevance: compound words, other scripts and the country's own name are recognised (non-U.S. only);
      other years are not
  [6] end-to-end research run: keywords logged, extra queries run, still within the query limit, keywords saved,
      German-only results recognised as this incident, no keyword is stored as evidence
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="wfdqx_"))
os.environ["WFD_DATA_DIR"] = str(TMP / "data")
for k in ("ANTHROPIC_API_KEY", "TAVILY_API_KEY", "BRAVE_API_KEY", "OPENAI_API_KEY", "WFD_PASSWORD"):
    os.environ.pop(k, None)
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS " if cond else "  FAIL ") + name + (f"  — {detail}" if detail and not cond else ""))


AHR = {"name": "Ahr valley disaster flood", "location": "germany Ahr valley", "date_text": "july 15 2021",
       "aliases": "", "identity_json": "{}"}
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
    {"url": "https://onlyone.example.org/x", "title": "Ahr valley 2021 Zwischenbilanz", "snippet": "Ahr valley", "match": []},
]


def main():
    from app.search import expansion as ex
    from app import research

    print("\n[1] Country and language from the location")
    de = ex.detect_country("germany Ahr valley")
    check("Germany recognised (German, .de, NINA/KATWARN)", de and de["code"] == "DE" and de["lang"] == "de"
          and de["site"] == ".de" and "KATWARN" in de["systems"], str(de))
    check("native name recognised (Deutschland)", (ex.detect_country("Ahrweiler, Deutschland") or {}).get("code") == "DE")
    check("non-Latin name recognised (日本)", (ex.detect_country("熊本県, 日本") or {}).get("code") == "JP")
    check("U.S. location → no profile (existing behaviour)", ex.detect_country("Boulder County, Colorado") is None
          and ex.detect_country("Kerr County, Texas, USA") is None)
    check("'us' inside a word is not the U.S. (Belarus → no false match)", ex.detect_country("Minsk, Belarus") is None)

    print("\n[2] Local queries")
    q = ex.localized_templates(AHR, de, "2021")
    texts = " | ".join(x[1] for x in q)
    check("German hazard + warning words are used", "Hochwasser" in texts and "Warnung" in texts, texts)
    check("inquiry / final report words are used", "Untersuchungsausschuss" in texts and "Abschlussbericht" in texts)
    check("official domain query", "site:.de" in texts)
    check("national warning systems are searched", "NINA" in texts and "KATWARN" in texts)
    check("the place is used without the country name", all("germany" not in x[1].lower() for x in q), texts)
    check("no extra queries for a U.S. incident", ex.localized_templates(
        {"name": "Marshall Fire", "location": "Boulder County, Colorado"}, None, "2021") == [])
    check("every local query is labelled as such in the search log",
          all(x[0].startswith("local") for x in q))

    print("\n[3] Exact-phrase rule")
    check("long descriptive name is not quoted", '"' not in research.core_query(AHR), research.core_query(AHR))
    check("short name is still an exact phrase", research.core_query(
        {"name": "Marshall Fire", "location": "Boulder County, Colorado", "date_text": "2021"}).startswith('"Marshall Fire"'))

    print("\n[4] Keyword discovery")
    t = research.case_terms(AHR)
    res = [dict(r) for r in RESULTS]
    for r in res:
        r["identity_score"] = research.identity_score(f"{r['title']} {r['snippet']} {r['url']}", t)[0]
    k1 = ex.discover_keywords(res, t)
    terms1 = [k["term"] for k in k1]
    check("place names that recur on several websites are found", "Ahrweiler" in terms1 and "Ahrtal" in terms1, str(terms1))
    check("multi-word place names stay together (Bad Neuenahr)", "Bad Neuenahr" in terms1 and "Bad" not in terms1, str(terms1))
    check("anchored words become aliases (Ahrtal ← Ahr), others do not",
          all(k["anchored"] for k in k1 if k["term"] in ("Ahrtal", "Ahrweiler")) and
          not any(k["anchored"] for k in k1 if k["term"] == "Bad Neuenahr"), str(k1))
    check("generic words are not keywords", not any(k["term"].lower() in ("warning", "warnung", "flood", "residents", "people")
                                                   for k in k1), str(terms1))
    check("a word from only one website is ignored", "Zwischenbilanz" not in terms1)
    t2 = {**t, "aliases": t["aliases"] + [research.sig_tokens(k["term"]) for k in k1 if k["anchored"]]}
    for r in res:
        r["identity_score"] = research.identity_score(f"{r['title']} {r['snippet']} {r['url']}", t2)[0]
    k2 = ex.discover_keywords(res, t2)
    check("second pass finds terms from German-only results (Flutkatastrophe)",
          "Flutkatastrophe" in [k["term"] for k in k2], str(k2))
    dq = ex.discovery_queries(k1, AHR, de, "2021")
    check("discovered keywords become queries with year and local warning word",
          any(x[1] == "Ahrweiler 2021 Warnung" for x in dq) and all(x[0].startswith("discovered keyword") for x in dq), str(dq))
    check("a report query is built from the incident's own local name",
          any("Abschlussbericht" in x[1] for x in dq), str(dq))

    print("\n[5] Relevance recognition")
    german = ("Die Flutkatastrophe im Ahrtal am 14. Juli 2021: Der Kreis Ahrweiler in Deutschland löste den "
              "Katastrophenalarm erst spät aus.")
    before = research.identity_score(german, t)[0]
    case_auto = {**AHR, "identity_json": json.dumps({"auto_aliases": ["Ahrtal", "Ahrweiler"]})}
    after = research.identity_score(german, research.case_terms(case_auto))[0]
    check("German source is relevant once aliases are known (≥ 0.6)", after >= 0.6, f"{before} → {after}")
    check("compound word counts for its first part (Ahr → Ahrtal)", research._hit("ahr", {"ahrtal"}))
    us = research.case_terms({"name": "Camp Fire", "location": "Butte County, California", "date_text": "2018"})
    check("U.S. cases keep exact word matching (Camp ≠ campus)", us["compound"] is False and
          research.identity_score("campus fires in Butte County 2018", us)[1].startswith("name 0%"),
          research.identity_score("campus fires in Butte County 2018", us)[1])
    check("Deutschland counts as Germany", "deutschland" in research.case_terms(AHR)["loc_alt"].get("germany", []))
    check("another flood in another year is not relevant",
          research.identity_score("Hochwasser an der Elbe 2002 in Dresden", research.case_terms(case_auto))[0] < 0.4)
    check("non-Latin words are kept as words (not dropped as before)", research.sig_tokens("Kumamoto 熊本 地震") == ["kumamoto", "熊本", "地震"])

    print("\n[6] End-to-end research run (TEST-FIXTURE search, no model)")
    from app import db, jobs
    from app.config import DEFAULT_SETTINGS
    from app.server import bootstrap_schema
    db.conn()
    bootstrap_schema()
    from app import coding
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
    check("location recognised in the run log", "recognised as DE" in log, log[:300])
    check("user alias is searched", any(p.startswith("alias:") for p in purposes), str(purposes))
    check("local-language queries ran", sum(1 for p in purposes if p.startswith("local")) >= 4, str(purposes))
    check("discovered keywords are logged as search leads, not evidence",
          "discovered keywords (search leads only, not evidence)" in log and "Ahrweiler" in log, log[-400:])
    check("discovered-keyword queries ran", any(p.startswith("discovered keyword") for p in purposes), str(purposes))
    check("still within the per-run query limit", len(qs) <= int(s["max_queries"]), f"{len(qs)} queries")
    ident = json.loads(db.q1("SELECT identity_json FROM cases WHERE id=?", (cid,))["identity_json"])
    check("keywords and automatic aliases are saved with the case",
          "Ahrweiler" in ident.get("auto_aliases", []) and ident.get("discovered_keywords"), str(ident)[:300])
    check("no keyword was stored as a source or passage",
          db.q1("SELECT COUNT(*) n FROM passages WHERE case_id=?", (cid,))["n"] == 0)
    os.environ.pop("WFD_TEST_FIXTURE", None)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED:", *FAIL, sep="\n  ")
        sys.exit(1)


if __name__ == "__main__":
    main()
