"""Sources-tab ordering (D-041, 2026-11-13, display only). Run:  python3 -m tests.test_sources_sort

Uses a COPY of the legacy fixture database with seven extra source rows written straight into the copy, fake keys and a
dead proxy, so nothing can leave the machine and nothing is billed. Checks:
  1  default order is type priority (AAR first), longer sources first inside a type
  2  "Length" orders by page count, then by passage count for sources without pages
  3  "Order found" is the old order (S number)
  4  changing the order sends nothing to the server; the choice persists in this browser
  5  the API and the stored rows are unchanged (still by id), so S numbers and exports are unaffected
  6  correcting a source's type re-sorts the list (one PATCH, the existing behaviour)
  7  Chinese labels; no JavaScript errors
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="wfdsort_"))
FIXTURE = ROOT / "tests" / "fixtures" / "legacy_c57214a_marshall.sqlite3"
PORT = "18873"
FAILS: list[str] = []

# (source_type, n_pages, n_passages, fetch_status) — the fixture already holds S1: aar, no pages, 3 passages.
EXTRA = [("media", None, 140, "ok"), ("government", 12, 40, "ok"), ("aar", 80, 300, "ok"), ("government", None, 26, "ok"),
         ("academic", 5, 10, "ok"), ("unknown", None, 500, "ok"), ("media", None, 0, "failed")]
BY_TYPE = [4, 1, 3, 5, 6, 2, 8, 7]
BY_LENGTH = [4, 3, 6, 7, 2, 5, 1, 8]
BY_FOUND = [1, 2, 3, 4, 5, 6, 7, 8]
AFTER_RETYPE = [4, 3, 5, 6, 2, 1, 8, 7]  # S1 changed from aar to media


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond or not detail else f"  — {str(detail)[:400]}"))
    if not cond:
        FAILS.append(name)


def order(pg):
    return [int(x[1:]) for x in pg.eval_on_selector_all("#srcTable tbody tr td:first-child", "els => els.map(e => e.innerText.trim())")]


def main():
    d = TMP / "d"; d.mkdir()
    shutil.copy(FIXTURE, d / "wfd.sqlite3")
    con = sqlite3.connect(d / "wfd.sqlite3")
    base = con.execute("SELECT id, source_type, n_pages, n_passages FROM sources ORDER BY id").fetchall()
    assert base == [(1, "aar", None, 3)], base
    for i, (typ, pages, passages, status) in enumerate(EXTRA, start=2):
        con.execute("INSERT INTO sources (id, case_id, url, title, source_type, origin, fetch_status, relevance_status, n_pages, n_passages, excluded) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,0)", (i, 1, f"https://example.org/s{i}", f"Sort test source {i}", typ, "manual", status, "relevant", pages, passages))
    con.commit(); con.close()
    env = {**os.environ, "WFD_DATA_DIR": str(d), "WFD_PORT": PORT, "ANTHROPIC_API_KEY": "test-not-a-real-key",
           "OPENAI_API_KEY": "test-not-a-real-key", "TAVILY_API_KEY": "test-not-a-real-key",
           "HTTPS_PROXY": "http://127.0.0.1:9", "HTTP_PROXY": "http://127.0.0.1:9", "NO_PROXY": "127.0.0.1,localhost"}
    for k in ("WFD_PASSWORD", "OPENAI_BASE_URL", "WFD_TEST_FIXTURE"):
        env.pop(k, None)
    srv = subprocess.Popen([sys.executable, "-m", "app.server"], cwd=str(ROOT), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    time.sleep(3)
    U = f"http://127.0.0.1:{PORT}/"

    def api_ids():
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        return [s["id"] for s in json.loads(opener.open(U + "api/cases/1/sources", timeout=10).read())]

    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch()
            errors, writes = [], []
            ctx = b.new_context(viewport={"width": 1400, "height": 900})
            ctx.add_init_script("if (!localStorage.getItem('wfd_lang')) localStorage.setItem('wfd_lang','en')")
            pg = ctx.new_page()
            pg.on("pageerror", lambda e: errors.append(str(e)))
            pg.on("request", lambda r: writes.append(f"{r.method} {r.url}") if r.method != "GET" else None)
            pg.goto(U + "#/case/1/sources"); pg.wait_for_selector("#srcSort")

            print("\n[1-3] The three orders")
            check("1 default is type priority: AAR first, longer first inside a type", pg.input_value("#srcSort") == "type" and order(pg) == BY_TYPE, order(pg))
            pg.select_option("#srcSort", "length"); pg.wait_for_timeout(500)
            check("2 length: page count, then passage count; failed source last", order(pg) == BY_LENGTH, order(pg))
            pg.select_option("#srcSort", "found"); pg.wait_for_timeout(500)
            check("3 order found is the S-number order", order(pg) == BY_FOUND, order(pg))

            print("\n[4-5] Display only")
            check("4 changing the order sent no write request", not writes, writes)
            pg.select_option("#srcSort", "length"); pg.wait_for_timeout(400)
            pg.reload(); pg.wait_for_selector("#srcSort"); pg.wait_for_timeout(400)
            check("4b the choice persists in this browser after reload", pg.input_value("#srcSort") == "length" and order(pg) == BY_LENGTH, order(pg))
            check("5 the API still returns sources by id", api_ids() == BY_FOUND, api_ids())
            con = sqlite3.connect(d / "wfd.sqlite3")
            now = con.execute("SELECT id, source_type, n_pages, n_passages FROM sources ORDER BY id").fetchall(); con.close()
            check("5b stored rows are unchanged by sorting", now == base + [(i, e[0], e[1], e[2]) for i, e in enumerate(EXTRA, start=2)], now)
            check("5c every row keeps its own S number and title", pg.inner_text("#srcTable tbody tr:first-child td:nth-child(2) b") == "Sort test source 4")

            print("\n[6] Correcting a type re-sorts")
            pg.select_option("#srcSort", "type"); pg.wait_for_timeout(500)
            n = len(writes)
            pg.select_option("select[data-type='1']", "media"); pg.wait_for_timeout(900)
            check("6 a corrected type moves the source to its new group", order(pg) == AFTER_RETYPE, order(pg))
            check("6b that correction is exactly one PATCH to that source", [w.split("/api/")[-1] for w in writes[n:]] == ["sources/1"] and writes[n].startswith("PATCH"), writes[n:])

            print("\n[7] Chinese labels; no errors")
            pg.evaluate("localStorage.setItem('wfd_lang','zh')"); pg.reload(); pg.wait_for_selector("#srcSort"); pg.wait_for_timeout(400)
            txt = pg.inner_text("#srcSort")
            check("7 the sort options are shown in Chinese", "类型优先" in txt and "篇幅" in txt and "找到顺序" in txt, txt)
            check("7b no JavaScript errors", not errors, errors)
            ctx.close(); b.close()
    finally:
        srv.terminate()
        shutil.rmtree(TMP, ignore_errors=True)
    print("\nSOURCES SORT:", "PASS" if not FAILS else f"FAIL ({len(FAILS)}): {FAILS}")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
