"""Source review rules (D-046): content validity, incident relevance, document type, topic tags, document groups.

Uses ONLY saved data (source metadata, search snippet, extracted passages) and local rules. Never searches, fetches,
downloads, calls a search service or a model, or starts analysis. Three assessments are kept separate:

1. content_status  — was usable document text obtained?   full_text | partial | no_usable_text | not_retrieved | interrupted
2. relevance_status — does the content concern the incident? relevant (directly) | background | uncertain (needs review)
                      | irrelevant | unchecked
3. source_type (+ type_subtype) — what kind of document is it?

Relevance is only assessed from usable text. No usable text → "uncertain" (needs review), never "irrelevant".
Every automatic label records the rule version and a reason; human labels (type_basis / relevance_basis = 'human') are
never changed by rules. Bulk changes to existing records go through `reassess_case` (dry run first, then apply), which
writes every change to `source_label_history` with the old value, new value, reason and who applied it.
"""
from __future__ import annotations

import json
import re
import time
from collections import defaultdict
from urllib.parse import urlparse

from . import db

RULE_VERSION = "SR-2026-11-13.2"  # .2: German specialist flood/storm words, German authority hosts (D-047)

# ----------------------------------------------------------------------------------------------- 1. content validity
# Messages that sites show INSTEAD of the document (loading failures, bot checks, logins, cookie walls, 404s).
ERROR_MARKERS = [
    r"a required part of this site couldn.?t load", r"this site can.?t be reached", r"enable javascript", r"javascript is (disabled|required)",
    r"please (turn|switch) on javascript", r"your browser (is not supported|does not support)", r"checking (if the site connection is secure|your browser)",
    r"verify(ing)? (you are|that you are) (a )?human", r"are you a robot", r"captcha", r"just a moment\.?\.?\.?",
    r"access (denied|forbidden)", r"403 forbidden", r"404 (error|not found)", r"page (not found|cannot be found|could not be found)",
    r"the requested (url|page) (was not found|could not be found)", r"sign in to (continue|view)", r"log ?in to (continue|view|read)",
    r"subscribe to (continue|read)", r"you have reached your (article|free article) limit", r"this content is (only )?available to subscribers",
    r"we use cookies", r"accept (all )?cookies", r"cookie (settings|preferences|consent)", r"service unavailable", r"temporarily unavailable",
    r"error occurred while processing", r"rate limit", r"too many requests",
    r"bitte aktivieren sie javascript", r"seite (wurde )?nicht gefunden", r"zugriff verweigert", r"wir verwenden cookies",
    r"cookies (akzeptieren|zulassen)", r"activez javascript", r"page introuvable", r"acceso denegado", r"página no encontrada",
]
_ERR = re.compile("|".join(ERROR_MARKERS), re.I)
_WORD = re.compile(r"[^\W\d_]+")


def _words(s: str) -> int:
    return len(_WORD.findall(s or ""))


def content_quality(src: dict, paragraphs: list[str]) -> tuple[str, str]:
    """(status, reason) from what was saved. A recorded failure keeps its recorded reason (no new diagnosis)."""
    if src.get("fetch_status") != "ok":
        err = (src.get("fetch_error") or src.get("fetch_status") or "").strip()
        if "server restarted while reading" in err:
            return "interrupted", "retrieval interrupted (recorded: " + err[:160] + ")"
        return "not_retrieved", "not retrieved (recorded: " + (err[:160] or "no reason recorded") + ")"
    paras = [p for p in paragraphs if p and p.strip()]
    if not paras:
        return "no_usable_text", "no text was saved for this source"
    err_paras = [p for p in paras if _ERR.search(p) and _words(p) < 80]
    good = [p for p in paras if p not in err_paras]
    good_words = sum(_words(p) for p in good)
    err_words = sum(_words(p) for p in err_paras)
    sentences = sum(len(re.findall(r"[.!?。](\s|$)", p)) for p in good)
    if err_paras and (good_words < 40 or err_words >= good_words):
        msg = re.sub(r"\s+", " ", err_paras[0])[:90]
        return "no_usable_text", f"saved text is a site message, not the document (“{msg}”)"
    if good_words < 12 or (good_words < 30 and sentences == 0):
        return "no_usable_text", f"only {good_words} word(s) of substantive text were saved"
    pages = int(src.get("n_pages") or 0)
    if good_words >= 700 or (pages >= 3 and good_words >= 400):
        return "full_text", f"document text available ({good_words:,} words{f', {pages} pages' if pages else ''})"
    return "partial", (f"short or partial text ({good_words} words) — may be an abstract, a notice or part of a page; "
                       "completeness not established")


