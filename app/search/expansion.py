"""Search expansion without a model (D-043): country/language-aware queries and keyword discovery.

Everything here only builds SEARCH QUERIES. Nothing it produces is evidence: evidence still comes only from the full
text of sources that are actually read. Discovered keywords are logged in the search log so a researcher can see why a
query was run.

1. detect_country(): the case location → country profile (language, official web domain, local words, warning
   systems). No country recognised → the existing U.S.-oriented templates are used unchanged.
2. localized_templates(): extra queries in the local language and English for non-U.S. incidents.
3. discover_keywords(): terms that recur across the first-round results that match the incident (titles and snippets
   from several different websites), e.g. "Ahrtal", "Ahrweiler", "Flutkatastrophe" for the 2021 Ahr valley flood.
   Terms that contain a word of the incident name or place ("anchored", e.g. Ahrtal ← Ahr) also help recognise
   local-language sources as being about this incident (auto aliases).
"""
from __future__ import annotations

import re
from collections import defaultdict
from urllib.parse import urlparse

# --------------------------------------------------------------------------- languages: words used to build queries
# hazard words are matched on the English case name; each language lists the search words to use.
HAZARDS = {
    "flood": ("flood", "flooding", "flash flood", "inundation"),
    "wildfire": ("wildfire", "bushfire", "fire", "forest fire"),
    "storm": ("storm", "hurricane", "typhoon", "cyclone", "tornado"),
    "earthquake": ("earthquake", "quake"),
    "tsunami": ("tsunami",),
    "landslide": ("landslide", "mudslide", "debris flow"),
    "heat": ("heat wave", "heatwave", "heat"),
}

LANG = {
    "de": {"hazard": {"flood": "Hochwasser", "wildfire": "Waldbrand", "storm": "Unwetter", "earthquake": "Erdbeben",
                      "tsunami": "Tsunami", "landslide": "Erdrutsch", "heat": "Hitzewelle"},
           "disaster": "Katastrophe", "warning": "Warnung", "report": "Abschlussbericht",
           "inquiry": "Untersuchungsausschuss", "investigation": "Untersuchung", "sirens": "Sirenen",
           "evacuation": "Evakuierung"},
    "fr": {"hazard": {"flood": "inondation", "wildfire": "incendie de forêt", "storm": "tempête", "earthquake": "séisme",
                      "tsunami": "tsunami", "landslide": "glissement de terrain", "heat": "canicule"},
           "disaster": "catastrophe", "warning": "alerte", "report": "rapport", "inquiry": "commission d'enquête",
           "investigation": "enquête", "sirens": "sirènes", "evacuation": "évacuation"},
    "es": {"hazard": {"flood": "inundación", "wildfire": "incendio forestal", "storm": "tormenta", "earthquake": "terremoto",
                      "tsunami": "tsunami", "landslide": "deslizamiento", "heat": "ola de calor"},
           "disaster": "catástrofe", "warning": "alerta", "report": "informe", "inquiry": "comisión de investigación",
           "investigation": "investigación", "sirens": "sirenas", "evacuation": "evacuación"},
    "it": {"hazard": {"flood": "alluvione", "wildfire": "incendio boschivo", "storm": "tempesta", "earthquake": "terremoto",
                      "tsunami": "tsunami", "landslide": "frana", "heat": "ondata di calore"},
           "disaster": "disastro", "warning": "allerta", "report": "relazione", "inquiry": "commissione d'inchiesta",
           "investigation": "indagine", "sirens": "sirene", "evacuation": "evacuazione"},
    "nl": {"hazard": {"flood": "overstroming", "wildfire": "natuurbrand", "storm": "storm", "earthquake": "aardbeving",
                      "tsunami": "tsunami", "landslide": "aardverschuiving", "heat": "hittegolf"},
           "disaster": "ramp", "warning": "waarschuwing", "report": "rapport", "inquiry": "parlementaire enquête",
           "investigation": "onderzoek", "sirens": "sirenes", "evacuation": "evacuatie"},
    "pt": {"hazard": {"flood": "enchente", "wildfire": "incêndio florestal", "storm": "tempestade", "earthquake": "terremoto",
                      "tsunami": "tsunami", "landslide": "deslizamento", "heat": "onda de calor"},
           "disaster": "tragédia", "warning": "alerta", "report": "relatório", "inquiry": "comissão de inquérito",
           "investigation": "investigação", "sirens": "sirenes", "evacuation": "evacuação"},
    "ja": {"hazard": {"flood": "豪雨 洪水", "wildfire": "山火事", "storm": "台風", "earthquake": "地震", "tsunami": "津波",
                      "landslide": "土砂災害", "heat": "熱中症"},
           "disaster": "災害", "warning": "警報", "report": "検証報告書", "inquiry": "検証委員会", "investigation": "調査",
           "sirens": "防災無線", "evacuation": "避難指示"},
    "zh": {"hazard": {"flood": "洪水 暴雨", "wildfire": "山火", "storm": "台风", "earthquake": "地震", "tsunami": "海啸",
                      "landslide": "山体滑坡", "heat": "高温"},
           "disaster": "灾害", "warning": "预警", "report": "调查报告", "inquiry": "调查评估报告", "investigation": "调查",
           "sirens": "警报", "evacuation": "撤离"},
    "zh-TW": {"hazard": {"flood": "水災 豪雨", "wildfire": "山火", "storm": "颱風", "earthquake": "地震", "tsunami": "海嘯",
                         "landslide": "土石流", "heat": "高溫"},
              "disaster": "災害", "warning": "警報", "report": "報告", "inquiry": "調查報告", "investigation": "調查",
              "sirens": "警報", "evacuation": "撤離"},
    "ko": {"hazard": {"flood": "홍수 호우", "wildfire": "산불", "storm": "태풍", "earthquake": "지진", "tsunami": "쓰나미",
                      "landslide": "산사태", "heat": "폭염"},
           "disaster": "재난", "warning": "경보", "report": "보고서", "inquiry": "국정조사", "investigation": "조사",
           "sirens": "사이렌", "evacuation": "대피"},
}

