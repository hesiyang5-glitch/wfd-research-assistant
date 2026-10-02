"""Existing-data migration on a database made by the deployed version (c57214a). Run:  python -m tests.test_legacy_migration

The fixture tests/fixtures/legacy_c57214a_marshall.sqlite3 was produced by tools/make_legacy_fixture.py running the
OLD code: a "Marshall Fire" case (synthetic text) coded by Claude through the old code path, plus a human edit.
This test copies it (the fixture itself is never modified), opens the copy with the current code (which migrates it),
and checks that the Claude results are still the Claude column, the human edit is still the Human final value, and no
existing row changed. It does NOT use any production database. Offline; no API calls.
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
FIXTURE = ROOT / "tests" / "fixtures" / "legacy_c57214a_marshall.sqlite3"
TMP = Path(tempfile.mkdtemp(prefix="wfdlegacy_"))
(TMP / "data").mkdir()
shutil.copy(FIXTURE, TMP / "data" / "wfd.sqlite3")
os.environ["WFD_DATA_DIR"] = str(TMP / "data")
for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENAI_BASE_URL", "WFD_PASSWORD", "WFD_TEST_FIXTURE"):
    os.environ.pop(k, None)
sys.path.insert(0, str(ROOT))
PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS " if cond else "  FAIL ") + name + (f"  — {detail}" if detail and not cond else ""))


def snapshot(path) -> dict:
    c = sqlite3.connect(str(path))
    c.row_factory = sqlite3.Row
    out = {}
    for t in ("cases", "sources", "passages", "runs", "suggestions", "reviews", "review_history", "usage"):
        out[t] = [dict(r) for r in c.execute(f"SELECT * FROM {t} ORDER BY rowid")]
    c.close()
    return out


def main():
    before = snapshot(TMP / "data" / "wfd.sqlite3")
    cols_before = {t: list(before[t][0].keys()) if before[t] else [] for t in before}
    check("fixture is in the pre-OpenAI format (no provider column, no model_calls table)",
          "provider" not in cols_before["suggestions"]
          and not sqlite3.connect(str(FIXTURE)).execute("SELECT 1 FROM sqlite_master WHERE name='model_calls'").fetchone())
    legacy_codes = {s["variable"]: s["value"] for s in before["suggestions"] if s["basis"] == "model" and s["value"]}
    print("  legacy Claude codes in the fixture:", legacy_codes)

    from app import coding, db, export
    db.conn()  # opening the copy runs the additive migration
    after = snapshot(TMP / "data" / "wfd.sqlite3")
    unchanged = all([{k: r[k] for k in cols_before[t]} for r in after[t]] == before[t] for t in before)
    check("every existing row (cases, sources, passages, runs, suggestions, reviews, history, usage) is unchanged", unchanged)
    check("same number of rows in every table", all(len(after[t]) == len(before[t]) for t in before))
    check("fixture file itself untouched (test used a copy)", "provider" not in [r[1] for r in sqlite3.connect(str(FIXTURE)).execute("PRAGMA table_info(suggestions)")])

    cid = before["cases"][0]["id"]
    rows = {r["name"]: r for r in export.case_results(cid)["rows"]}
    for var, val in legacy_codes.items():
        cell = rows[var]["cells"]["anthropic"]
        check(f"{var}: Claude column shows the existing Claude value {val}", cell["value"] == val and cell["state"] == "suggested", str(cell))
        check(f"{var}: OpenAI column shows 'Not run'", rows[var]["cells"]["openai"]["state"] == "not_run")
    check("existing human edit (SYSTEM_LEVEL 3 → 2) is still the Human final value, separate from Claude's 3",
          rows["SYSTEM_LEVEL"]["review"]["value"] == "2" and rows["SYSTEM_LEVEL"]["review"]["action"] == "edited"
          and rows["SYSTEM_LEVEL"]["cells"]["anthropic"]["value"] == "3")
    check("no comparison is invented when only Claude has run", all(r["comparison"] is None for r in rows.values()))
    check("unsupported variables shown as 'No supported value' in the Claude column",
          rows["POPULATION_SCOPE"]["cells"]["anthropic"]["state"] == "no_supported_value")
    check("derived fields still shown as system values", rows["SOURCE_COUNT_PRIMARY"]["system"] and rows["SOURCE_COUNT_PRIMARY"]["system"]["value"] == "1")
    led = coding.case_ledger(cid)
    check("old Claude calls count toward the case's attempt and spend totals",
          led["attempts_by"].get("anthropic") == len([u for u in before["usage"] if u["kind"] == "model"])
          and abs(led["spent_total"] - sum(u["cost_usd"] or 0 for u in before["usage"])) < 1e-9, str(led))
    import openpyxl, io
    xl = openpyxl.load_workbook(io.BytesIO(export.xlsx(cid)))
    hdr = [c.value for c in xl["Case_Row"][1]]
    v = [c.value for c in xl["Case_Row"][2]]
    sl = hdr.index(rows["SYSTEM_LEVEL"]["raw_header"])
    check("export after migration: Case_Row carries the human value (2), not a model value", v[sl] == 2)

    # browser: the review table on the migrated copy (English)
    env = {**os.environ, "WFD_PORT": "8831"}
    srv = subprocess.Popen([sys.executable, "-m", "app.server"], cwd=str(ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen("http://127.0.0.1:8831/healthz", timeout=1)
                break
            except Exception:
                time.sleep(0.5)
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page(viewport={"width": 1500, "height": 900})
            errors = []
            pg.on("pageerror", lambda e: errors.append(str(e)))
            pg.goto("http://127.0.0.1:8831/")
            pg.evaluate("localStorage.setItem('wfd_lang','en')")
            pg.goto(f"http://127.0.0.1:8831/#/case/{cid}/review")
            pg.reload()  # a hash change alone does not reload, so the language setting would not apply
            pg.wait_for_timeout(1500)
            pg.fill("#wbq", "S")
            pg.click("tr[data-v='SYSTEM_LEVEL']")
            pg.wait_for_timeout(500)
            row = pg.inner_text("tr[data-v='SYSTEM_LEVEL']")
            print("  browser row SYSTEM_LEVEL:", " | ".join(x.strip() for x in row.split("\t")))
            check("browser: SYSTEM_LEVEL row shows Claude 3, OpenAI Not run, Human final 2",
                  "3" in row and "Not run" in row and "2" in row)
            pg.fill("#wbq", "")
            sec = [o for o in pg.eval_on_selector_all("#wbsec option", "els => els.map(e => e.value)") if o.startswith("IV")]
            if sec:
                pg.select_option("#wbsec", sec[0])  # Failure Information section: rows with Claude values
            pg.wait_for_timeout(400)
            pg.screenshot(path=str(TMP / "legacy_marshall_review.png"))
            check("browser: no JS errors", not errors, str(errors))
            b.close()
    finally:
        srv.terminate()
        srv.communicate(timeout=10)
    print("  screenshot:", TMP / "legacy_marshall_review.png")
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