USABLE_CONTENT = ("full_text", "partial")


# ----------------------------------------------------------------------------------------------- 2. incident relevance
def _hazard_terms(case: dict) -> list[str]:
    from .search.expansion import HAZARDS, LANG, detect_country, hazard_of
    hz = hazard_of(case.get("name", "")) or hazard_of(case.get("details", "") or "")
    terms = list(HAZARDS.get(hz, ())) if hz else ["disaster", "emergency"]
    country = detect_country(case.get("location") or "")
    if country and LANG.get(country["lang"]):
        w = LANG[country["lang"]]
        terms += (w["hazard"].get(hz, w["disaster"]) if hz else w["disaster"]).split()
        terms.append(w["disaster"])
        terms += [x for x in w.get("more", {}).get(hz, []) if x != "Pegel"]  # D-047 (a gauge page alone is not about the incident)
    if hz == "flood":
        terms += ["flut", "hochwasser", "überschwemmung", "inondation", "crue", "inundación", "alluvione", "overstroming"]
    return sorted({t.lower() for t in terms if len(t) >= 3})


def _place_tokens(terms: dict, case: dict) -> list[str]:
    from .search.expansion import detect_country
    country = detect_country(case.get("location") or "")
    cn = set(country["names"]) if country else set()
    loc = [t for t in terms.get("loc", []) if t not in cn and len(t) >= 3 and t not in ("valley", "county", "city", "region", "state")]
    try:
        auto = json.loads(case.get("identity_json") or "{}").get("auto_aliases") or []
    except ValueError:
        auto = []
    # automatic aliases count as place names only when built on a typed place word (Ahrtal, Ahrweiler ← Ahr)
    return sorted(set(loc) | {a.lower() for a in auto if " " not in a and any(a.lower().startswith(l) for l in loc)})


def _has(tok: str, low: str) -> bool:
    if not tok.isascii():
        return tok in low
    return re.search(rf"\b{re.escape(tok)}", low) is not None  # prefix match: ahr → ahrtal, ahrweiler; flood → flooding


