"""Visual-polish checks (2026-10-29, presentation only). Run:  python3 -m tests.test_visual

Uses a COPY of the legacy fixture database (a case with stored Claude results) plus an empty-ish second data folder,
fake keys and a dead proxy, so nothing can leave the machine and nothing is billed. Checks, in Chinese and English at
desktop (1400 px) and phone (390 px) widths:
  1  no button / tab / filter chip / status tag wraps its text onto a second line (owner request 2026-10-29)
  2  buttons respond to the mouse (hover changes the look; disabled buttons do not)
  3  the theme switch only changes the page: it persists in this browser and sends no request to the server
  4  status tags show readable names (the raw id stays as a tooltip)
  5  variable names break only after an underscore
  6  the review/settings pages send nothing while being viewed; no JavaScript errors
The payload / fingerprint checks for this change are covered by tests/test_ui_labels.py (unchanged).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="wfdvis_"))
FIXTURE = ROOT / "tests" / "fixtures" / "legacy_c57214a_marshall.sqlite3"
FAILS: list[str] = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond or not detail else f"  — {str(detail)[:400]}"))
    if not cond:
        FAILS.append(name)


WRAP_JS = """() => {
  const sel = 'button, .chip, .tabs a, header nav a, .badge:not(.wrap), .cell-tag';
  const out = [];
  for (const el of document.querySelectorAll(sel)) {
    if (!el.offsetParent || !el.innerText.trim()) continue;
    const cs = getComputedStyle(el);
    const lh = parseFloat(cs.lineHeight) || parseFloat(cs.fontSize) * 1.4;
    const r = document.createRange(); r.selectNodeContents(el);
    const tops = new Set([...r.getClientRects()].filter((x) => x.width > 0.5).map((x) => Math.round(x.top / (lh * 0.6))));
    if (tops.size > 1 || cs.whiteSpace !== 'nowrap') out.push({ t: el.innerText.replace(/\\s+/g, ' ').slice(0, 50), ws: cs.whiteSpace, lines: tops.size });
  }
  return out;
}"""


def main():
    d1 = TMP / "mf"; d1.mkdir()
    shutil.copy(FIXTURE, d1 / "wfd.sqlite3")
    env = {**os.environ, "WFD_DATA_DIR": str(d1), "WFD_PORT": "18871", "ANTHROPIC_API_KEY": "test-not-a-real-key",
           "OPENAI_API_KEY": "test-not-a-real-key", "TAVILY_API_KEY": "test-not-a-real-key",
           "HTTPS_PROXY": "http://127.0.0.1:9", "HTTP_PROXY": "http://127.0.0.1:9", "NO_PROXY": "127.0.0.1,localhost"}
    for k in ("WFD_PASSWORD", "OPENAI_BASE_URL", "WFD_TEST_FIXTURE"):
        env.pop(k, None)
    srv = subprocess.Popen([sys.executable, "-m", "app.server"], cwd=str(ROOT), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    time.sleep(3)
    U = "http://127.0.0.1:18871/"
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch()
            errors, writes = [], []
            pages = ["#/", "#/cases", "#/schema", "#/settings", "#/case/1/progress", "#/case/1/review", "#/case/1/sources", "#/case/1/searches", "#/case/1/export"]
            print("\n[1] Button, tab, chip and tag text stays on one line")
            for lang in ("zh", "en"):
                for w in (1400, 390):
                    ctx = b.new_context(viewport={"width": w, "height": 900})
                    ctx.add_init_script(f"localStorage.setItem('wfd_lang','{lang}')")
                    pg = ctx.new_page()
                    pg.on("pageerror", lambda e: errors.append(str(e)))
                    pg.on("request", lambda r: writes.append(f"{r.method} {r.url}") if r.method != "GET" else None)
                    bad = {}
                    for h in pages:
                        pg.goto(U + h); pg.wait_for_timeout(900)
                        if h.endswith("review"):
                            pg.click("tr[data-v='FAILURE_TYPE']"); pg.wait_for_timeout(400)
                        r = pg.evaluate(WRAP_JS)
                        if r:
                            bad[h] = r
                    check(f"1 {lang} {w}px: no wrapped button/tab/chip/tag on any page", not bad, bad)
                    ctx.close()

            ctx = b.new_context(viewport={"width": 1400, "height": 900})
            ctx.add_init_script("localStorage.setItem('wfd_lang','en')")
            pg = ctx.new_page()
            pg.on("pageerror", lambda e: errors.append(str(e)))
            pg.on("request", lambda r: writes.append(f"{r.method} {r.url}") if r.method != "GET" else None)
            print("\n[2] Buttons respond to the mouse")
            pg.goto(U + "#/case/1/review"); pg.wait_for_timeout(900)
            pg.click("tr[data-v='FAILURE_TYPE']"); pg.wait_for_timeout(400)
            look = "(s) => { const c = getComputedStyle(document.querySelector(s)); return [c.transform, c.boxShadow, c.backgroundColor, c.borderColor].join('|'); }"
            pg.mouse.move(1, 1); pg.wait_for_timeout(200)
            idle = pg.evaluate(look, "#deferBtn")
            pg.hover("#deferBtn"); pg.wait_for_timeout(250)
            hov = pg.evaluate(look, "#deferBtn")
            check("2 hovering a button changes its look (lift, shadow, colour)", idle != hov, (idle, hov))
            check("2b the hover effect includes a lift (transform)", "matrix" in hov.split("|")[0])
            pg.mouse.move(1, 1); pg.wait_for_timeout(200)
            dis = pg.evaluate("() => { const b = [...document.querySelectorAll('button')].find((x) => x.disabled && x.offsetParent); return b ? b.id || b.innerText : null; }")
            if dis:
                sel = f"#{dis}" if pg.locator(f"#{dis}").count() else None
                if sel:
                    i2 = pg.evaluate(look, sel); pg.hover(sel, force=True); pg.wait_for_timeout(250)
                    check("2c a disabled button does not react to hover", i2 == pg.evaluate(look, sel))
                    check("2d a disabled button shows the not-allowed cursor", pg.evaluate(f"getComputedStyle(document.querySelector('{sel}')).cursor") == "not-allowed")

            print("\n[3] Theme switch (display only)")
            n_writes = len(writes)
            check("3 light theme by default", pg.evaluate("document.documentElement.dataset.theme") == "light")
            pg.click("#themeBtn"); pg.wait_for_timeout(300)
            check("3b switching sets the dark theme", pg.evaluate("document.documentElement.dataset.theme") == "dark")
            bg = pg.evaluate("getComputedStyle(document.body).backgroundColor")
            check("3c dark theme changes the page background", bg not in ("rgb(243, 245, 248)",), bg)
            pg.reload(); pg.wait_for_timeout(900)
            check("3d the choice persists in this browser after reload", pg.evaluate("document.documentElement.dataset.theme") == "dark")
            pg.click("#themeBtn"); pg.wait_for_timeout(200)
            check("3e switching back restores the light theme", pg.evaluate("document.documentElement.dataset.theme") == "light")
            check("3f the theme switch sent nothing to the server", len(writes) == n_writes, writes[n_writes:])

            print("\n[4] Readable status tags; [5] variable-name breaks")
            pg.goto(U + "#/cases"); pg.wait_for_timeout(800)
            tag = pg.inner_text("table tbody tr td:nth-child(3)")
            check("4 case status shows a readable name, not the raw id", tag.strip() == "In review", tag)
            check("4b the raw id stays available as a tooltip", pg.get_attribute("table tbody tr td:nth-child(3) .badge", "title") == "review")
            pg.goto(U + "#/case/1/review"); pg.wait_for_timeout(900)
            html = pg.inner_html("tr[data-v='GEOCODE_SPECIFICITY'] .var-name")
            check("5 variable names may break only after an underscore", html.startswith("GEOCODE_<wbr>SPECIFICITY"), html)
            check("5b the visible text of the variable name is unchanged", pg.inner_text("tr[data-v='GEOCODE_SPECIFICITY'] .var-name") == "GEOCODE_SPECIFICITY")
            pg.goto(U + "#/case/1/progress"); pg.wait_for_timeout(800)
            check("5c progress page with no run shows a sentence, not 'none'", "No research has been run for this case yet." in pg.inner_text("#tabBody"))

            print("\n[6] Nothing sent while viewing; no errors")
            check("6 viewing every page sent no write request (POST/PUT/PATCH/DELETE)", not writes, writes)
            check("6b no JavaScript errors", not errors, errors)
            ctx.close(); b.close()
    finally:
        srv.terminate()
    print("\nVISUAL:", "PASS" if not FAILS else f"FAIL ({len(FAILS)}): {FAILS}")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
