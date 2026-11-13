"""Per-case reading (fetch) limit can be raised on an existing case (DECISIONS D-044). Run:  python -m tests.test_fetch_limit

Offline, no network: fetching is replaced by a counter. Checks:
  [1] the limit counts pages read in ALL runs of the case; at the limit no new page is read
  [2] the limit can be set on an existing case through the limits API: whole number 1–300; not removable
  [3] every change is recorded with who changed it and why
  [4] after raising it, the next run reads new pages again
  [5] the case API reports pages already read and the limit; the Re-run research button asks first
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="wfdfl_"))
os.environ["WFD_DATA_DIR"] = str(TMP / "data")
for k in ("ANTHROPIC_API_KEY", "TAVILY_API_KEY", "BRAVE_API_KEY", "OPENAI_API_KEY", "WFD_PASSWORD", "WFD_TEST_FIXTURE"):
    os.environ.pop(k, None)
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS " if cond else "  FAIL ") + name + (f"  — {detail}" if detail and not cond else ""))


def main():
    from app import db, research, server, jobs
    from app.config import DEFAULT_SETTINGS
    db.conn()
    server.bootstrap_schema()
    s = {**DEFAULT_SETTINGS, "max_fetch": 2}
    cid = db.insert("cases", {"name": "Test flood", "location": "Somewhere, TX", "date_text": "2025", "details": "",
                              "known_links": "", "aliases": "", "schema_version_id": 1, "status": "new",
                              "identity_json": "{}", "settings_json": json.dumps(s),
                              "created_at": time.time(), "updated_at": time.time()})
    for i in range(2):  # two pages read in an earlier run
        research.save_source(cid, {"url": f"https://example.org/old{i}", "origin": "search"}, None, "failed", "earlier run")

    reads = []

    def fake_fetch(url):
        reads.append(url)
        raise research.FetchError("offline test")
    research.fetch_url = fake_fetch

    def run_fetch(label):
        jid = jobs.enqueue(cid, "research", {"identity_confirmed": True})
        ctx = research.Ctx(db.q1("SELECT * FROM jobs WHERE id=?", (jid,)))
        try:
            research.fetch_candidates(ctx, [{"url": f"https://example.org/{label}", "title": "Test flood 2025 Somewhere TX",
                                             "snippet": "", "identity_score": 0.9, "purpose": "test"}])
        except research.Budget:
            pass
        db.update("jobs", jid, {"status": "done"})
        return ctx

    print("\n[1] The limit counts every run of the case")
    ctx = run_fetch("new1")
    check("at the limit, no new page is read", reads == [], str(reads))
    check("stopping is reported as a limit with a hint where to raise it",
          any("fetch limit (2 pages for this case, all runs" in x and "Re-run research" in x for x in ctx.state.get("limits_hit", [])),
          str(ctx.state.get("limits_hit")))

    print("\n[2] Setting the limit on an existing case")

    class H:
        user = "tester"
    for bad in (0, -5, 301, "abc", float("inf")):
        try:
            server.api_case_limits(H(), str(cid), {"limits": {"max_fetch": bad}})
            check(f"rejects {bad!r}", False)
        except server.ApiError as e:
            check(f"rejects {bad!r} ({e.status})", e.status == 400)
    r = server.api_case_limits(H(), str(cid), {"limits": {"max_fetch": 5}, "reason": "set before re-running research"})
    st = json.loads(db.q1("SELECT settings_json FROM cases WHERE id=?", (cid,))["settings_json"])
    check("raised to an explicit number", st["max_fetch"] == 5 and r["changed"] == {"max_fetch": 5}, str(r))
    check("other limits untouched", st["budget_usd"] == s["budget_usd"])

    print("\n[3] Every change is recorded")
    lc = db.q("SELECT * FROM limit_changes WHERE case_id=? AND key='max_fetch'", (cid,))
    check("one record with old value, new value, who and why",
          len(lc) == 1 and lc[0]["old_value"] == "2" and lc[0]["new_value"] == "5" and lc[0]["changed_by"] == "tester"
          and lc[0]["reason"] == "set before re-running research", str(lc))
    server.api_case_limits(H(), str(cid), {"limits": {"max_fetch": 5}})
    check("setting the same value again adds no record",
          len(db.q("SELECT * FROM limit_changes WHERE case_id=? AND key='max_fetch'", (cid,))) == 1)

    print("\n[4] After raising, the next run reads again")
    run_fetch("new2")
    check("a new page is read", reads == ["https://example.org/new2"], str(reads))

    print("\n[5] Case API and interface")
    c = server.api_case(H(), str(cid))
    check("case API reports pages already read and the limit", c["fetched_count"] == 3 and c["max_fetch"] == 5, str(
        {k: c[k] for k in ("fetched_count", "max_fetch")}))
    js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    check("Re-run research asks first (shows pages read and the limit)",
          'startResearch(c.id, ev.currentTarget, true)' in js and "fetched_count" in js and "max_fetch: n" in js)
    check("first research run of a new case does not ask", 'startResearch(c.id); return;' in js)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED:", *FAIL, sep="\n  ")
        sys.exit(1)


if __name__ == "__main__":
    main()