def relevance_v2(case: dict, terms: dict, paragraphs: list[str], quality: str, title: str = "", snippet: str = "") -> tuple[str, str]:
    """(status, reason). Keyword counts are reported as keyword-match measures, not confidence scores."""
    if quality not in USABLE_CONTENT:
        pre = f"{title} {snippet}".lower()
        hint = ""
        places, hz = _place_tokens(terms, case), _hazard_terms(case)
        if pre.strip() and any(_has(p, pre) for p in places) and any(_has(h, pre) for h in hz):
            hint = "; preliminary (title/search snippet only): mentions the place and the hazard"
        return "uncertain", "needs review: no usable document text, so relevance was not assessed" + hint
    text = "\n".join(paragraphs)
    low = text.lower()
    places, hz = _place_tokens(terms, case), _hazard_terms(case)
    years = terms.get("years") or []
    place_hit = [p for p in places if _has(p, low)]
    hz_count = sum(len(re.findall(rf"\b{re.escape(h)}", low)) if h.isascii() else low.count(h) for h in hz)
    year_hit = any(re.search(rf"\b{y}\b", low) for y in years)
    cooc = sum(1 for p in paragraphs if any(_has(x, p.lower()) for x in places) and any(_has(h, p.lower()) for h in hz))
    words = _words(text)
    metrics = (f"keyword match: place {len(place_hit)}/{len(places) or 0}, hazard terms {hz_count}, "
               f"incident year {'mentioned' if year_hit else 'not mentioned'}, place+hazard together in {cooc} passage(s)")
    if not places:  # nothing place-specific to check against: do not guess
        return "uncertain", "needs review: the case location gives no place name to check; " + metrics
    if cooc >= 2 and (year_hit or cooc >= 4) or (cooc >= 1 and year_hit and hz_count >= 3):
        return "relevant", "directly relevant: discusses the hazard at the incident's place" + (" in the incident year" if year_hit else "") + "; " + metrics
    if not place_hit:
        if hz_count and year_hit:
            return "background", "background: the hazard in the incident year, but not this place; " + metrics
        if words >= 150:
            return "irrelevant", "irrelevant: the text never mentions the incident's place; " + metrics
        return "uncertain", "needs review: short text without the incident's place; " + metrics
    if hz_count == 0:
        if words >= 200:
            return "irrelevant", "irrelevant: mentions the place but never the hazard or the incident; " + metrics
        return "uncertain", "needs review: mentions the place, no hazard terms in a short text; " + metrics
    return "background", "background: mentions the place and the hazard, but not clearly this incident; " + metrics


TOPIC_RULES = {
    "warning_evacuation": r"\bwarn|alert|siren|evacuat|cell broadcast|katwarn|nina\b|warnung|alarm|evakuier|räumung",
    "organization_coordination": r"coordinat|crisis (staff|team)|command|emergency management|responsib|krisenstab|einsatzleitung|zuständig|koordin",
    "impacts_harms": r"\bdeath|fatalit|killed|died|injur|damage|destroy|victim|\btote|todesopfer|schäden|zerstör|opfer",
    "policy_remedial": r"\blaw\b|legislat|reform|inquiry|recommendation|lessons|gesetz|untersuchungsausschuss|empfehlung|enquete",
    "hazard_background": r"rainfall|precipitation|hydrolog|discharge|gauge|climate|forecast|niederschlag|pegel|abfluss|klima|vorhersage",
}


def topic_tags(paragraphs: list[str], quality: str) -> list[str]:
    """Optional, non-authoritative topic hints (≥ 3 matches). Not document type, not WFD coding."""
    if quality not in USABLE_CONTENT:
        return []
    low = "\n".join(paragraphs).lower()
    return [k for k, rx in TOPIC_RULES.items() if len(re.findall(rx, low)) >= 3]


# ----------------------------------------------------------------------------------------------- 3. document type
DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"'<>]+)", re.I)
ACADEMIC_HOSTS = r"copernicus\.org|mdpi\.com|springer|wiley|tandfonline|sciencedirect|elsevier|nature\.com|frontiersin|plos|sagepub|" \
                 r"cambridge\.org|academic\.oup|iwaponline|ascelibrary|ametsoc|agupubs|jstor|ssrn|arxiv|researchgate|zenodo|hal\.science|" \
                 r"osf\.io|preprints\.org|eartharxiv|essopenarchive|egusphere|semanticscholar|doi\.org|scielo|ieee|acm\.org|emerald|" \
                 r"inderscience|hindawi|cell\.com|science\.org|pnas\.org|bmj|thelancet|europepmc|ncbi\.nlm\.nih\.gov"
REPOSITORY_MARKERS = r"treesearch|/bitstream/|dspace|eprints|handle\.net|/handle/|repository|publishup|edoc\.|opus\.|escholarship|" \
                     r"digitalcommons|scholarworks|/record/|/items/|kar\.kent|repositorio|depositonce|elib\.dlr"
