"""Automated research pipeline for one incident.

Stages: identify → search → fetch → gaps → followup (repeat) → coding → review.
All state is in SQLite, search/fetch/model results are cached, so a restarted job resumes without paying twice.
Stopping because a limit was reached is reported as "research incomplete", never as evidence that something is absent.
"""
from __future__ import annotations

import json
import re
import time
from collections import Counter
from urllib.parse import urlparse

from . import db
from .config import DEFAULT_SETTINGS, load_pricing
from .ingest import (FetchError, classify_source, containment, content_hash, extract_file, extract_html,
                     extract_text_plain, fetch_url, make_passages, shingles)
from .search.providers import SearchError, get_provider

STAGES = ["identify", "search", "fetch", "gaps", "followup", "coding", "review"]
NAME_STOP = {"the", "of", "and", "in", "at", "on", "a", "an", "to", "for", "alert", "alerts", "warning", "warnings",
             "emergency", "failure", "incident", "event", "county", "city", "state"}
MONTHS = "january february march april may june july august september october november december".split()


class Budget(Exception):
    pass


class Cancelled(Exception):
    pass


# ----------------------------------------------------------------------------- identity helpers
def sig_tokens(s: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", (s or "").lower()) if t not in NAME_STOP and len(t) > 1]


def years_in(s: str) -> list[str]:
    return re.findall(r"\b(19[5-9]\d|20[0-4]\d)\b", s or "")


def case_terms(case: dict) -> dict:
    name_t = sig_tokens(case["name"])
    alias_t = [sig_tokens(a) for a in (case.get("aliases") or "").split(";") if a.strip()]
    loc_t = [t for t in sig_tokens(case["location"]) if len(t) > 2]
    yrs = sorted(set(years_in(" ".join([case.get("date_text") or "", case.get("date_start") or "", case.get("date_end") or ""]))))
    months = [m for m in MONTHS if m in (case.get("date_text") or "").lower()]
    return {"name": name_t, "aliases": alias_t, "loc": loc_t, "years": yrs, "months": months}


def identity_score(text: str, terms: dict, published: str = "") -> tuple[float, str]:
    low = (text or "").lower()
    toks = set(re.findall(r"[a-z0-9]+", low))
    name_hit = (sum(1 for t in terms["name"] if t in toks) / len(terms["name"])) if terms["name"] else 0
    for a in terms["aliases"]:
        if a:
            name_hit = max(name_hit, sum(1 for t in a if t in toks) / len(a))
    loc_hit = (sum(1 for t in terms["loc"] if t in toks) / len(terms["loc"])) if terms["loc"] else 0.5
    yrs = years_in(low + " " + (published or ""))
    yr_score, why_year = 0.5, "no year stated"
    if terms["years"]:
        if any(y in terms["years"] for y in yrs):
            yr_score, why_year = 1.0, "target year mentioned"
        elif yrs:
            later = [y for y in yrs if int(y) > int(max(terms["years"]))]
            earlier = [y for y in yrs if int(y) < int(min(terms["years"]))]
            if earlier and not later:
                yr_score, why_year = 0.0, f"only earlier years mentioned ({', '.join(sorted(set(earlier))[:3])})"
            else:
                yr_score, why_year = 0.35, f"other years mentioned ({', '.join(sorted(set(yrs))[:3])})"
    score = round(0.5 * name_hit + 0.3 * loc_hit + 0.2 * yr_score, 3)
    return score, f"name {name_hit:.0%}, location {loc_hit:.0%}, {why_year}"


def core_query(case: dict, with_year: bool = True) -> str:
    t = case_terms(case)
    yr = f" {t['years'][0]}" if with_year and t["years"] else ""
    return f"\"{case['name']}\" {case['location']}{yr}".strip()


INITIAL_TEMPLATES = [
    ("after-action report", "{core} after-action report"),
    ("after-action report (PDF)", "{core} after action review report filetype:pdf"),
    ("government documents", "{core} emergency alert site:.gov"),
    ("investigation / findings", "{core} investigation findings warning"),
    ("original alert / WEA / EAS", "{core} emergency alert wireless emergency alert"),
    ("corrections / cancellations", "{core} alert corrected OR cancelled OR retracted OR \"all clear\""),
    ("reforms / legislation", "{core} legislation OR reform OR \"new policy\" warning system"),
    ("hearings / meetings", "{core} hearing OR testimony OR commission meeting alerts"),
    ("academic / technical", "{core} warning study OR analysis OR report"),
    ("media coverage", "{core} warning failure residents"),
]


# ----------------------------------------------------------------------------- context
class Ctx:
    def __init__(self, job: dict):
        self.job = job
        self.id = job["id"]
        self.case = db.q1("SELECT * FROM cases WHERE id=?", (job["case_id"],))
        self.settings = {**DEFAULT_SETTINGS, **json.loads(self.case.get("settings_json") or "{}")}
        self.params = json.loads(job.get("params_json") or "{}")
        self.state = json.loads(job.get("state_json") or "{}")
        self.state.setdefault("done", [])
        self.state.setdefault("round", 0)
        self.state.setdefault("limits_hit", [])
        self.state.setdefault("started", time.time())
        self.provider = get_provider(self.settings.get("search_provider", "auto"))
        self.terms = case_terms(self.case)
        pr = load_pricing().get("search", {})
        self.search_unit = (pr.get(self.provider.name, {}) if self.provider else {}).get("usd_per_1000_queries")

    def save(self, **kw):
        kw.setdefault("state_json", json.dumps(self.state))
        kw["updated_at"] = time.time()
        db.update("jobs", self.id, kw)

    def log(self, level: str, msg: str):
        db.insert("job_log", {"job_id": self.id, "at": time.time(), "stage": self.state.get("stage", ""), "level": level,
                              "message": msg})

    def stage(self, name: str, progress: float, msg: str = ""):
        self.state["stage"] = name
        self.save(stage=name, progress=progress, message=msg)

    def check_cancel(self):
        r = db.q1("SELECT cancel_requested FROM jobs WHERE id=?", (self.id,))
        if r and r["cancel_requested"]:
            raise Cancelled()

    def elapsed_min(self) -> float:
        return (time.time() - self.state["started"]) / 60

    def spent(self) -> float:
        """Spend for the whole case, across every run (the budget is per case, not per run)."""
        from .coding import case_spent
        return case_spent(self.case["id"])

    def budget(self) -> float:
        return float(self.settings["budget_usd"])

    def next_query_cost(self) -> float:
        return (self.search_unit / 1000.0) if self.search_unit is not None else 0.0

    def queries_run(self) -> int:
        r = db.q1("SELECT COUNT(*) n FROM search_queries WHERE job_id=? AND status IN ('ok','error')", (self.id,))
        return r["n"]

    def limit(self, what: str):
        if what not in self.state["limits_hit"]:
            self.state["limits_hit"].append(what)
            self.log("warn", f"limit reached: {what} — research incomplete for remaining steps")
        raise Budget(what)

    def check_limits(self, kind: str):
        s = self.settings
        if self.elapsed_min() > float(s["time_limit_minutes"]):
            self.limit(f"time limit ({s['time_limit_minutes']} min)")
        if kind == "query" and self.queries_run() >= int(s["max_queries"]):
            self.limit(f"query limit ({s['max_queries']})")
        extra = self.next_query_cost() if kind == "query" else 0.0
        if self.spent() + extra > self.budget() + 1e-9:
            self.limit(f"case cost budget (${self.budget():.2f})")


# ----------------------------------------------------------------------------- search
def run_query(ctx: Ctx, query: str, purpose: str, round_no: int, page: int = 1, target_vars: list[str] | None = None) -> list[dict]:
    ctx.check_cancel()
    ctx.check_limits("query")
    prov = ctx.provider
    if page > 1 and not prov.supports_paging:
        return []
    key = f"search:{prov.name}:{query}:{page}:{ctx.settings['results_per_query']}"
    cached = db.cache_get(key)
    qid = db.insert("search_queries", {"case_id": ctx.case["id"], "job_id": ctx.id, "round": round_no, "purpose": purpose,
                                       "query": query, "page": page, "provider": prov.name, "status": "running",
                                       "result_count": 0, "target_vars": json.dumps(target_vars or []), "created_at": time.time()})
    try:
        if cached is not None:
            results = cached
            ctx.log("info", f"search (cached, no charge): {query} [p{page}]")
        else:
            results = prov.search(query, page=page, count=int(ctx.settings["results_per_query"]))
            db.cache_put(key, results)
            cost = (ctx.search_unit / 1000.0) if ctx.search_unit is not None else None
            db.insert("usage", {"case_id": ctx.case["id"], "job_id": ctx.id, "kind": "search", "provider": prov.name,
                                "model": None, "input_tokens": None, "output_tokens": None, "units": 1, "cost_usd": cost,
                                "estimated": 1, "at": time.time(), "note": query[:120]})
        db.update("search_queries", qid, {"status": "ok", "result_count": len(results)})
    except SearchError as e:
        db.update("search_queries", qid, {"status": "error", "error": str(e)[:300]})
        ctx.log("error", f"search failed: {query}: {e}")
        return []
    out = []
    for r in results:
        if not r.get("url"):
            continue
        sc, why = identity_score(f"{r.get('title','')} {r.get('snippet','')} {r.get('url','')}", ctx.terms, r.get("published", ""))
        db.insert("search_results", {"query_id": qid, "case_id": ctx.case["id"], "url": r["url"], "title": r.get("title", ""),
                                     "snippet": r.get("snippet", ""), "rank": r.get("rank"), "published": r.get("published", ""),
                                     "identity_score": sc})
        out.append({**r, "identity_score": sc, "identity_why": why, "purpose": purpose})
    return out


def stage_identify(ctx: Ctx):
    ctx.stage("identify", 0.05, "Confirming incident identity")
    if ctx.params.get("identity_confirmed"):
        ctx.log("info", "identity confirmed by user")
        return
    if not ctx.provider:
        ctx.log("warn", "No search provider configured: automatic identity check and discovery are unavailable. "
                        "Add BRAVE_API_KEY, TAVILY_API_KEY or SEARXNG_URL, or supply sources manually.")
        return
    results = []
    for q in [core_query(ctx.case), f"{ctx.case['name']} {ctx.case['location']} emergency alert",
              f"\"{ctx.case['name']}\"" + (f" {ctx.terms['years'][0]}" if ctx.terms["years"] else "")]:
        try:
            results += run_query(ctx, q, "identity check", 0)
        except Budget:
            break
    strong = [r for r in results if r["identity_score"] >= 0.55]
    # Group strong name matches by the year they mention to detect same-name incidents in other years/places
    groups = Counter()
    examples: dict[str, list] = {}
    for r in results:
        name_part = identity_score(f"{r.get('title','')} {r.get('snippet','')}", {**ctx.terms, "loc": [], "years": []})[0]
        if name_part < 0.45:
            continue
        ys = sorted(set(years_in(f"{r.get('title','')} {r.get('snippet','')} {r.get('published','')}")))
        for y in ys[:2] or ["(no year)"]:
            groups[y] += 1
            examples.setdefault(y, []).append({"title": r.get("title"), "url": r.get("url")})
    cands = [{"year": y, "count": n, "examples": examples[y][:3]} for y, n in groups.most_common(6) if n >= 2]
    target = ctx.terms["years"]
    other = [c for c in cands if c["year"] not in target and c["year"] != "(no year)"]
    ambiguous = (not target and len([c for c in cands if c["year"] != "(no year)"]) >= 2) or \
                (target and other and other[0]["count"] > 1.5 * max([c["count"] for c in cands if c["year"] in target] or [0]))
    ident = {"checked_at": time.time(), "n_results": len(results), "n_strong": len(strong), "candidates": cands,
             "target_years": target}
    db.update("cases", ctx.case["id"], {"identity_json": json.dumps(ident)})
    if ambiguous:
        ctx.log("warn", "Several incidents with this name appear in results — waiting for you to choose.")
        ctx.state["awaiting"] = "identity"
        ctx.save(status="needs_input", message="Choose the intended incident (same name appears for different years/places).")
        raise Budget("awaiting identity choice")
    ctx.log("info", f"identity check: {len(strong)} strong matches of {len(results)} results")


def gather(ctx: Ctx, templates, round_no: int) -> list[dict]:
    found = []
    pages = int(ctx.settings.get("pages_per_query", 2))
    for purpose, tmpl, *tv in templates:
        q = tmpl.replace("{core}", core_query(ctx.case))
        for page in range(1, pages + 1):
            try:
                found += run_query(ctx, q, purpose, round_no, page, tv[0] if tv else None)
            except Budget:
                return found
    return found


def stage_search(ctx: Ctx):
    ctx.stage("search", 0.15, "Searching for sources (multiple source types, beyond page 1)")
    if not ctx.provider:
        return []
    if ctx.search_unit is None and not ctx.provider.is_test:
        ctx.log("warn", f"No price is configured for search provider '{ctx.provider.name}', so search spending is not counted "
                        f"in the case budget; searches are limited by count only (max {ctx.settings['max_queries']} per run). "
                        f"Add the price under Settings → Pricing.")
    links = [l.strip() for l in re.split(r"[\s,;]+", ctx.case.get("known_links") or "") if l.strip().startswith("http")]
    for l in links:
        ctx.state.setdefault("seed_urls", []).append(l)
    return gather(ctx, INITIAL_TEMPLATES, 0)


# ----------------------------------------------------------------------------- fetching
TYPE_PRIORITY = {"aar": 0, "government": 1, "regulatory": 1, "legislative": 2, "academic": 3, "ngo_technical": 3, "media": 4}


def existing_urls(case_id: int) -> set[str]:
    rows = db.q("SELECT url, final_url FROM sources WHERE case_id=?", (case_id,))
    return {r["url"] for r in rows} | {r["final_url"] for r in rows if r["final_url"]}


def save_source(ctx_case_id: int, meta: dict, extracted: dict | None, fetch_status: str, error: str = "", terms=None) -> int:
    row = {"case_id": ctx_case_id, "url": meta.get("url"), "final_url": meta.get("final_url"), "title": meta.get("title") or "",
           "publisher": meta.get("publisher") or "", "published_date": meta.get("published") or "", "retrieved_at": time.time(),
           "origin": meta.get("origin", "search"), "found_via": meta.get("found_via", ""), "fetch_status": fetch_status,
           "fetch_error": error, "content_type": meta.get("content_type", ""), "file_path": meta.get("path", ""),
           "snippet": meta.get("snippet", ""), "relevance_status": "unchecked", "excluded": 0}
    if extracted is None:
        row["source_type"] = classify_source(meta.get("url", ""), meta.get("title", ""))
        return db.insert("sources", row)
    full = "\n".join(p for pg in extracted["pages"] for p in pg["paragraphs"])
    row.update({"title": row["title"] or extracted.get("title") or meta.get("url", ""),
                "publisher": row["publisher"] or extracted.get("publisher", "") or urlparse(meta.get("final_url") or meta.get("url") or "").netloc,
                "published_date": row["published_date"] or extracted.get("published", ""),
                "ocr_status": extracted.get("ocr_status"), "n_pages": extracted.get("n_pages"),
                "text_chars": len(full), "content_hash": content_hash(full) if full.strip() else None})
    row["source_type"] = classify_source(meta.get("final_url") or meta.get("url", ""), row["title"], full)
    if not full.strip():
        row["fetch_status"] = "failed"
        row["fetch_error"] = "no extractable text" + (f" ({extracted.get('ocr_status')})" if extracted.get("ocr_status") else "")
        return db.insert("sources", row)
    # exact duplicate?
    dup = db.q1("SELECT id FROM sources WHERE case_id=? AND content_hash=? AND duplicate_of IS NULL", (ctx_case_id, row["content_hash"]))
    if dup:
        row["duplicate_of"] = dup["id"]
    sid = db.insert("sources", row)
    passages = make_passages(extracted)
    with db.tx() as c:
        for i, p in enumerate(passages, start=1):
            c.execute("INSERT INTO passages (id,case_id,source_id,seq,page,para,text) VALUES (?,?,?,?,?,?,?)",
                      (f"S{sid}-P{i}", ctx_case_id, sid, i, p["page"], p["para"], p["text"]))
    dropped = passages[0].get("dropped_boilerplate", 0) if passages else 0
    db.update("sources", sid, {"n_passages": len(passages),
                               "ocr_status": (row.get("ocr_status") or "") + (f"; {dropped} boilerplate passage(s) (ads/navigation) not indexed" if dropped else "")})
    if not dup:
        mark_near_duplicates(ctx_case_id, sid, full)
    assess_relevance(ctx_case_id, sid, full, terms)
    return sid


_shingle_cache: dict[int, set] = {}


def source_shingles(sid: int) -> set:
    if sid not in _shingle_cache:
        txt = " ".join(r["text"] for r in db.q("SELECT text FROM passages WHERE source_id=? ORDER BY seq", (sid,)))
        _shingle_cache[sid] = shingles(txt)
    return _shingle_cache[sid]


def mark_near_duplicates(case_id: int, sid: int, full: str):
    """Flag syndicated/near-identical copies. The copy is linked to the more authoritative original
    (official > academic > media; PDF originals over HTML reprints; earlier retrieval breaks ties)."""
    mine = shingles(full)
    _shingle_cache[sid] = mine
    best, best_id = 0.0, None
    for o in db.q("SELECT id FROM sources WHERE case_id=? AND id<>? AND fetch_status='ok' AND duplicate_of IS NULL "
                  "AND near_duplicate_of IS NULL", (case_id, sid)):
        c = containment(mine, source_shingles(o["id"]))
        if c > best:
            best, best_id = c, o["id"]
    if not best_id or best < 0.6:
        return
    a = db.q1("SELECT id, source_type, content_type FROM sources WHERE id=?", (sid,))
    b = db.q1("SELECT id, source_type, content_type FROM sources WHERE id=?", (best_id,))

    def rank(x):
        return (TYPE_PRIORITY.get(x["source_type"], 5), 0 if x["content_type"] == "application/pdf" else 1, x["id"])
    original, copy = (a, b) if rank(a) < rank(b) else (b, a)
    db.update("sources", copy["id"], {"near_duplicate_of": original["id"], "similarity": round(best, 3)})


def assess_relevance(case_id: int, sid: int, full: str, terms=None):
    if terms is None:
        case = db.q1("SELECT * FROM cases WHERE id=?", (case_id,))
        terms = case_terms(case)
    head = full[:6000]
    sc, why = identity_score(head, terms)
    sc_full, why_full = identity_score(full[:60000], terms)
    s = max(sc, sc_full)
    status = "relevant" if s >= 0.6 else ("uncertain" if s >= 0.4 else "irrelevant")
    db.update("sources", sid, {"relevance_score": s, "relevance_status": status,
                               "relevance_reason": (why if sc >= sc_full else why_full)})


def fetch_candidates(ctx: Ctx, cands: list[dict], found_via: str = "search") -> int:
    ctx.stage("fetch", 0.35 + 0.05 * ctx.state["round"], "Retrieving full text and removing duplicates")
    have = existing_urls(ctx.case["id"])
    best: dict[str, dict] = {}
    for c in cands:
        u = c["url"].split("#")[0]
        if u in have:
            continue
        if u not in best or c["identity_score"] > best[u]["identity_score"]:
            best[u] = c
    for u in ctx.state.pop("seed_urls", []):
        if u not in have:
            best[u] = {"url": u, "title": "", "snippet": "", "identity_score": 1.0, "purpose": "user-supplied link", "origin": "manual_url"}
    ranked = sorted(best.values(), key=lambda c: (-round(c["identity_score"], 1),
                                                  TYPE_PRIORITY.get(classify_source(c["url"], c.get("title", "")), 5)))
    n = 0
    for c in ranked:
        ctx.check_cancel()
        fetched_so_far = db.q1("SELECT COUNT(*) n FROM sources WHERE case_id=? AND origin IN ('search','followed_link')",
                               (ctx.case["id"],))["n"]
        if fetched_so_far >= int(ctx.settings["max_fetch"]):
            ctx.limit(f"fetch limit ({ctx.settings['max_fetch']})")
        ctx.check_limits("fetch")
        if c["identity_score"] < 0.3:
            continue  # remains visible in the search log as "not fetched (weak identity match)"
        n += fetch_one(ctx, c["url"], {"title": c.get("title", ""), "snippet": c.get("snippet", ""),
                                       "published": c.get("published", ""), "origin": c.get("origin", "search"),
                                       "found_via": c.get("found_via") or f"{found_via}: {c.get('purpose','')}"})
    return n


def fetch_one(ctx: Ctx, url: str, meta: dict) -> int:
    meta = {**meta, "url": url}
    try:
        res = fetch_url(url)
        meta.update(res)
        if res["content_type"] == "application/pdf":
            ex = extract_file(res["path"])
        else:
            raw = open(res["path"], "rb").read()
            ex = extract_html(raw, res["final_url"])
        if db.q1("SELECT id FROM sources WHERE case_id=? AND final_url=?", (ctx.case["id"], res["final_url"])):
            return 0
        sid = save_source(ctx.case["id"], meta, ex, "ok", terms=ctx.terms)
        if ctx.settings.get("follow_links") and meta.get("origin") != "followed_link":
            queue_links(ctx, sid, ex.get("links", []))
        ctx.log("info", f"retrieved S{sid}: {meta.get('title') or url} ({res['content_type']})")
        return 1
    except FetchError as e:
        sid = save_source(ctx.case["id"], meta, None, "failed", str(e))
        ctx.log("warn", f"retrieval failed S{sid}: {url}: {e}")
        return 0
    except Exception as e:  # extraction bug or malformed file: record, do not crash the run
        sid = save_source(ctx.case["id"], meta, None, "failed", f"extraction error: {type(e).__name__}: {e}")
        ctx.log("warn", f"extraction failed S{sid}: {url}: {e}")
        return 0


LINK_HINT = re.compile(r"after[- ]action|\baar\b|report|findings|investigation|review|timeline|assessment|testimony|minutes|"
                       r"\.pdf($|\?)", re.I)


def queue_links(ctx: Ctx, sid: int, links: list[dict]):
    src = db.q1("SELECT relevance_status, final_url FROM sources WHERE id=?", (sid,))
    if not src or src["relevance_status"] != "relevant":
        return
    base_host = urlparse(src["final_url"] or "").netloc
    picked = []
    for l in links:
        u, t = l["url"], l.get("text", "")
        host = urlparse(u).netloc
        if not LINK_HINT.search(u + " " + t):
            continue
        official = host.endswith(".gov") or host.endswith(".us") or host.endswith(".mil") or host == base_host
        if not official and not u.lower().endswith(".pdf"):
            continue
        sc, _ = identity_score(t + " " + u, {**ctx.terms, "years": []})
        # relevance is re-checked on the full text after fetching, so only obviously unrelated links are skipped here
        picked.append({"url": u, "title": t, "snippet": "", "identity_score": max(sc, 0.35), "origin": "followed_link",
                       "found_via": f"link in S{sid}", "purpose": "followed link"})
    picked.sort(key=lambda x: -x["identity_score"])
    ctx.state.setdefault("link_queue", []).extend(picked[:4])


# ----------------------------------------------------------------------------- gaps
GENERIC_WORDS = {"message", "characteristics", "type", "status", "flag", "indicators", "assessment", "summary", "notes",
                 "or", "and", "the", "of", "level", "count", "source", "sources", "id", "details"}


def gap_queries(ctx: Ctx, gaps: list[dict], limit: int = 8) -> list[tuple]:
    from .retrieval import EXPANSIONS
    out, seen = [], set()
    for g in gaps:
        words = [w for w in g["name"].lower().split("_") if w and w not in GENERIC_WORDS][:3]
        extra = ""
        for w in words:
            for k, v in EXPANSIONS.items():
                if w.startswith(k[:5]):
                    extra = " ".join(v.split()[:3])
                    break
        q = "{core} " + " ".join(words) + (f" {extra}" if extra else "")
        if q in seen:
            continue
        seen.add(q)
        out.append((f"gap: {g['name']}", q, [g["name"]]))
        if len(out) >= limit:
            break
    return out


def stage_gaps(ctx: Ctx) -> list[dict]:
    from .coding import MODEL_CLASSES, schema_for_case
    from .retrieval import CorpusIndex, evidence_strength, load_case_passages, variable_query
    ctx.stage("gaps", 0.55 + 0.05 * ctx.state["round"], "Checking evidence gaps against the codebook")
    schema = schema_for_case(ctx.case)
    passages = load_case_passages(ctx.case["id"])
    fields = [f for f in schema["fields"] if f.get("field_class") in MODEL_CLASSES and not f.get("rule_missing")]
    if not passages:
        gaps = [{"name": f["name"], "strength": 0.0} for f in fields]
    else:
        from .retrieval import get_index
        idx = get_index(ctx.case["id"], passages)
        gaps = []
        for f in fields:
            hits = idx.search(variable_query(f), k=5)
            s = evidence_strength(hits, f)
            if s < 0.35:
                gaps.append({"name": f["name"], "strength": s})
    ctx.state["gaps"] = gaps
    ctx.log("info", f"evidence gaps: {len(gaps)} of {len(fields)} variables have weak evidence in {len(passages)} passages")
    return gaps


# ----------------------------------------------------------------------------- coding
def stage_coding(ctx: Ctx):
    from .coding import PROVIDER_DISPLAY, estimate, limit_needs, resolve_plan, run_coding_plan
    from .display import mode_display
    ctx.stage("coding", 0.85, "Coding and validating")
    mode = ctx.params.get("mode") or ctx.settings.get("coding_mode") or "single"
    resume = ctx.params.get("resume")  # continue ONE provider's stopped variables inside an earlier coding group
    if resume:
        from .llm.clients import make_client
        mode = resume.get("mode") or mode
        c = make_client(resume["provider"], ctx.settings.get("model_name", "claude-sonnet-5-5"), ctx.settings)
        plan, err = ([(c, resume.get("role") or "primary")], None) if c else \
            ([], f"Cannot resume {PROVIDER_DISPLAY.get(resume['provider'], resume['provider'])}: its API key is not configured.")
    else:
        plan, mode, err = resolve_plan(ctx.settings, mode)
    if err:
        ctx.state["awaiting"] = "provider"
        ctx.save(status="needs_input", message=err)
        raise Budget("model provider not configured")
    from .llm.clients import LLMError
    for c, _role in plan:  # free availability check (e.g. OpenAI GET /models/{model}) before estimating or paying
        if hasattr(c, "preflight"):
            try:
                c.preflight()
            except LLMError as e:
                if e.config_error:
                    ctx.state["awaiting"] = "provider"
                    ctx.save(status="needs_input", message=str(e)[:500])
                    raise Budget("model provider configuration error")
                ctx.log("warn", f"could not check {PROVIDER_DISPLAY.get(c.provider, c.provider)} model availability now ({str(e)[:160]}); will check again "
                                f"before the first paid call")
    variables = (resume or {}).get("variables") or ctx.params.get("variables")
    spent, budget = ctx.spent(), ctx.budget()
    remaining = max(0.0, budget - spent)
    ctx.state["coding_mode"] = mode
    runs = ctx.state.setdefault("provider_runs", {})
    for c, role in plan:  # shown on the Progress page with Stop / Resume buttons
        runs.setdefault(c.provider, {"status": "pending", "role": role, "model": c.model})
    if resume:
        ctx.state["resume_of"] = resume
    if plan:
        est = estimate(ctx.case, ctx.settings, variables, plan=plan)
        ctx.state["estimate"] = est
        ctx.state["budget"] = {"budget_usd": round(budget, 2), "spent_usd": round(spent, 4), "remaining_usd": round(remaining, 4)}
        for p in est["providers"]:
            ctx.log("info", f"estimate [{PROVIDER_DISPLAY.get(p['provider'], p['provider'])} · {p['model']}, "
                            f"{'cross-model review' if p['role'] == 'reviewer' else 'independent'}]: {p['calls']} call(s) "
                            f"({p['calls_uncached']} not cached), ~{p['input_tokens']:,} input tokens, cost "
                            f"${p['cost_low']}–${p['cost_high']} worst case")
        ctx.log("info", f"{mode_display(mode)}: combined worst case ${est['cost_high']}; case has spent ${spent:.2f} of ${budget:.2f}")
        for n in est.get("price_notes", []):
            ctx.log("warn", f"pricing: {n}")
        if est["cost_high"] is None:
            missing = ", ".join(p["model"] for p in est["providers"] if p["cost_high"] is None)
            ctx.state["awaiting"] = "price"
            ctx.save(status="needs_input", message=f"No price is configured for model {missing}, so the budget cannot be "
                                                   f"enforced. Add its price under Settings → Pricing (use 0 for a free local "
                                                   f"model) and resume, or code manually.")
            raise Budget("awaiting model price")
        needs = limit_needs(ctx.case["id"], ctx.settings, est)
        ctx.state["limit_needs"] = needs
        if needs and ctx.settings.get("require_approval_over_budget") and not ctx.params.get("approve_over_budget"):
            ctx.state["awaiting"] = "budget"
            parts = [f"{v['label']}: {v['current']} → needs {v['needed']}" for v in needs.values()]
            if "budget_usd" in needs:
                head = (f"Worst-case model cost ${est['cost_high']:.2f} exceeds this case's remaining budget "
                        f"${remaining:.2f} (spent ${spent:.2f} of ${budget:.2f}).")
            else:
                head = "This run could exceed a case limit."
            ctx.save(status="needs_input", message=f"{head} Limits to raise (explicit amounts): {'; '.join(parts)}. "
                                                   f"Raise them, or code manually.")
            raise Budget("awaiting budget approval")
        if (ctx.job.get("kind") == "research" and ctx.settings.get("pause_before_coding")
                and not ctx.params.get("coding_approved") and not resume):
            # Stage 2 of the estimate (D-036): research is done, nothing has been sent to a model. The owner sees the
            # exact estimate for the evidence actually found and decides whether to start paid coding.
            ctx.state["awaiting"] = "coding_approval"
            parts = [f"{PROVIDER_DISPLAY.get(p['provider'], p['provider'])}: {p['calls']} request(s), "
                     f"{p['calls_uncached']} new, up to ${p['cost_high']:.2f}" for p in est["providers"]]
            ctx.save(status="needs_input", message=(
                f"Research finished. Nothing has been sent to a model yet. Exact estimate for the evidence found — "
                f"{'; '.join(parts)}; combined worst case ${est['cost_high']:.2f} (case has spent ${spent:.2f} of "
                f"${budget:.2f}). Start coding, or stop here at no model cost."))
            raise Budget("awaiting coding approval")
        names = " + ".join(PROVIDER_DISPLAY.get(c.provider, c.provider) for c, _role in plan)
        ctx.log("info", f"coding with {names} (independent; same shared evidence; processed one after another); "
                        f"search and evidence are shared — nothing is searched again per provider")
    else:
        ctx.log("warn", "No AI coding provider configured — running local evidence retrieval only (manual coding mode).")
    # The cap always applies: approving raises the case budget to a set amount, it never removes the limit.
    def on_status(provider, status, **extra):
        r = ctx.state["provider_runs"].setdefault(provider, {})
        r.update({"status": status, **extra, "updated_at": time.time()})
        ctx.save()

    rep = run_coding_plan(ctx.case, ctx.settings, plan, ctx.id, ctx.log, (spent + remaining) if plan else None, variables,
                          cancelled=lambda: bool(db.q1("SELECT cancel_requested FROM jobs WHERE id=?", (ctx.id,))["cancel_requested"]),
                          mode=mode, group_id=(resume or {}).get("group_id"), on_status=on_status)
    ctx.state["coding_report"] = rep
    ctx.state["group_id"] = rep["group_id"]


# ----------------------------------------------------------------------------- orchestration
def coverage_report(ctx: Ctx) -> dict:
    cid = ctx.case["id"]
    srcs = db.q("SELECT fetch_status, relevance_status, duplicate_of, near_duplicate_of, excluded, ocr_status FROM sources WHERE case_id=?", (cid,))
    qs = db.q("SELECT status, round FROM search_queries WHERE case_id=?", (cid,))
    return {
        "queries_ok": sum(1 for x in qs if x["status"] == "ok"), "queries_failed": sum(1 for x in qs if x["status"] == "error"),
        "rounds": (max([x["round"] for x in qs]) if qs else 0),
        "sources_ok": sum(1 for s in srcs if s["fetch_status"] == "ok"),
        "sources_failed": sum(1 for s in srcs if s["fetch_status"] == "failed"),
        "exact_duplicates": sum(1 for s in srcs if s["duplicate_of"]),
        "near_duplicates": sum(1 for s in srcs if s["near_duplicate_of"]),
        "irrelevant": sum(1 for s in srcs if s["relevance_status"] == "irrelevant"),
        "uncertain": sum(1 for s in srcs if s["relevance_status"] == "uncertain"),
        "ocr_gaps": sum(1 for s in srcs if (s["ocr_status"] or "").startswith("ocr_unavailable")),
        "limits_hit": ctx.state.get("limits_hit", []),
        "automatic_search_ran": any(x["status"] == "ok" for x in qs) and not (ctx.provider and ctx.provider.is_test),
        "research_complete": bool(ctx.provider) and not ctx.provider.is_test and any(x["status"] == "ok" for x in qs)
                             and not ctx.state.get("limits_hit"),
        "gaps_remaining": [g["name"] for g in ctx.state.get("gaps", [])],
        "spent_usd": round(ctx.spent(), 4),
        "budget_usd": round(ctx.budget(), 2),
        "search_price_configured": ctx.search_unit is not None,
        "search_provider": ctx.provider.name if ctx.provider else None,
        "search_is_test_fixture": bool(ctx.provider and ctx.provider.is_test),
    }


def run_research(job: dict):
    ctx = Ctx(job)
    ctx.save(status="running", error=None)
    done = ctx.state["done"]
    try:
        if ctx.job["kind"] in ("research",):
            if "identify" not in done:
                stage_identify(ctx)
                done.append("identify"); ctx.save()
            if "search" not in done:
                try:
                    cands = stage_search(ctx)
                except Budget:
                    cands = []
                ctx.state["cands"] = [{k: c.get(k) for k in ("url", "title", "snippet", "published", "identity_score", "purpose")} for c in cands]
                done.append("search"); ctx.save()
            if "fetch" not in done:
                try:
                    fetch_candidates(ctx, ctx.state.get("cands", []))
                    q = ctx.state.pop("link_queue", [])
                    if q:
                        fetch_candidates(ctx, q, "followed link")
                except Budget:
                    pass
                ctx.state.pop("cands", None)
                done.append("fetch"); ctx.save()
            # gap-driven follow-up rounds
            while ctx.state["round"] < int(ctx.settings["max_search_rounds"]) and ctx.provider:
                gaps = stage_gaps(ctx)
                if not gaps:
                    break
                ctx.state["round"] += 1
                ctx.stage("followup", 0.6 + 0.05 * ctx.state["round"], f"Targeted follow-up search, round {ctx.state['round']}")
                before = db.q1("SELECT COUNT(*) n FROM sources WHERE case_id=? AND fetch_status='ok'", (ctx.case["id"],))["n"]
                try:
                    found = gather(ctx, gap_queries(ctx, gaps), ctx.state["round"])
                    fetch_candidates(ctx, found, "gap search")
                    q = ctx.state.pop("link_queue", [])
                    if q:
                        fetch_candidates(ctx, q, "followed link")
                except Budget:
                    ctx.save()
                    break
                after = db.q1("SELECT COUNT(*) n FROM sources WHERE case_id=? AND fetch_status='ok'", (ctx.case["id"],))["n"]
                ctx.save()
                if after == before:
                    ctx.log("info", "follow-up round found no new sources; stopping follow-up")
                    break
            stage_gaps(ctx)
            done.append("followup"); ctx.save()
        n_pass = db.q1("SELECT COUNT(*) n FROM passages WHERE case_id=?", (ctx.case["id"],))["n"]
        if ctx.job["kind"] != "research" and n_pass:
            stage_gaps(ctx)
        if n_pass == 0:
            msg = ("No source text is available yet. " + ("Automatic search found nothing retrievable. " if ctx.provider else
                   "No search provider is configured. ") + "Add links, upload files, or paste text on the Sources tab, then re-run.")
            ctx.state["coverage"] = coverage_report(ctx)
            ctx.save(status="needs_input", stage="fetch", message=msg)
            db.update("cases", ctx.case["id"], {"status": "needs_sources", "updated_at": time.time()})
            return
        stage_coding(ctx)
        ctx.state["coverage"] = coverage_report(ctx)
        cov = ctx.state["coverage"]
        why = ("" if cov["research_complete"] else
               " — research incomplete: " + ("; ".join(cov["limits_hit"]) if cov["limits_hit"] else
                                              "no real automatic web search in this run"))
        ctx.stage("review", 1.0, "Ready for human review" + why)
        ctx.save(status="done")
        db.update("cases", ctx.case["id"], {"status": "review", "updated_at": time.time()})
    except Budget as b:
        if ctx.state.get("awaiting"):
            return  # needs_input already saved
        ctx.state["coverage"] = coverage_report(ctx)
        ctx.save(status="done", message=f"Stopped: {b}. Research incomplete.")
    except Cancelled:
        ctx.state["coverage"] = coverage_report(ctx)
        ctx.save(status="cancelled", message="Cancelled by user. Completed work is kept.")
    except Exception as e:
        import traceback
        ctx.log("error", traceback.format_exc()[-1500:])
        ctx.save(status="failed", error=f"{type(e).__name__}: {e}")


def ingest_manual(case_id: int, kind: str, payload: dict) -> int:
    """Optional supplements: a URL, an uploaded file, or pasted text."""
    case = db.q1("SELECT * FROM cases WHERE id=?", (case_id,))
    terms = case_terms(case)
    if kind == "url":
        meta = {"url": payload["url"], "origin": "manual_url", "found_via": "added by user"}
        try:
            res = fetch_url(payload["url"])
            meta.update(res)
            ex = extract_file(res["path"]) if res["content_type"] == "application/pdf" else extract_html(open(res["path"], "rb").read(), res["final_url"])
            return save_source(case_id, meta, ex, "ok", terms=terms)
        except FetchError as e:
            return save_source(case_id, meta, None, "failed", str(e))
    if kind == "file":
        meta = {"url": "", "title": payload.get("title") or payload["filename"], "origin": "upload",
                "found_via": f"uploaded file: {payload['filename']}", "path": payload["path"],
                "content_type": payload.get("content_type", "")}
        try:
            ex = extract_file(payload["path"])
        except Exception as e:
            return save_source(case_id, meta, None, "failed", f"could not read file: {e}")
        if payload.get("url"):
            meta["url"] = payload["url"]
        return save_source(case_id, meta, ex, "ok", terms=terms)
    if kind == "text":
        meta = {"url": payload.get("url", ""), "title": payload.get("title") or "Pasted text", "origin": "paste",
                "found_via": "pasted by user", "published": payload.get("published", "")}
        return save_source(case_id, meta, extract_text_plain(payload["text"]), "ok", terms=terms)
    raise ValueError(kind)