# German specialist terms (D-047). Search words only — never evidence, never codes.
LANG["de"].update({
    "more": {"flood": ["Starkregen", "Sturzflut", "Flutkatastrophe", "Pegel", "Hochwasserwarnung"],
             "storm": ["Unwetterwarnung", "Orkan", "Sturmwarnung"], "wildfire": ["Waldbrandgefahr", "Waldbrandwarnung"],
             "heat": ["Hitzewarnung"], "landslide": ["Hangrutschung", "Murgang"], "earthquake": [], "tsunami": []},
    "warning_terms": ["Unwetterwarnung", "Warnstufe", "Katastrophenfall", "Katastrophenschutz", "Warn-App", "Sirenenwarnung",
                      "Krisenstab", "Warnmeldung", "Bevölkerungswarnung"],
})

# Authoritative German bodies (D-047): used only to build site-restricted search queries and to recognise official /
# legislative hosts when sorting. A source from these sites is still only a source: its text must be read and checked.
AUTHORITIES = {
    "DE": [
        {"name": "Deutscher Wetterdienst (DWD)", "site": "dwd.de", "kind": "government", "role": "weather warnings",
         "query": "{hz} {place}{yr} Warnung"},
        {"name": "Bundesamt für Bevölkerungsschutz und Katastrophenhilfe (BBK)", "site": "bbk.bund.de", "kind": "government",
         "role": "civil protection; NINA, Cell Broadcast, sirens", "query": "{place}{yr} Warnung Bevölkerung"},
        {"name": "Deutscher Bundestag", "site": "bundestag.de", "kind": "legislative", "role": "federal parliament papers (Drucksachen)",
         "query": "{hz} {place}{yr} Drucksache"},
        {"name": "Bundesanstalt für Gewässerkunde (BfG)", "site": "bafg.de", "kind": "government", "role": "river gauges, flood hydrology",
         "query": "{hz} {place}{yr}", "hazards": ["flood"]},
    ],
}
# German states: only names a user would type in the location. Domains limited to ones known to be the state's own.
DE_STATES = {
    "RP": {"names": ["rheinland-pfalz", "rhineland-palatinate"], "landtag": "landtag.rlp.de", "gov": "rlp.de"},
    "NW": {"names": ["nordrhein-westfalen", "north rhine-westphalia", "nrw"], "landtag": "landtag.nrw.de", "gov": "nrw.de"},
    "BY": {"names": ["bayern", "bavaria"], "landtag": "bayern.landtag.de", "gov": "bayern.de"},
    "BW": {"names": ["baden-württemberg", "baden-wuerttemberg"], "landtag": "landtag-bw.de", "gov": "baden-wuerttemberg.de"},
    "SN": {"names": ["sachsen", "saxony"], "landtag": "landtag.sachsen.de", "gov": "sachsen.de"},
    "NI": {"names": ["niedersachsen", "lower saxony"], "landtag": "landtag-niedersachsen.de", "gov": "niedersachsen.de"},
    "HE": {"names": ["hessen", "hesse"], "landtag": "hessischer-landtag.de", "gov": "hessen.de"},
}