UNIVERSITY_HOST = r"\.edu$|\.edu\.|\.ac\.[a-z]{2}$|(^|\.)uni-[a-z-]+\.de$|(^|\.)tu-[a-z-]+\.de$|university|universit|univ\.|\.uni\.|kit\.edu|ethz\.ch|epfl\.ch|utwente|tudelft"
NEWS_HOSTS = r"tagesschau|swr\.de|wdr\.de|zdf\.de|br\.de|ndr\.de|mdr\.de|hr\.de|dw\.com|spiegel|zeit\.de|faz\.net|sueddeutsche|welt\.de|taz\.de|" \
             r"tagesspiegel|rnd\.de|focus\.de|n-tv\.de|stern\.de|merkur\.de|t-online|ksta\.de|general-anzeiger|rhein-zeitung|blick-aktuell|" \
             r"bbc\.|cnn\.com|reuters|apnews|nytimes|theguardian|washingtonpost|npr\.org|cbsnews|abcnews|nbcnews|foxnews|euronews|" \
             r"aljazeera|france24|lemonde|lefigaro|elpais|corriere|nos\.nl|err\.ee|postimees|digi24|hotnews|news\.|\.news$|zeitung|" \
             r"times\.|tribune|herald|gazette|kcra|ktvb|kmbc|kshb|kpcw|ksl\.com|kutv|denverite|9news|hoodline|sfist|wwltv|texastribune|" \
             r"patch\.com|usatoday|latimes|politico|axios|bloomberg|cnbc|independent\.co|telegraph|mirror\.co|express\.co|abc7|abc13|nbc|fox\d"
SOCIAL_HOSTS = r"facebook\.com|youtube\.com|youtu\.be|twitter\.com|x\.com|instagram|tiktok|linkedin|reddit|threads\.net|mastodon"
LEGIS_HOST = r"landtag|bundestag|bundesrat|parliament|parlament|legis|senate\.|congress\.gov|house\.gov|assembly|europarl|riigikogu|cdep\.ro|senat\.ro"
LEGIS_TITLE = r"untersuchungsausschuss|enquete|drucksache|plenarprotokoll|parliamentary inquiry|committee of inquiry|hearing before|" \
              r"\bhearing\b|\bbill\b|\bact of\b|legislation|senate bill|house bill|commission d.enqu[eê]te|comisi[oó]n de investigaci[oó]n"
AAR_TITLE = r"after[- ]action|after action review|\baar\b|lessons learned|lessons learnt|improvement plan|einsatznachbereitung|" \
            r"erfahrungsbericht|retour d.exp[eé]rience|\bretex\b|review of the (response|emergency)|evaluation of the (response|emergency)"
INTL_HOSTS = r"\.int$|undrr|preventionweb|ifrc|redcross|rotkreuz|worldbank|oecd|unu\.edu|reliefweb|wmo\.int|who\.int|un\.org|unisdr|gfdrr|" \
             r"copernicus\.eu|jrc\.ec|ec\.europa|dkkv|cedim|fema\.gov"
TOURISM = r"\bvisit|tourism|tourist|urlaub|ferien|wandern|hotel|travel|reise|sightseeing|discover the region"


def _official_host(host: str) -> bool:
    from .search.expansion import COUNTRIES
    if re.search(r"\.gov$|\.gov\.|\.mil$|\.gouv\.|\.gv\.at$|\.admin\.ch$|\.bund\.de$|\.gob\.|\.go\.jp$|\.go\.kr$|\.govt\.nz$|\.gc\.ca$|"
                 r"\.gov\.uk$|\.europa\.eu$|polizei|landkreis|kreis-|\.rlp\.de$|\.nrw\.de$|\.bayern\.de$|\.sachsen\.de$|\.hessen\.de$|"
                 r"\.niedersachsen\.de$|stadt-|\.state\.[a-z]{2}\.us$|\.(co|ci|city|county)\.[a-z]{2}\.us$|\.gov\.(ro|ee)$|\.ee$|\.ro$", host):
        # bare .ee / .ro only with an official word; checked below
        if re.search(r"\.(ee|ro)$", host) and not re.search(r"gov|valitsus|riik|ministerul|guvern|mai\.gov", host):
            return False
        return True
    from .search.expansion import AUTHORITIES, DE_STATES
    gov_sites = [a["site"] for lst in AUTHORITIES.values() for a in lst if a["kind"] == "government"] + [st["gov"] for st in DE_STATES.values()]
    if any(host == d or host.endswith("." + d) for d in gov_sites):  # D-047
        return True
    return any(host.endswith(c["site"]) and c["site"].count(".") >= 2 for c in COUNTRIES.values())


