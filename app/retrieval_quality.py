"""Retrieval-quality report for one case (D-047). Read-only: it counts what is already saved (search log, sources,
passages) and never searches, fetches, calls a model or writes anything.

It answers "what did the search find, in which languages, from which kinds of bodies, and where are the gaps?".
It does NOT measure what exists: a gap means "nothing usable saved", not "no such document exists".

Language: the declared language (web pages only, D-045) when present; otherwise an estimate from the saved text by
counting common function words of a few languages (local and deterministic). Estimates are labelled as such.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from urllib.parse import urlparse

from . import db
from .search.expansion import AUTHORITIES, detect_country, detect_de_state

USABLE = ("full_text", "partial")
GROUPS = [("aar", "After-action reports", ("aar",)), ("gov", "Government and regulatory", ("government", "regulatory")),
          ("legis", "Legislative", ("legislative",)), ("acad", "Academic and technical", ("academic", "ngo_technical")),
          ("media", "News media", ("media",)), ("other", "Other / unclassified", ())]
LANG_NAMES = {"en": "English", "de": "German", "fr": "French", "es": "Spanish", "it": "Italian", "nl": "Dutch",
              "pt": "Portuguese", "et": "Estonian", "ro": "Romanian", "ja": "Japanese", "zh": "Chinese", "ko": "Korean"}
# frequent short function words; a text is assigned the language with the most hits, if clearly ahead
FUNCTION_WORDS = {
    "en": "the and of to in is that for was with are on by this from have were which".split(),
    "de": "der die das und ist nicht mit den von zu auf für eine wurde sich auch bei werden".split(),
    "fr": "le la les et des est une pour dans que qui sur pas par avec sont".split(),
    "es": "el la los las y del que en por con para una es se fue".split(),
    "it": "il la di che è per una sono con del della non gli".split(),
    "nl": "de het een van en is dat op voor niet met zijn wordt".split(),
    "pt": "o os de que do da em para com uma não foi são".split(),
    "et": "ja on ei et see oli kui ka mis või kes ning seda".split(),
    "ro": "și este în care nu pentru cu din au fost una mai sunt".split(),
}


def guess_language(text: str) -> str | None:
    words = re.findall(r"[^\W\d_]+", (text or "")[:6000].lower())
    if len(words) < 40:
        return None
    cnt = Counter(words)
    scores = sorted(((sum(cnt[w] for w in ws), lang) for lang, ws in FUNCTION_WORDS.items()), reverse=True)
    (best, lang), (second, _) = scores[0], scores[1]
    if best < 8 or best < 1.5 * max(second, 1):
        return None
    return lang


def _group(t: str) -> str:
    return next((k for k, _, ts in GROUPS if t in ts), "other")


def _host(s: dict) -> str:
    return urlparse((s.get("final_url") or s.get("url") or "").lower()).netloc.removeprefix("www.")


def _purpose_group(p: str) -> str:
    p = (p or "").lower()
    for pre, label in (("authority", "Official bodies (site-restricted)"), ("local terms", "Specialist local terms"),
                       ("local language", "Local-language queries"), ("local:", "Local official domain / warning systems"),
                       ("alias", "Aliases typed by the user"), ("keyword", "Discovered keywords"), ("discovered", "Discovered keywords"),
                       ("follow", "Follow-up (evidence gaps)"), ("gap", "Follow-up (evidence gaps)")):
        if p.startswith(pre):
            return label
    return "Standard queries"


def report(case_id: int) -> dict:
    case = db.q1("SELECT * FROM cases WHERE id=?", (case_id,))
    country = detect_country(case.get("location") or "")
    srcs = db.q("SELECT * FROM sources WHERE case_id=? ORDER BY id", (case_id,))
    text_head = defaultdict(str)
    for p in db.q("SELECT source_id, text FROM passages WHERE case_id=? ORDER BY source_id, seq", (case_id,)):
        if len(text_head[p["source_id"]]) < 6000:
            text_head[p["source_id"]] += " " + p["text"]
    usable = lambda s: s["fetch_status"] == "ok" and (s.get("content_status") or "full_text") in USABLE

    # languages
    langs: dict[str, dict] = defaultdict(lambda: {"saved": 0, "usable": 0, "relevant": 0, "declared": 0, "estimated": 0})
    for s in srcs:
        decl = (s.get("language") or "").split("-")[0].lower()
        est = None if decl else guess_language(text_head.get(s["id"], ""))
        key = decl or est or "unknown"
        row = langs[key]
        row["saved"] += 1
        row["usable"] += int(usable(s))
        row["relevant"] += int(usable(s) and s.get("relevance_status") == "relevant")
        if decl or est:
            row["declared" if decl else "estimated"] += 1
    languages = [{"code": k, "name": LANG_NAMES.get(k, "Not known" if k == "unknown" else k), **v}
                 for k, v in sorted(langs.items(), key=lambda kv: (kv[0] == "unknown", -kv[1]["saved"]))]

    # document types
    types = []
    for k, label, _ in GROUPS:
        ms = [s for s in srcs if _group(s.get("source_type") or "") == k]
        types.append({"group": k, "label": label, "saved": len(ms), "usable": sum(usable(s) for s in ms),
                      "relevant": sum(1 for s in ms if usable(s) and s.get("relevance_status") == "relevant")})

    # queries: what each kind of query produced
    queries = db.q("SELECT id, purpose, query, status, result_count FROM search_queries WHERE case_id=?", (case_id,))
    res_by_q = defaultdict(set)
    for r in db.q("SELECT query_id, url FROM search_results WHERE case_id=?", (case_id,)):
        res_by_q[r["query_id"]].add(r["url"])
    by_url = {}
    for s in srcs:
        for u in (s.get("url"), s.get("final_url")):
            if u:
                by_url[u] = s
    yields = defaultdict(lambda: {"queries": 0, "failed": 0, "results": set(), "saved": set(), "usable": set(), "relevant": set()})
    for q in queries:
        y = yields[_purpose_group(q["purpose"])]
        y["queries"] += 1
        y["failed"] += int(q["status"] not in ("ok", None))
        for u in res_by_q[q["id"]]:
            y["results"].add(u)
            s = by_url.get(u)
            if s:
                y["saved"].add(s["id"])
                if usable(s):
                    y["usable"].add(s["id"])
                    if s.get("relevance_status") == "relevant":
                        y["relevant"].add(s["id"])
    query_yield = [{"kind": k, "queries": v["queries"], "failed": v["failed"], "results": len(v["results"]), "saved": len(v["saved"]),
                    "usable": len(v["usable"]), "relevant": len(v["relevant"])} for k, v in sorted(yields.items())]

    # official bodies (Germany for now)
    bodies = []
    if country and country["code"] in AUTHORITIES:
        st = detect_de_state(case.get("location") or "") if country["code"] == "DE" else None
        lst = list(AUTHORITIES[country["code"]])
        if country["code"] == "DE":
            lst += [{"name": f"State parliaments (Landtag){' — ' + st['code'] if st else ''}", "site": st["landtag"] if st else "landtag",
                     "kind": "legislative", "match": "landtag"}]
            lst += [{"name": f"State government — {st['code']}", "site": st["gov"], "kind": "government"}] if st else []
        for a in lst:
            match = a.get("match") or a["site"]
            searched = [q for q in queries if (q["purpose"] or "").startswith("authority:") and
                        (a["site"] in (q["query"] or "") or (match == "landtag" and "Landtag" in (q["purpose"] or "")))]
            hit = [s for s in srcs if ((match in _host(s)) if match == "landtag" else (_host(s) == a["site"] or _host(s).endswith("." + a["site"])))]
            bodies.append({"name": a["name"], "site": a["site"], "kind": a["kind"], "searched": len(searched),
                           "results": sum(len(res_by_q[q["id"]]) for q in searched), "saved": len(hit),
                           "usable": sum(usable(s) for s in hit),
                           "examples": [f"S{s['id']}" for s in hit[:5]]})

    # gaps — plain statements about what is saved, never about what exists
    gaps = []
    n_use = sum(usable(s) for s in srcs)
    g = {t["group"]: t for t in types}
    if srcs and not g["aar"]["usable"]:
        gaps.append({"en": "No after-action report with usable text is saved.", "zh": "没有保存到有可用正文的事后评估报告。"})
    if srcs and not g["gov"]["usable"]:
        gaps.append({"en": "No government or regulatory document with usable text is saved.", "zh": "没有保存到有可用正文的政府或监管文件。"})
    if srcs and not g["legis"]["usable"]:
        gaps.append({"en": "No legislative / inquiry document with usable text is saved.", "zh": "没有保存到有可用正文的立法或调查委员会文件。"})
    if country and country["lang"] != "en":
        loc = next((l for l in languages if l["code"] == country["lang"].split("-")[0]), None)
        if not loc or not loc["usable"]:
            gaps.append({"en": f"No {LANG_NAMES.get(country['lang'], country['lang'])}-language source with usable text is saved "
                               f"(declared or estimated).", "zh": f"没有保存到有可用正文的当地语言（{country['lang']}）来源（按声明或估计）。"})
    for b in bodies:
        if b["searched"] and not b["usable"]:
            gaps.append({"en": f"{b['name']} ({b['site']}) was searched {b['searched']}× ({b['results']} results) but no readable document from it is saved.",
                         "zh": f"已搜索 {b['name']}（{b['site']}）{b['searched']} 次（{b['results']} 条结果），但没有保存到这个机构的可读文档。"})
        elif not b["searched"] and not b["usable"]:
            gaps.append({"en": f"{b['name']} ({b['site']}) has not been searched in this case (older run, or limit reached).",
                         "zh": f"本案例还没有搜索过 {b['name']}（{b['site']}）（较早的运行，或已达到上限）。"})
    if srcs and n_use < 0.6 * len(srcs):
        gaps.append({"en": f"Only {n_use} of {len(srcs)} saved sources have usable text (the rest failed, were blocked or are error pages).",
                     "zh": f"已保存的 {len(srcs)} 条来源中只有 {n_use} 条有可用正文（其余读取失败、被拒或是错误页）。"})
    unk = next((l["saved"] for l in languages if l["code"] == "unknown"), 0)
    if unk:
        gaps.append({"en": f"The language of {unk} saved source(s) is not known (no declaration, too little text to estimate).",
                     "zh": f"{unk} 条已保存来源的语言未知（网页没有声明，正文太少无法估计）。"})
    if not any(s.get("content_status") for s in srcs) and srcs:
        gaps.append({"en": "Sources have not been checked with the current content rules; usable-text counts treat saved text as usable.",
                     "zh": "来源还没有按当前内容规则检查；“可用正文”暂时把所有已保存的正文都算作可用。"})
    return {"case_id": case_id, "country": country["code"] if country else None,
            "local_language": country["lang"] if country else None,
            "sources": len(srcs), "usable": n_use,
            "languages": languages, "types": types, "query_yield": query_yield, "official_bodies": bodies, "gaps": gaps,
            "note": "Counts what this case has saved. A gap means nothing usable is saved, not that no such document "
                    "exists. Nothing is searched, fetched or sent to a model to make this report."}