def detect_de_state(location: str) -> dict | None:
    low = " " + re.sub(r"[,;/()]", " ", (location or "").lower()) + " "
    for code, st in DE_STATES.items():
        if any(f" {n} " in low for n in st["names"]):
            return {"code": code, **st}
    return None


def authority_templates(case: dict, country: dict | None, year: str) -> list[tuple[str, str]]:
    """(purpose, query) pairs aimed at the country's authoritative bodies and specialist local terms (D-047).
    Germany only for now; empty elsewhere. Each query is one paid search, counted in the case budget."""
    if not country or country["code"] != "DE":
        return []
    words = LANG["de"]
    place = place_words(case.get("location", ""), country) or case.get("name", "")
    st = detect_de_state(case.get("location", ""))
    drop = list(st["names"]) if st else []  # the state name is not a useful search word next to the place
    drop += ["valley", "river", "county", "district", "region", "area"]  # English geo words would spoil German queries
    for n in drop:
        place = re.sub(rf"(?i)\b{re.escape(n)}\b", " ", place)
    place = re.sub(r"\s+", " ", place).strip() or case.get("name", "")
    yr = f" {year}" if year else ""
    hz_key = hazard_of(case.get("name", "")) or hazard_of(case.get("location", ""))
    hz = words["hazard"].get(hz_key, words["disaster"]) if hz_key else words["disaster"]
    out = []
    for a in AUTHORITIES["DE"]:
        if a.get("hazards") and hz_key not in a["hazards"]:
            continue
        q = a["query"].format(hz=hz, place=place, yr=yr).strip()
        out.append((f"authority: {a['name']}", f"{q} site:{a['site']}"))
    inquiry = f"{words['inquiry']} {hz} {place}{yr}"
    out.append(("authority: state parliament inquiry (Landtag)", f"{inquiry} site:{st['landtag']}" if st else f"Landtag {inquiry}"))
    if st:
        out.append((f"authority: state government ({st['code']})", f"{hz} {place}{yr} {words['warning']} site:{st['gov']}"))
    more = (words["more"].get(hz_key) or [])[:2]
    if more:
        out.append(("local terms: specialist words", f"{' '.join(more)} {place}{yr} {words['warning_terms'][0]}"))
    out.append(("local terms: civil protection", f"{hz} {place}{yr} {words['warning_terms'][2]} {words['warning_terms'][3]}"))
    return out


def authority_sites(code: str) -> list[str]:
    sites = [a["site"] for a in AUTHORITIES.get(code, [])]
    if code == "DE":
        sites += [st["landtag"] for st in DE_STATES.values()] + [st["gov"] for st in DE_STATES.values()]
    return sites