def classify_v2(url: str, title: str = "", text_head: str = "", publisher: str = "") -> tuple[str, str, str]:
    """(source_type, subtype, reason). Precedence (documented in DECISIONS D-046):
    1 explicit scholarly identity (DOI, journal/preprint platform, repository, article structure) → academic
    2 news outlet → media (a news story about a report stays a news story)
    3 explicit after-action title → aar
    4 legislature host or inquiry/bill title → legislative
    5 regulator → regulatory; official government host → government
    6 international / agency technical report → ngo_technical (shown with academic & technical)
    7 otherwise → unknown ("Other / Unclassified": tourism, encyclopedia, blogs, social, anything uncertain) — never
      media by default. The search query that found a source is never used."""
    u = (url or "").lower()
    host = urlparse(u).netloc.removeprefix("www.")
    t = (title or "").lower()
    head = (text_head or "")[:4000].lower()
    pub = (publisher or "").lower()
    doi = DOI_RE.search(u) or DOI_RE.search(head[:2500])
    structure = bool(re.search(r"\babstract\b", head) and re.search(r"\b(keywords|introduction|references|et al\.)", head))
    if doi or re.search(ACADEMIC_HOSTS, host) or re.search(REPOSITORY_MARKERS, u) or re.search(r"journal of|proceedings of", f"{t} {pub}") \
            or (structure and re.search(UNIVERSITY_HOST, host)) or (structure and not re.search(NEWS_HOSTS, host)):
        if re.search(r"arxiv|preprint|eartharxiv|essopenarchive|egusphere|-discuss|discussions|preprints\.org", f"{u} {t} {head[:600]}"):
            sub = "preprint"
        elif re.search(r"\bthesis\b|dissertation|masterarbeit|doktorarbeit|bachelorarbeit", f"{t} {head[:1500]}"):
            sub = "thesis"
        elif re.search(r"technical report|report no|working paper|discussion paper|technical note", f"{t} {head[:1500]}"):
            sub = "technical_report"
        elif re.search(REPOSITORY_MARKERS, u) and not doi and not re.search(ACADEMIC_HOSTS, host):
            sub = "repository_copy"
        else:
            sub = "journal_article" if (doi or re.search(ACADEMIC_HOSTS, host) or "journal" in f"{t} {pub}") else "research_paper"
        why = ("DOI" if doi else "scholarly platform" if re.search(ACADEMIC_HOSTS, host) else
               "repository address" if re.search(REPOSITORY_MARKERS, u) else "article structure (abstract, references)")
        return "academic", sub, f"academic: {why}" + (f" (hosted on {host})" if host and _official_host(host) else "")
    if re.search(SOCIAL_HOSTS, host):
        return "unknown", "social_media", f"other: social media platform ({host})"
    if re.search(NEWS_HOSTS, host):
        return "media", "news", f"news media: news outlet ({host})"
    if re.search(AAR_TITLE, t):
        return "aar", "", "after-action report: title states a review of the incident or response"
    if re.search(LEGIS_HOST, host) or re.search(LEGIS_TITLE, t):
        return "legislative", "", "legislative: " + (f"legislature website ({host})" if re.search(LEGIS_HOST, host) else "inquiry / bill title")
    if host.endswith("fcc.gov") or (re.search(r"docket|public notice|rulemaking", f"{t} {head[:1500]}") and _official_host(host)):
        return "regulatory", "", f"regulatory: regulator notice ({host})"
    if host and _official_host(host):
        return "government", "", f"government: official government website ({host})"
    if re.search(INTL_HOSTS, host) or (host.endswith(".org") and re.search(r"technical report|working paper|policy brief|assessment report", f"{t} {head[:1500]}")):
        return "ngo_technical", "technical_report", f"technical report: international / agency source ({host})"
    if re.search(r"wikipedia|wikimedia|britannica", host):
        return "unknown", "encyclopedia", "other: encyclopedia"
    if re.search(TOURISM, f"{host} {t}"):
        return "unknown", "tourism", "other: tourism / travel page"
    if not host:
        return "unknown", "", "unclassified: no address (upload or pasted text) — set the type by hand"
    return "unknown", "", f"unclassified: not enough saved information to tell the document type ({host})"


