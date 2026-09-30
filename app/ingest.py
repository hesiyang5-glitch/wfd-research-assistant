"""Source retrieval and text extraction. Webpages and PDFs are fetched over ordinary public HTTP only —
no login, paywall, or robots/access-control circumvention. Failures are recorded, never hidden."""
from __future__ import annotations

import hashlib
import io
import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import logging

import httpx
from bs4 import BeautifulSoup

logging.getLogger("pdfminer").setLevel(logging.ERROR)

from .config import DATA_DIR

UA = "WFD-Coding-Assistant/0.1 (academic research tool; public-warning-failure database)"
MAX_BYTES = 60 * 1024 * 1024
FILES = DATA_DIR / "files"


class FetchError(Exception):
    pass


def url_key(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:24]


def fetch_url(url: str) -> dict:
    """Returns {final_url, content_type, path, status}. Raises FetchError with a human-readable reason."""
    try:
        with httpx.Client(follow_redirects=True, timeout=httpx.Timeout(30.0, connect=10.0),
                          headers={"User-Agent": UA, "Accept": "text/html,application/pdf,*/*;q=0.8"}) as c:
            with c.stream("GET", url) as r:
                if r.status_code in (401, 402, 403):
                    raise FetchError(f"access restricted (HTTP {r.status_code}) — add the text manually if you have legitimate access")
                if r.status_code == 429:
                    raise FetchError("rate limited by site (HTTP 429)")
                if r.status_code >= 400:
                    raise FetchError(f"HTTP {r.status_code}")
                ctype = r.headers.get("content-type", "").split(";")[0].strip().lower()
                buf = io.BytesIO()
                for chunk in r.iter_bytes():
                    buf.write(chunk)
                    if buf.tell() > MAX_BYTES:
                        raise FetchError(f"file larger than {MAX_BYTES // 1024 // 1024} MB — not downloaded")
                final = str(r.url)
    except httpx.HTTPError as e:
        raise FetchError(f"network error: {type(e).__name__}: {e}") from e
    data = buf.getvalue()
    if not ctype:
        ctype = "application/pdf" if data[:5] == b"%PDF-" else "text/html"
    if data[:5] == b"%PDF-":
        ctype = "application/pdf"
    ext = ".pdf" if ctype == "application/pdf" else ".html"
    path = FILES / f"{url_key(final)}{ext}"
    path.write_bytes(data)
    return {"final_url": final, "content_type": ctype, "path": str(path), "size": len(data)}


# ----------------------------------------------------------------------------- extraction
BLOCK_TAGS = ["p", "li", "h1", "h2", "h3", "h4", "blockquote", "td", "th", "pre", "figcaption", "dd"]


def extract_html(html: bytes | str, base_url: str = "") -> dict:
    soup = BeautifulSoup(html, "lxml")
    meta = {}
    for m in soup.find_all("meta"):
        k = (m.get("property") or m.get("name") or m.get("itemprop") or "").lower()
        if k and m.get("content"):
            meta[k] = m["content"]
    title = (meta.get("og:title") or (soup.title.string if soup.title and soup.title.string else "") or "").strip()
    publisher = meta.get("og:site_name") or meta.get("publisher") or meta.get("author") or ""
    published = (meta.get("article:published_time") or meta.get("datepublished") or meta.get("date") or
                 meta.get("dc.date") or meta.get("pubdate") or "")
    if not published:
        for s in soup.find_all("script", type="application/ld+json"):
            try:
                j = json.loads(s.string or "{}")
            except Exception:
                continue
            items = j if isinstance(j, list) else [j]
            for it in items:
                if isinstance(it, dict) and it.get("datePublished"):
                    published = it["datePublished"]
                    pub = it.get("publisher")
                    if isinstance(pub, dict) and not publisher:
                        publisher = pub.get("name", "")
                    break
    if not published:
        t = soup.find("time")
        if t and t.get("datetime"):
            published = t["datetime"]
    links = []
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"])
        if href.startswith("http"):
            links.append({"url": href.split("#")[0], "text": a.get_text(" ", strip=True)[:200]})
    for bad in soup(["script", "style", "noscript", "nav", "footer", "header", "aside", "form", "svg", "iframe", "button"]):
        bad.decompose()
    root = soup.find("article") or soup.find("main") or soup.body or soup
    paras = []
    seen = set()
    for el in root.find_all(BLOCK_TAGS):
        if el.find(BLOCK_TAGS):  # avoid double-counting nested blocks
            continue
        txt = re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip()
        if len(txt) < 25 or txt in seen:
            continue
        seen.add(txt)
        paras.append(txt)
    if not paras:  # plain pages without block tags
        txt = re.sub(r"[ \t]+", " ", root.get_text("\n", strip=True))
        paras = [p.strip() for p in txt.split("\n") if len(p.strip()) >= 25]
    return {"title": title, "publisher": publisher.strip(), "published": str(published)[:40],
            "pages": [{"page": None, "paragraphs": paras}], "links": links, "ocr_status": "not_applicable"}