# --------------------------------------------------------------------------- countries
# names: lower-case English and native names used to detect the country in the location field (and to recognise the
# country in local-language sources). site: official domain for site: queries. systems: public warning systems.
COUNTRIES = {
    "DE": {"names": ["germany", "deutschland"], "lang": "de", "site": ".de", "systems": ["NINA", "KATWARN", "Cell Broadcast"]},
    "AT": {"names": ["austria", "österreich"], "lang": "de", "site": ".gv.at", "systems": ["AT-Alert", "KATWARN"]},
    "CH": {"names": ["switzerland", "schweiz", "suisse", "svizzera"], "lang": "de", "site": ".admin.ch", "systems": ["Alertswiss"]},
    "FR": {"names": ["france"], "lang": "fr", "site": ".gouv.fr", "systems": ["FR-Alert"]},
    "BE": {"names": ["belgium", "belgique", "belgië"], "lang": "fr", "site": ".be", "systems": ["BE-Alert"]},
    "NL": {"names": ["netherlands", "nederland", "holland"], "lang": "nl", "site": ".nl", "systems": ["NL-Alert"]},
    "ES": {"names": ["spain", "españa"], "lang": "es", "site": ".gob.es", "systems": ["ES-Alert"]},
    "IT": {"names": ["italy", "italia"], "lang": "it", "site": ".gov.it", "systems": ["IT-alert"]},
    "PT": {"names": ["portugal"], "lang": "pt", "site": ".gov.pt", "systems": []},
    "BR": {"names": ["brazil", "brasil"], "lang": "pt", "site": ".gov.br", "systems": ["Defesa Civil Alerta"]},
    "MX": {"names": ["mexico", "méxico"], "lang": "es", "site": ".gob.mx", "systems": ["SASMEX"]},
    "GB": {"names": ["united kingdom", "uk", "england", "scotland", "wales", "northern ireland", "britain"], "lang": "en",
           "site": ".gov.uk", "systems": ["Emergency Alerts", "Environment Agency flood warning"]},
    "IE": {"names": ["ireland"], "lang": "en", "site": ".gov.ie", "systems": []},
    "CA": {"names": ["canada"], "lang": "en", "site": ".gc.ca", "systems": ["Alert Ready"]},
    "AU": {"names": ["australia"], "lang": "en", "site": ".gov.au", "systems": ["Emergency Alert", "Australian Warning System"]},
    "NZ": {"names": ["new zealand", "aotearoa"], "lang": "en", "site": ".govt.nz", "systems": ["Emergency Mobile Alert"]},
    "JP": {"names": ["japan", "日本"], "lang": "ja", "site": ".go.jp", "systems": ["J-Alert", "緊急速報メール"]},
    "CN": {"names": ["china", "中国"], "lang": "zh", "site": ".gov.cn", "systems": []},
    "TW": {"names": ["taiwan", "台灣", "臺灣"], "lang": "zh-TW", "site": ".gov.tw", "systems": ["災防告警"]},
    "KR": {"names": ["south korea", "korea", "대한민국", "한국"], "lang": "ko", "site": ".go.kr", "systems": ["재난문자"]},
    "IN": {"names": ["india"], "lang": "en", "site": ".gov.in", "systems": ["Cell Broadcast"]},
    "PH": {"names": ["philippines"], "lang": "en", "site": ".gov.ph", "systems": ["ECBS"]},
}

US_HINTS = {"usa", "u.s.", "us", "united states", "america"}


def detect_country(location: str) -> dict | None:
    """Country profile for a non-U.S. location, or None (U.S. or not recognised → existing behaviour)."""
    low = " " + re.sub(r"[,;/()]", " ", (location or "").lower()) + " "
    if any(f" {h} " in low for h in US_HINTS):
        return None
    for code, c in COUNTRIES.items():
        for n in c["names"]:
            if (f" {n} " in low) if n.isascii() else (n in low):
                return {"code": code, **c}
    return None