# ----------------------------------------------------------------------------------------------- 4. document groups
def _norm_title(t: str) -> str:
    words = re.findall(r"[^\W_]+", (t or "").lower())
    return " ".join(words) if len(words) >= 6 else ""


def group_keys(src: dict, head: str, quality: str) -> list[str]:
    """Keys that identify the SAME document across formats / repository copies. Error text and site templates are never
    used: content hashes only count for usable content."""
    keys = []
    d = DOI_RE.search((src.get("url") or "")) or DOI_RE.search((head or "")[:2500])
    if d:
        keys.append("doi:" + d.group(1).lower().rstrip(".,;)"))
    nt = _norm_title(src.get("title") or "")
    if nt:
        keys.append("title:" + nt)
    if quality in USABLE_CONTENT and src.get("content_hash"):
        keys.append("hash:" + src["content_hash"])
    return keys


# ----------------------------------------------------------------------------------------------- assessment + apply
def _paragraphs(sid: int) -> list[str]:
    return [p["text"] for p in db.q("SELECT text FROM passages WHERE source_id=? ORDER BY seq", (sid,))]


def assess_source(src: dict, case: dict, terms: dict, paragraphs: list[str] | None = None) -> dict:
    """All automatic assessments for one saved source (no I/O beyond the local database)."""
    paras = _paragraphs(src["id"]) if paragraphs is None else paragraphs
    quality, qreason = content_quality(src, paras)
    head = "\n".join(paras)[:4000]
    stype, sub, treason = classify_v2(src.get("final_url") or src.get("url") or "", src.get("title") or "",
                                      head if quality in USABLE_CONTENT else "", src.get("publisher") or "")
    rel, rreason = relevance_v2(case, terms, paras, quality, src.get("title") or "", src.get("snippet") or "")
    return {"content_status": quality, "content_reason": qreason, "source_type": stype, "type_subtype": sub,
            "type_reason": treason, "relevance_status": rel, "relevance_reason": rreason,
            "topic_tags": json.dumps(topic_tags(paras, quality)), "_keys": group_keys(src, head, quality)}


def _human_type(src: dict) -> bool:
    if src.get("type_basis") == "human":
        return True
    if src.get("type_basis"):  # assessed by these rules before
        return False
    # Before 2026-11-13 type corrections were not recorded. A stored type that differs from what the old rule gives for
    # the same address and title was most likely set by a person: keep it (flagged as 'probably human').
    from .ingest import classify_source
    if not src.get("source_type"):
        return False
    paras = _paragraphs(src["id"])
    heads = ["", "\n".join(paras)[:1500], (paras[0] if paras else "")[:1500], (src.get("snippet") or "")]
    urls = {src.get("url") or "", src.get("final_url") or src.get("url") or ""}
    # if the old rule gives the stored type for any plausible input it saw, the label was automatic
    return not any(classify_source(u, src.get("title") or "", h) == src["source_type"] for u in urls for h in heads)