def _ocr_available() -> bool:
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def extract_pdf(path: str | Path) -> dict:
    import pdfplumber
    pages = []
    empty_pages = []
    title = ""
    with pdfplumber.open(str(path)) as pdf:
        title = (pdf.metadata or {}).get("Title", "") or ""
        for i, pg in enumerate(pdf.pages, start=1):
            try:
                txt = pg.extract_text() or ""
            except Exception:
                txt = ""
            if len(txt.strip()) < 30:
                empty_pages.append(i)
            pages.append({"page": i, "text": txt})
    _strip_repeated_lines(pages)
    ocr_status = "not_needed"
    if empty_pages:
        if _ocr_available():
            import pypdfium2 as pdfium
            import pytesseract
            doc = pdfium.PdfDocument(str(path))
            done = 0
            for i in empty_pages:
                try:
                    img = doc[i - 1].render(scale=2.0).to_pil()
                    pages[i - 1]["text"] = pytesseract.image_to_string(img)
                    pages[i - 1]["ocr"] = True
                    done += 1
                except Exception:
                    pass
            ocr_status = f"ocr_applied: {done}/{len(empty_pages)} page(s) had no text layer (pages {_ranges(empty_pages)})"
        else:
            ocr_status = f"ocr_unavailable: {len(empty_pages)} page(s) without text layer not read (pages {_ranges(empty_pages)})"
    out_pages = []
    for p in pages:
        paras = _split_pdf_text(p["text"])
        out_pages.append({"page": p["page"], "paragraphs": paras})
    return {"title": title.strip(), "publisher": "", "published": "", "pages": out_pages, "links": [],
            "ocr_status": ocr_status, "n_pages": len(pages)}


def _strip_repeated_lines(pages: list[dict]) -> None:
    """Remove running headers/footers (e.g. browser print stamps, site names, page URLs) that repeat on most pages."""
    if len(pages) < 3:
        return
    def key(l):
        return re.sub(r"\d+", "#", l.strip().lower())
    from collections import Counter
    cnt = Counter()
    for p in pages:
        cnt.update({key(l) for l in p["text"].splitlines() if l.strip()})
    rep = {k for k, n in cnt.items() if n >= max(3, 0.5 * len(pages)) and len(k) < 200}
    for p in pages:
        p["text"] = "\n".join(l for l in p["text"].splitlines() if key(l) not in rep)


BOILER = re.compile(r"\b(sponsored|advertisement|trending topics|click here|learn more|subscribe|sign up for|newsletter|"
                    r"cookie|all rights reserved|privacy policy|terms of use|share this|follow us|related stories|"
                    r"read more|watch:|most popular)\b", re.I)


def is_boilerplate(text: str) -> bool:
    hits = len(BOILER.findall(text))
    return hits >= 2 or (hits >= 1 and len(text) < 160)


def _ranges(nums: list[int]) -> str:
    out, start, prev = [], None, None
    for n in nums:
        if start is None:
            start = prev = n
        elif n == prev + 1:
            prev = n
        else:
            out.append(f"{start}-{prev}" if start != prev else str(start))
            start = prev = n
    if start is not None:
        out.append(f"{start}-{prev}" if start != prev else str(start))
    return ", ".join(out)


def _split_pdf_text(text: str) -> list[str]:
    """PDF text has hard line breaks; rebuild paragraphs from blank lines / sentence ends."""
    lines = [l.rstrip() for l in text.splitlines()]
    paras, cur = [], []
    for l in lines:
        if not l.strip():
            if cur:
                paras.append(" ".join(cur))
                cur = []
            continue
        cur.append(l.strip())
        if re.search(r"[.!?:\"”]$", l.strip()) and len(" ".join(cur)) > 350:
            paras.append(" ".join(cur))
            cur = []
    if cur:
        paras.append(" ".join(cur))
    return [re.sub(r"\s+", " ", p).strip() for p in paras if len(p.strip()) >= 3]


def extract_docx(path) -> dict:
    import docx
    d = docx.Document(str(path))
    paras = [p.text.strip() for p in d.paragraphs if len(p.text.strip()) >= 3]
    return {"title": (d.core_properties.title or "").strip(), "publisher": "", "published": "",
            "pages": [{"page": None, "paragraphs": paras}], "links": [], "ocr_status": "not_applicable"}