def hazard_of(name: str) -> str | None:
    low = (name or "").lower()
    for key, words in HAZARDS.items():
        if any(re.search(rf"\b{re.escape(w)}", low) for w in words):
            return key
    return None


def place_words(location: str, country: dict | None) -> str:
    """The location without the country name, e.g. 'germany Ahr valley' → 'Ahr valley'."""
    s = location or ""
    if country:
        for n in country["names"]:
            s = re.sub(rf"(?i)\b{re.escape(n)}\b" if n.isascii() else re.escape(n), " ", s)
    return re.sub(r"\s+", " ", re.sub(r"[,;]", " ", s)).strip()


def localized_templates(case: dict, country: dict | None, year: str) -> list[tuple[str, str]]:
    """Extra (purpose, query) pairs for a non-U.S. incident. Empty for U.S. / unrecognised locations."""
    if not country:
        return []
    place = place_words(case.get("location", ""), country) or case.get("name", "")
    yr = f" {year}" if year else ""
    hz = hazard_of(case.get("name", "")) or hazard_of(case.get("location", ""))
    out = [("local: official reports", f"{place}{yr} {hz or 'disaster'} report site:{country['site']}"),
           ("local: warning systems", f"{place}{yr} " + " OR ".join(f'"{s}"' if " " in s else s for s in country["systems"][:3])
            if country["systems"] else f"{place}{yr} public warning")]
    words = LANG.get(country["lang"])
    if words:
        local_hz = words["hazard"].get(hz, words["disaster"]) if hz else words["disaster"]
        out += [
            ("local language: warning", f"{local_hz} {place}{yr} {words['warning']}"),
            ("local language: inquiry / report", f"{local_hz} {place}{yr} {words['inquiry']} {words['report']}"),
            ("local language: official", f"{local_hz} {place}{yr} {words['warning']} site:{country['site']}"),
            ("local language: report (PDF)", f"{local_hz} {place}{yr} {words['report']} filetype:pdf"),
        ]
    return out


# --------------------------------------------------------------------------- keyword discovery
_STOP = set("""
the a an and or of in on at to for from by with as is are was were be been this that these those it its into after
before over under about more most new news live video photos photo update updates says said year years day days week
how why what when where who which than then also not no can will would could should may might one two three first
last people many more report reports alert alerts warning warnings emergency disaster flood floods flooding fire storm
der die das und oder ein eine einer eines im in am an auf aus bei mit nach von vor zu zum zur ist sind war wurde
werden hat haben nicht auch noch nur wie was wer wo als für über unter durch des dem den jahre jahr heute
le la les un une des du de et ou en au aux est sont pour par sur dans avec
el los las y o en del al es son por con para una uno
il lo gli i e di da nel nella con per su
het een van en op voor met aan
www com org net html https http pdf
""".split())


def _tokens(text: str) -> list[str]:
    return re.findall(r"[^\W\d_][^\W_]{2,}", text or "")


def _candidates(text: str) -> set[str]:
    """Single words plus runs of 2-3 capitalised words ("Bad Neuenahr", "Kreis Ahrweiler")."""
    words = re.findall(r"[^\W\d_][^\W_]+(?:-[^\W\d_][^\W_]+)*", text or "")
    out = {w for w in words if len(w) >= 3}
    for n in (2, 3):
        for i in range(len(words) - n + 1):
            run = words[i:i + n]
            if all(w[:1].isupper() for w in run) and not any(w.lower() in _STOP for w in (run[0], run[-1])):
                out.add(" ".join(run))
    return out