def _human_relevance(src: dict) -> bool:
    return src.get("relevance_basis") == "human" or (src.get("relevance_reason") or "").startswith("set by reviewer")


def reassess_case(case_id: int, apply: bool = False, actor: str = "", examples: int = 6) -> dict:
    """Dry run (apply=False) or apply the current rules to every saved source of a case. Human labels are never
    changed. Never deletes a source; never changes a selection (excluded) or a finished analysis."""
    from .research import case_terms
    case = db.q1("SELECT * FROM cases WHERE id=?", (case_id,))
    terms = case_terms(case)
    srcs = db.q("SELECT * FROM sources WHERE case_id=? ORDER BY id", (case_id,))
    changes, ex = defaultdict(int), defaultdict(list)
    kept_human = {"type": 0, "relevance": 0}
    planned: list[tuple[int, dict, dict]] = []
    new_status: dict[int, str] = {}
    keys_by_src: dict[int, list[str]] = {}
    for s in srcs:
        a = assess_source(s, case, terms)
        keys_by_src[s["id"]] = a.pop("_keys")
        new_status[s["id"]] = a["content_status"]
        upd = {}
        for f in ("content_status", "content_reason", "topic_tags"):
            if (s.get(f) or "") != (a[f] or ""):
                upd[f] = a[f]
        if _human_type(s):
            kept_human["type"] += 1
            if not s.get("type_basis"):
                upd["type_basis"] = "human"
                upd["type_reason"] = "kept: probably a human correction made before changes were recorded"
        elif (s.get("source_type"), s.get("type_subtype") or "") != (a["source_type"], a["type_subtype"]) or s.get("type_basis") != "auto":
            upd.update(source_type=a["source_type"], type_subtype=a["type_subtype"], type_reason=a["type_reason"], type_basis="auto")
        if _human_relevance(s):
            kept_human["relevance"] += 1
            if s.get("relevance_basis") != "human":
                upd["relevance_basis"] = "human"
        elif s.get("relevance_status") != a["relevance_status"] or s.get("relevance_basis") != "auto":
            upd.update(relevance_status=a["relevance_status"], relevance_reason=a["relevance_reason"], relevance_basis="auto")
        if upd:
            upd["rule_version"] = RULE_VERSION
            planned.append((s["id"], s, upd))
    # duplicates: a duplicate link is only kept when BOTH sides have usable content
    by_id = {s["id"]: s for s in srcs}
    for s in srcs:
        for f in ("duplicate_of", "near_duplicate_of"):
            o = s.get(f)
            if o and (new_status.get(s["id"]) not in USABLE_CONTENT or new_status.get(o) not in USABLE_CONTENT):
                entry = next((p for p in planned if p[0] == s["id"]), None)
                if not entry:
                    entry = (s["id"], s, {"rule_version": RULE_VERSION})
                    planned.append(entry)
                entry[2][f] = None
                if f == "near_duplicate_of":
                    entry[2]["similarity"] = None
    # document groups (display only)
    parent = {s["id"]: s["id"] for s in srcs}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    owner: dict[str, int] = {}
    for sid, ks in keys_by_src.items():
        for k in ks:
            if k in owner:
                parent[find(sid)] = find(owner[k])
            else:
                owner[k] = sid
    for s in srcs:
        root = find(s["id"])
        members = [x for x in parent if find(x) == root]
        g = f"G{min(members)}" if len(members) > 1 else None
        if (s.get("doc_group") or None) != g:
            entry = next((p for p in planned if p[0] == s["id"]), None)
            if not entry:
                entry = (s["id"], s, {"rule_version": RULE_VERSION})
                planned.append(entry)
            entry[2]["doc_group"] = g
    # summary
    LABEL = {"content_status": "content", "source_type": "document type", "relevance_status": "relevance",
             "duplicate_of": "duplicate link removed", "near_duplicate_of": "near-duplicate link removed", "doc_group": "document group"}
    for sid, s, upd in planned:
        for f, lab in LABEL.items():
            if f in upd and (s.get(f) or None) != (upd[f] or None):
                key = f"{lab}: {s.get(f) or '—'} → {upd[f] or '—'}" if f not in ("duplicate_of", "near_duplicate_of", "doc_group") else lab
                changes[key] += 1
                if len(ex[lab]) < examples:
                    ex[lab].append({"source": f"S{sid}", "title": (s.get("title") or s.get("url") or "")[:90],
                                    "before": s.get(f), "after": upd[f],
                                    "reason": upd.get({"source_type": "type_reason", "relevance_status": "relevance_reason",
                                                       "content_status": "content_reason"}.get(f, ""), "")})
    # analyses that used content now found unusable (flag only; never rerun or rewritten)
    bad = {sid for sid, st in new_status.items() if st not in USABLE_CONTENT}
    flagged = []
    for r in db.q("SELECT r.id, r.job_id, r.provider, e.sources_json FROM runs r JOIN evidence_snapshots e ON e.id=r.evidence_snapshot_id "
                  "WHERE r.case_id=?", (case_id,)):
        used = set(json.loads(r["sources_json"] or "[]")) & bad
        if used:
            flagged.append({"run": r["id"], "provider": r["provider"], "sources": sorted(f"S{x}" for x in used)})
    summary = {"case_id": case_id, "rule_version": RULE_VERSION, "sources": len(srcs), "sources_changing": len(planned),
               "changes": dict(sorted(changes.items(), key=lambda kv: -kv[1])), "examples": dict(ex),
               "human_labels_kept": kept_human, "analyses_to_review": flagged, "applied": False,
               "note": "Local rules on saved data only: no search, no retrieval, no model. Selections, finished analyses and "
                       "human-approved values are not changed. Every change is recorded with the old value."}
    if apply:
        now = time.time()
        with db.tx() as c:
            for sid, s, upd in planned:
                for f, v in upd.items():
                    if f == "rule_version":
                        continue
                    old = s.get(f)
                    if (old or None) == (v or None):
                        continue
                    c.execute("INSERT INTO source_label_history (source_id, case_id, field, old_value, new_value, basis, "
                              "rule_version, reason, changed_by, at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                              (sid, case_id, f, None if old is None else str(old), None if v is None else str(v), "rule",
                               RULE_VERSION, "bulk reassessment of saved sources", actor or "", now))
                cols = ",".join(f"{k}=?" for k in upd)
                c.execute(f"UPDATE sources SET {cols} WHERE id=?", (*upd.values(), sid))
        summary["applied"] = True
    return summary


def assess_new_source(sid: int, case_id: int, terms: dict | None = None) -> None:
    """Applied when a source is first saved (no history needed: there is no previous automatic value)."""
    from .research import case_terms
    s = db.q1("SELECT * FROM sources WHERE id=?", (sid,))
    case = db.q1("SELECT * FROM cases WHERE id=?", (case_id,))
    a = assess_source(s, case, terms or case_terms(case))
    a.pop("_keys")
    upd = {**a, "type_basis": "auto", "relevance_basis": "auto", "rule_version": RULE_VERSION}
    if a["content_status"] not in USABLE_CONTENT:  # never link documents through error text or empty pages
        upd.update(duplicate_of=None, near_duplicate_of=None, similarity=None)
    db.update("sources", sid, upd)


def record_human(sid: int, field: str, new, actor: str, reason: str = "") -> None:
    s = db.q1("SELECT * FROM sources WHERE id=?", (sid,))
    db.insert("source_label_history", {"source_id": sid, "case_id": s["case_id"], "field": field,
                                       "old_value": None if s.get(field) is None else str(s.get(field)),
                                       "new_value": None if new is None else str(new), "basis": "human",
                                       "rule_version": None, "reason": reason or "", "changed_by": actor or "", "at": time.time()})