def extract_text_plain(text: str) -> dict:
    paras = [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if len(paras) <= 1:
        paras = [p.strip() for p in text.splitlines() if p.strip()]
    return {"title": "", "publisher": "", "published": "", "pages": [{"page": None, "paragraphs": paras}],
            "links": [], "ocr_status": "not_applicable"}


def extract_file(path: str, content_type: str = "") -> dict:
    p = Path(path)
    head = p.read_bytes()[:5]
    if head == b"%PDF-" or p.suffix.lower() == ".pdf":
        return extract_pdf(p)
    if p.suffix.lower() == ".docx":
        return extract_docx(p)
    if p.suffix.lower() in (".txt", ".md"):
        return extract_text_plain(p.read_text(encoding="utf-8", errors="replace"))
    raw = p.read_bytes()
    return extract_html(raw)


# ----------------------------------------------------------------------------- passages
def make_passages(extracted: dict, target: int = 900, max_len: int = 1600) -> list[dict]:
    """Chunk into passages that keep page and paragraph numbers. No cap on count; nothing is truncated."""
    out = []
    for pg in extracted["pages"]:
        buf, buf_para = "", None
        for pi, para in enumerate(pg["paragraphs"], start=1):
            pieces = [para]
            if len(para) > max_len:
                sents = re.split(r"(?<=[.!?])\s+", para)
                pieces, cur = [], ""
                for s in sents:
                    if len(cur) + len(s) > target and cur:
                        pieces.append(cur.strip())
                        cur = ""
                    while len(s) > max_len:          # pathological run-on text: hard split at whitespace
                        cut = s.rfind(" ", 0, max_len)
                        cut = cut if cut > 200 else max_len
                        pieces.append(s[:cut].strip())
                        s = s[cut:]
                    cur += " " + s
                if cur.strip():
                    pieces.append(cur.strip())
            for piece in pieces:
                if buf and len(buf) + len(piece) > target:
                    out.append({"page": pg["page"], "para": buf_para, "text": buf.strip()})
                    buf, buf_para = "", None
                if buf_para is None:
                    buf_para = pi
                buf = f"{buf} {piece}" if buf else piece
                if len(buf) >= target * 0.6:
                    out.append({"page": pg["page"], "para": buf_para, "text": buf.strip()})
                    buf, buf_para = "", None
        if buf.strip():
            out.append({"page": pg["page"], "para": buf_para, "text": buf.strip()})
    # Boilerplate (ads, navigation) is kept out of the evidence index; the count is reported, not hidden.
    kept = [p for p in out if not is_boilerplate(p["text"])]
    for p in kept:
        p["dropped_boilerplate"] = len(out) - len(kept)
    return kept


def normalize_text(t: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", t.lower())).strip()


def content_hash(text: str) -> str:
    return hashlib.sha256(normalize_text(text).encode()).hexdigest()


def shingles(text: str, k: int = 5) -> set[int]:
    w = normalize_text(text).split()
    s = set()
    import zlib
    for i in range(max(0, len(w) - k + 1)):
        h = zlib.crc32(" ".join(w[i:i + k]).encode())
        if h % 3 == 0:
            s.add(h)
    return s


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def containment(a: set, b: set) -> float:
    """Share of the smaller document contained in the other (catches syndicated copies with extra boilerplate)."""
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


# ----------------------------------------------------------------------------- classification
def classify_source(url: str, title: str, text_head: str = "") -> str:
    u = (url or "").lower()
    host = urlparse(u).netloc
    t = f"{title} {u} {text_head[:1500]}".lower()
    if re.search(r"after[- ]action|\baar\b|after-action review|improvement plan", t):
        return "aar"
    if re.search(r"legis|senate\.|house\.gov|capitol\.|statutes|bill history|\bbill\b.*\b(sb|hb)\s?\d", t) and \
            re.search(r"\.gov|\.us|legis|capitol", host):
        return "legislative"
    if host.endswith("fcc.gov") or re.search(r"docket|public notice", t) and host.endswith(".gov"):
        return "regulatory"
    if host.endswith(".gov") or host.endswith(".mil") or re.search(r"\.(state|co|ci|city|county)\.[a-z]{2}\.us$", host) \
            or host.endswith(".us") and ("county" in host or "city" in host):
        return "government"
    if host.endswith(".edu") or "doi.org" in host or re.search(r"journal|springer|wiley|tandfonline|sciencedirect|jstor|ssrn|"
                                                             r"researchgate|arxiv|unu\.edu|nature\.com", host):
        return "academic"
    if host.endswith(".org") and re.search(r"report|brief|analysis|study", t):
        return "ngo_technical"
    if not host:
        return "unknown"  # uploads/pasted text without a URL: set the type on the Sources page rather than guess
    return "media"


PRIMARY_TYPES = {"aar", "government", "regulatory", "legislative"}