def discover_keywords(results: list[dict], terms: dict, min_sites: int = 2, top: int = 8) -> list[dict]:
    """Terms that recur across results that match the incident, counted once per website.

    results: search results with url/title/snippet/identity_score. Only results with identity_score >= 0.5 are used.
    Returns [{"term", "sites", "anchored"}], strongest first. A term is anchored when it contains a word of the
    incident name or place as a prefix (Ahrtal, Ahrweiler ← Ahr), which makes it safe to use for recognising
    local-language sources about this incident.
    """
    known = set(terms.get("name", [])) | set(terms.get("loc", [])) | {a for al in terms.get("aliases", []) for a in al}
    anchors = [t for t in (list(terms.get("name", [])) + list(terms.get("loc", []))) if len(t) >= 3]

    def is_known(w: str) -> bool:  # what the user already typed (incl. simple plurals: disasters ← disaster), or filler
        return (w in known or w in _STOP or w.isdigit()
                or (w.endswith("s") and w[:-1] in known) or (w.endswith("es") and w[:-2] in known))

    def compound(w: str) -> bool:  # a NEW word built on a typed word: Ahrtal, Ahrweiler ← Ahr (not plurals)
        return not is_known(w) and any(w.startswith(a) and len(w) >= len(a) + 3 for a in anchors)
    sites: dict[str, set] = defaultdict(set)
    shown: dict[str, str] = {}
    for r in results:
        if (r.get("identity_score") or 0) < 0.5:
            continue
        host = urlparse(r.get("url") or "").netloc.lower().removeprefix("www.")
        for tok in _candidates(f"{r.get('title', '')} {r.get('snippet', '')}"):
            low = tok.lower()
            # 2026-11-13 live Ahr run: skip candidates made only of words already typed ("Ahr Valley", "Germany Ahr",
            # "Disasters") — they add nothing new to search with
            if all(is_known(w) for w in low.split()):
                continue
            sites[low].add(host)
            if tok[:1].isupper() or low not in shown:
                shown[low] = tok
    out = []
    for low, hosts in sites.items():
        if len(hosts) < min_sites:
            continue
        anchored = any(compound(w) for w in low.split())
        proper = shown[low][:1].isupper() or not shown[low].isascii()
        if not (anchored or proper):
            continue  # ordinary lower-case words ("residents", "water") are not useful search keywords
        out.append({"term": shown[low], "sites": len(hosts), "anchored": anchored})
    # single new compound words first (Ahrtal, Ahrweiler); then other anchored terms; then more websites; then longer
    # phrases ("Bad Neuenahr" before "Bad")
    single_anchor = lambda d: d["anchored"] and " " not in d["term"]
    out.sort(key=lambda d: (-int(single_anchor(d)), -int(d["anchored"]), -d["sites"], -len(d["term"].split()), d["term"].lower()))
    kept: list[dict] = []
    for d in out:  # drop a word already inside a kept phrase, or a phrase whose words are all kept on their own
        low = d["term"].lower()
        words = low.split()
        if " " in low and any(w == k["term"].lower() for k in kept if single_anchor(k) for w in words):
            continue  # "Ahr River Ahrtal", "Ahrtal Ahrweiler": the kept compound alone is the better search term
        if any(low in k["term"].lower().split() for k in kept if " " in k["term"]):
            continue
        if " " in low and all(w in {k["term"].lower() for k in kept} for w in low.split()):
            continue
        kept.append(d)
    return kept[:top]


def discovery_queries(keywords: list[dict], case: dict, country: dict | None, year: str, limit: int = 6) -> list[tuple[str, str]]:
    """(purpose, query) pairs built from discovered keywords: each keyword with the year and a warning word."""
    words = LANG.get(country["lang"]) if country else None
    warn = words["warning"] if words else "warning"
    yr = f" {year}" if year else ""
    out = []
    for k in keywords[:limit]:
        out.append((f"discovered keyword: {k['term']}", f"{k['term']}{yr} {warn}"))
    anchored = [k["term"] for k in keywords if k["anchored"]]
    if anchored:  # the incident's own local name + "report" finds inquiry reports and after-action reviews
        report = words["report"] if words else "after-action report"
        out.append((f"discovered keyword: {anchored[0]} (report)", f"{anchored[0]}{yr} {report}"))
    return out
