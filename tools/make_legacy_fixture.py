"""Build tests/fixtures/legacy_c57214a_marshall.sqlite3 with the code that is deployed today (commit c57214a).

Run from a checkout of c57214a (e.g. `git worktree add /tmp/old c57214a`):
    cd /tmp/old && WFD_DATA_DIR=/tmp/legacy_data python3 /path/to/repo/tools/make_legacy_fixture.py /path/to/output.sqlite3

It creates a "Marshall Fire" case through the OLD code path: a pasted SYNTHETIC test text (not real source text),
Claude coding through the old AnthropicClient with its HTTP call replaced by a scripted reply (no network, no cost),
and one human edit through the old review API. The result is a database in exactly the format production uses
today, so tests can prove that migration keeps those Claude results visible in the Claude column.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import sys
import time

sys.path.insert(0, os.getcwd())

TEXT = ("SYNTHETIC TEST TEXT — not a real source. Marshall Fire, Boulder County, Colorado, December 30, 2021. "
        "Boulder County sent emergency notifications through its Everbridge-based local alert system and a Wireless "
        "Emergency Alert was issued for parts of Louisville and Superior. Many residents in the evacuation area reported "
        "receiving no alert before the fire reached their neighborhood. The county after-action report says the reverse "
        "911 system and WEA were not used together early enough, a channel selection and redundancy failure. "
        "The alerts were issued by the Boulder Office of Emergency Management, a county agency. ") * 4

CODES = {"FAILURE_TYPE": "6", "SYSTEM_LEVEL": "3", "ALERTING_AUTHORITY_TYPE": "3"}


def main(out_path: str):
    from app import coding, db, research
    from app.config import DEFAULT_SETTINGS
    from app.llm import clients
    from app.server import api_review, bootstrap_schema

    db.conn()
    bootstrap_schema()
    schema = coding.active_schema()
    st = {**DEFAULT_SETTINGS, "max_search_rounds": 0}
    cid = db.insert("cases", {"name": "Marshall Fire", "location": "Boulder County, Colorado", "date_text": "December 30, 2021",
                              "details": "legacy-format test fixture", "known_links": "", "aliases": "",
                              "schema_version_id": schema["id"], "status": "review", "identity_json": "{}",
                              "settings_json": json.dumps(st), "created_at": time.time(), "updated_at": time.time()})
    research.ingest_manual(cid, "text", {"title": "Synthetic Marshall Fire test text", "text": TEXT})

    rx = re.compile(r"^\[(S\d+-P\d+)\] \(source[^\n]*\)\n([^\n]+)", re.M)

    class R:
        status_code = 200

    def fake_post(url, json=None, **kw):
        import json as js
        user = json["messages"][0]["content"]
        ps = rx.findall(user)
        names = [l.split("### ")[1].split("  (")[0] for l in user.splitlines() if l.startswith("### ")]
        res = []
        for n in names:
            if n in CODES and ps:
                pid, text = ps[0]
                res.append({"variable": n, "value": CODES[n], "status": "suggested",
                            "evidence": [{"id": pid, "quote": text.strip()[:70], "stance": "supports"}],
                            "rationale": "synthetic fixture", "unresolved": ""})
            else:
                res.append({"variable": n, "value": "", "status": "insufficient_evidence", "evidence": []})
        payload = {"content": [{"type": "text", "text": js.dumps({"results": res})}],
                   "usage": {"input_tokens": 1000, "output_tokens": 300}, "stop_reason": "end_turn"}
        r = R()
        r.text = js.dumps(payload)
        r.json = lambda: payload
        return r

    clients.httpx.post = fake_post
    case = db.q1("SELECT * FROM cases WHERE id=?", (cid,))
    client = clients.AnthropicClient("claude-sonnet-5-5", "fixture-not-a-key")
    rep = coding.run_coding(case, st, client, None, lambda *a: None, 3.0, None)

    class H:
        user = "fixture-reviewer"
    api_review(H(), str(cid), {"variable": "SYSTEM_LEVEL", "action": "edit", "value": "2",
                               "reason": "fixture: human edit that must survive migration"})
    db.conn().execute("PRAGMA wal_checkpoint(TRUNCATE)")
    db.conn().commit()
    from app.config import DB_PATH
    src = sqlite3.connect(str(DB_PATH))
    dst = sqlite3.connect(out_path)
    src.backup(dst)
    dst.close()
    print("fixture written:", out_path, "| run", rep["run_id"], "| calls", rep["calls"])


if __name__ == "__main__":
    main(sys.argv[1])
