"""Equal independent providers + first-screen provider choice (DECISIONS D-036). Run:
    python -m tests.test_independent_providers

Fully offline: model providers are scripted stand-ins, search is the labelled TEST-FIXTURE provider, and a network
guard makes any non-local connection fail the test. Checks are numbered after the owner's two requests:
  P1–P20  first-screen provider choice      E1–E21  equal providers, evidence/analysis versions, cache identity (K-40)
"""
from __future__ import annotations

import glob
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="wfdindep_"))
os.environ["WFD_DATA_DIR"] = str(TMP / "data")
for k in ("ANTHROPIC_API_KEY", "TAVILY_API_KEY", "BRAVE_API_KEY", "OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL",
          "WFD_TEST_FIXTURE", "WFD_PASSWORD"):
    os.environ.pop(k, None)
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PASS, FAIL = [], []
NET = {"blocked": []}


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS " if cond else "  FAIL ") + name + (f"  — {detail}" if detail and not cond else ""))


# ----------------------------------------------------------------------------------------------- network guard
_real_connect = socket.socket.connect


def _guard(self, addr):
    host = addr[0] if isinstance(addr, tuple) else str(addr)
    if host not in ("127.0.0.1", "localhost", "::1"):
        NET["blocked"].append(host)
        raise OSError(f"network access blocked in tests: {host}")
    return _real_connect(self, addr)


socket.socket.connect = _guard

CORPUS = ("Hill Country flash flood, Kerr County, Texas, July 4, 2025. Kerr County officials did not send a CodeRED "
          "alert to residents along the Guadalupe River before the water rose. The National Weather Service issued a "
          "flash flood warning and Wireless Emergency Alerts reached some phones. The county emergency management "
          "office later said the local alerting system was not activated in time. ")
PX_HEAD = "[S"


class Fake:
    """Scripted provider stand-in. Records every request it receives (never a real network call)."""
    supports_schema = False
    CALLS: list = []

    def __init__(self, provider, model, policy=None, fail=False, unavailable=False):
        self.provider, self.model = provider, model
        self.policy = policy or {}
        self.fail, self.unavailable = fail, unavailable

    def generation_settings(self):
        return {"stand_in": self.provider}

    def check_available(self):
        from app.llm.clients import LLMError
        if self.unavailable == "rejected":
            raise LLMError(f"{self.provider} key was rejected (test)", config_error=True, attempts=0)
        if self.unavailable == "unreachable":
            raise LLMError(f"could not reach {self.provider} (test)")

    def complete(self, system, user, max_tokens=4000):
        import re
        from app.llm.clients import LLMError
        Fake.CALLS.append({"provider": self.provider, "user": user})
        if self.fail:
            raise LLMError("HTTP 500 from provider (test)", possibly_billed=True, attempts=1)
        names = [l.split("### ")[1].split("  (")[0] for l in user.splitlines() if l.startswith("### ")]
        ps = re.findall(r"^\[(S\d+-P\d+)\] \(source[^\n]*\)\n([^\n]+)", user, re.M)
        res = []
        for n in names:
            v = self.policy.get(n)
            if v is None or not ps:
                res.append({"variable": n, "value": "", "status": "insufficient_evidence", "evidence": []})
                continue
            pid, text = ps[0]
            res.append({"variable": n, "value": v, "status": "suggested", "rationale": f"{self.provider} rationale",
                        "unresolved": "", "evidence": [{"id": pid, "quote": text.strip()[:60], "stance": "supports"}]})
        return {"text": json.dumps({"results": res}), "input_tokens": 1000, "output_tokens": 200, "stop_reason": "end_turn"}


POLICY = {"anthropic": {"SYSTEM_LEVEL": "3", "FAILURE_TYPE": "6"}, "openai": {"SYSTEM_LEVEL": "3", "FAILURE_TYPE": "2"}}
STATE = {"fail": set(), "unavailable": {}}


def fake_make_client(provider, model, settings=None):
    from app.config import env
    if provider == "anthropic" and env("ANTHROPIC_API_KEY"):
        return Fake("anthropic", "claude-sonnet-5-5", POLICY["anthropic"], "anthropic" in STATE["fail"],
                    STATE["unavailable"].get("anthropic", False))
    if provider == "openai" and env("OPENAI_API_KEY"):
        return Fake("openai", "gpt-6.1-sol", POLICY["openai"], "openai" in STATE["fail"],
                    STATE["unavailable"].get("openai", False))
    return None


def set_keys(an: bool, oa: bool):
    for k, on in (("ANTHROPIC_API_KEY", an), ("OPENAI_API_KEY", oa)):
        if on:
            os.environ[k] = "test-not-a-real-key"
        else:
            os.environ.pop(k, None)


def main():
    from app import coding, db, export, jobs, research, server
    from app.config import DEFAULT_SETTINGS
    from app.llm import clients
    clients.make_client = fake_make_client
    clients.get_client = lambda p, m, s=None: next((c for c in (fake_make_client(x, m, s) for x in
                                                     ([p] if p not in ("auto", "", None) else ["anthropic", "openai"])) if c), None)
    db.conn()
    server.bootstrap_schema()
    fx = TMP / "fx.json"
    fx.write_text(json.dumps({"results": []}))
    os.environ["WFD_TEST_FIXTURE"] = str(fx)

    class H:
        user = "coder1"

    def create(mode=None, extra_settings=None, pause=None, label="", start=True):
        body = {"name": "Hill Country flash flood", "location": "Kerr County, Texas", "date_text": "July 4, 2025",
                "details": label, "start": start, "settings": {"max_search_rounds": 0, "budget_usd": 10,
                                                               "openai_budget_usd": 10, **(extra_settings or {})}}
        if mode:
            body["mode"] = mode
        if pause is not None:
            body["pause_before_coding"] = pause
        r = server.api_new_case(H(), body)
        research.ingest_manual(r["id"], "text", {"title": "County statement", "text": CORPUS * 4})
        return r

    def run_job(jid):
        research.run_research(db.q1("SELECT * FROM jobs WHERE id=?", (jid,)))
        return db.q1("SELECT * FROM jobs WHERE id=?", (jid,))

    def provs(cid, var="SYSTEM_LEVEL"):
        return {r["provider"] for r in db.q("SELECT provider FROM suggestions WHERE case_id=? AND variable=? AND "
                                             "provider IS NOT NULL", (cid, var))}

    def n_queries(jid):
        return db.q1("SELECT COUNT(*) n FROM search_queries WHERE job_id=?", (jid,))["n"]

    set_keys(True, True)
    print("\n[P] First-screen provider choice")
    r1 = create("anthropic_only", label="P1")
    j1 = run_job(r1["job_id"])
    check("P1 initial run with Claude only: only Claude results", j1["status"] == "done" and provs(r1["id"]) == {"anthropic"},
          f"{j1['status']} {j1['message']} {provs(r1['id'])}")
    r2 = create("openai_only", label="P2")
    j2 = run_job(r2["job_id"])
    check("P2 initial run with OpenAI only: only OpenAI results", j2["status"] == "done" and provs(r2["id"]) == {"openai"})
    r3 = create("dual_independent", label="P3")
    j3 = run_job(r3["job_id"])
    check("P3 initial run with both providers: both results", j3["status"] == "done" and provs(r3["id"]) == {"anthropic", "openai"})
    check("P4/E2 dual mode performs one search, not two (same query count as a single-provider run)",
          n_queries(r3["job_id"]) == n_queries(r1["job_id"]) and n_queries(r3["job_id"]) > 0,
          f"dual {n_queries(r3['job_id'])} vs single {n_queries(r1['job_id'])}")
    runs3 = db.q("SELECT * FROM runs WHERE case_id=? AND provider IS NOT NULL", (r3["id"],))
    check("P5/E4 dual mode stores separate Claude and OpenAI results (separate runs, separate rows)",
          len(runs3) == 2 and {r["provider"] for r in runs3} == {"anthropic", "openai"}
          and len({r["id"] for r in runs3}) == 2)

    set_keys(False, True)
    modes = {m["mode"]: m for m in server.available_modes(DEFAULT_SETTINGS)}
    check("P6 Claude unavailable: 'Claude only' and the dual option are disabled with a plain reason, no key shown",
          not modes["anthropic_only"]["available"] and not modes["dual_independent"]["available"]
          and "ANTHROPIC_API_KEY is not set" in modes["anthropic_only"]["reason"] and "test-not" not in json.dumps(modes))
    n_cases = db.q1("SELECT COUNT(*) n FROM cases")["n"]
    try:
        server.api_new_case(H(), {"name": "x", "mode": "anthropic_only"})
        check("P6 server refuses to start Claude only without Claude; nothing created", False)
    except server.ApiError:
        check("P6 server refuses to start Claude only without Claude; nothing created",
              db.q1("SELECT COUNT(*) n FROM cases")["n"] == n_cases)
    check("P8 one provider unavailable, the other still offered", modes["openai_only"]["available"])
    set_keys(True, False)
    modes = {m["mode"]: m for m in server.available_modes(DEFAULT_SETTINGS)}
    check("P7 OpenAI unavailable: 'OpenAI only' and the dual option are disabled; Claude only offered",
          not modes["openai_only"]["available"] and not modes["dual_independent"]["available"]
          and modes["anthropic_only"]["available"])
    set_keys(True, True)
    STATE["unavailable"] = {"openai": "rejected"}
    try:
        server.api_new_case(H(), {"name": "x", "mode": "dual_independent", "settings": {"budget_usd": 10}})
        check("P8b a rejected key (free availability check) blocks the start before any search", False)
    except server.ApiError as e:
        check("P8b a rejected key (free availability check) blocks the start before any search",
              "rejected" in str(e) and db.q1("SELECT COUNT(*) n FROM cases")["n"] == n_cases)
    STATE["unavailable"] = {"openai": "unreachable"}
    chk = server.provider_checks("openai_only", DEFAULT_SETTINGS)
    check("P8c provider unreachable right now: allowed but marked unverified (checked again before paying)",
          chk["openai"]["ok"] and not chk["openai"]["verified"])
    STATE["unavailable"] = {}

    pv = {m: server.api_estimate_preview(H(), {"mode": [m], "budget_usd": ["10"], "openai_budget_usd": ["10"]})
          for m in ("anthropic_only", "openai_only", "dual_independent")}
    sel = {m: [p["provider"] for p in e["providers"] if p["selected"]] for m, e in pv.items()}
    check("P9 preliminary estimate changes with the selection", sel == {"anthropic_only": ["anthropic"],
          "openai_only": ["openai"], "dual_independent": ["anthropic", "openai"]}
          and len({e["cost_high"] for e in pv.values()}) == 3, str(sel))
    check("P9b unselected provider shown as $0 'not selected'", all(p["cost_high"] == 0 and p["cost_low"] == 0
          for e in pv.values() for p in e["providers"] if not p["selected"]))
    check("P10/E15 search estimate is one shared line, identical for every mode (never doubled in dual mode)",
          len({e["search_cost_max"] for e in pv.values()}) == 1 and len({e["search_queries_max"] for e in pv.values()}) == 1)
    d = pv["dual_independent"]
    check("P11 combined = shared search + selected providers",
          abs(d["combined_high"] - ((d["search_cost_max"] or 0) + sum(p["cost_high"] for p in d["providers"] if p["selected"]))) < 1e-6)
    try:
        server.api_new_case(H(), {"name": "x", "mode": "dual_independent", "settings": {"budget_usd": 0.01}})
        check("P12 server rejects a mode whose hard budget cannot cover one request per provider", False)
    except server.ApiError as e:
        check("P12 server rejects a mode whose hard budget cannot cover one request per provider",
              "cannot cover" in str(e) and db.q1("SELECT COUNT(*) n FROM cases")["n"] == n_cases, str(e))
    try:
        server.api_new_case(H(), {"name": "x", "mode": "openai_only", "settings": {"budget_usd": 10, "openai_budget_usd": 0.01}})
        check("P12b OpenAI budget too small for one OpenAI request → rejected", False)
    except server.ApiError as e:
        check("P12b OpenAI budget too small for one OpenAI request → rejected", "OpenAI budget" in str(e))
    try:
        server.api_new_case(H(), {"name": "x", "mode": "anthropic_primary_openai_review"})
        check("P12c cross-model review cannot be started", False)
    except server.ApiError:
        check("P12c cross-model review cannot be started", True)

    r13 = create("dual_independent", pause=True, label="P13")
    c13 = server.api_case(H(), str(r13["id"]))
    jb = server.api_job(H(), str(r13["id"]))
    check("P13 the selected mode is stored on the server (case settings and job), not only in the browser",
          c13["settings"]["coding_mode"] == "dual_independent" and jb["params"]["mode"] == "dual_independent")
    db.update("jobs", r13["job_id"], {"status": "running", "stage": "search"})
    jobs.recover_interrupted()  # simulated server restart
    jb2 = server.api_job(H(), str(r13["id"]))
    check("P14 server restart keeps the selected mode", jb2["params"]["mode"] == "dual_independent"
          and jb2["status"] == "needs_input")
    jobs.resume(r13["job_id"], {})
    n_calls = len(Fake.CALLS)
    j13 = run_job(r13["job_id"])
    st13 = json.loads(j13["state_json"])
    check("P13b pause after research: needs approval, NO model request sent, exact estimate shown",
          j13["status"] == "needs_input" and st13.get("awaiting") == "coding_approval" and len(Fake.CALLS) == n_calls
          and "Nothing has been sent to a model" in j13["message"], f"{j13['status']} {j13['message'][:120]}")
    check("P13c the user can stop after research at zero model cost",
          db.q1("SELECT COUNT(*) n FROM usage WHERE case_id=? AND kind='model'", (r13["id"],))["n"] == 0)
    server.api_resume(H(), str(r13["job_id"]), {"coding_approved": True})
    j13 = run_job(r13["job_id"])
    check("P13d after approval, coding runs with the selected providers", j13["status"] == "done"
          and provs(r13["id"]) == {"anthropic", "openai"}, f"{j13['status']} {j13['message']}")

    r15 = create("dual_independent", label="P15")
    server.api_stop_provider(H(), str(r15["job_id"]), "openai")
    j15 = run_job(r15["job_id"])
    cells = {r["name"]: r for r in export.case_results(r15["id"])["rows"]}["SYSTEM_LEVEL"]["cells"]
    check("P15 stopping OpenAI does not stop Claude", cells["anthropic"]["state"] == "suggested"
          and cells["openai"]["state"] == "stopped", str({k: v["state"] for k, v in cells.items()}))
    STATE["fail"] = {"openai"}
    r16 = create("dual_independent", label="P16")
    run_job(r16["job_id"])
    STATE["fail"] = set()
    cells = {r["name"]: r for r in export.case_results(r16["id"])["rows"]}["SYSTEM_LEVEL"]["cells"]
    check("P16 a failed provider does not erase the other provider's completed result",
          cells["anthropic"]["value"] == "3" and cells["openai"]["state"] == "failed")

    snap_before = json.dumps(db.q("SELECT * FROM suggestions WHERE case_id=? ORDER BY id", (r1["id"],)), default=str)
    create("dual_independent", label="P17 other case")
    check("P17 existing cases remain unchanged when a new case runs",
          json.dumps(db.q("SELECT * FROM suggestions WHERE case_id=? ORDER BY id", (r1["id"],)), default=str) == snap_before)
    server.api_review(H(), str(r3["id"]), {"variable": "SYSTEM_LEVEL", "action": "edit", "value": "2", "reason": "AAR"})
    jre = server.api_recode(H(), str(r3["id"]), {"mode": "dual_independent"})["job_id"]
    run_job(jre)
    rv = db.q1("SELECT * FROM reviews WHERE case_id=? AND variable='SYSTEM_LEVEL'", (r3["id"],))
    check("P18/E18 Human final unchanged by re-analysis", rv["value"] == "2" and rv["action"] == "edited")
    js = (ROOT / "web" / "app.js").read_text()
    check("P19 first form and Re-analyze use the same server-side provider definitions",
          [m["mode"] for m in server.available_modes(DEFAULT_SETTINGS)] == list(coding.PUBLIC_MODES)
          and "STATUS.modes" in js and "availModes()" in js and "/api/estimate_preview?mode=" in js)

    print("\n[E] Equal providers, shared evidence, analysis versions, cache identity")
    ra1 = db.q("SELECT evidence_snapshot_id e, analysis_spec_id a FROM runs WHERE case_id=? AND provider IS NOT NULL", (r3["id"],))
    check("E1 every provider run records the shared evidence snapshot and analysis version",
          all(x["e"] and x["a"] for x in ra1))
    first = [c for c in Fake.CALLS if "P3" in c["user"]]
    by_p = {}
    for c in first:
        by_p.setdefault(c["provider"], []).append(c["user"])
    check("E3 both providers received the identical evidence (byte-identical prompts) and the same snapshot",
          by_p.get("anthropic") and by_p.get("anthropic") == by_p.get("openai")
          and len({(x["e"], x["a"]) for x in ra1[:2]}) == 1)
    rr = db.q("SELECT role, interpretation FROM runs WHERE case_id=? AND provider IS NOT NULL", (r3["id"],))
    check("E6 execution order does not create a hierarchy: both runs 'independent'",
          {(x["role"], x["interpretation"]) for x in rr} == {("independent", "independent")})
    srow = {r["name"]: r for r in export.case_results(r1["id"])["rows"]}
    a = db.q1("SELECT * FROM suggestions WHERE case_id=? AND variable='FAILURE_TYPE' AND provider='anthropic'", (r3["id"],))
    b = db.q1("SELECT * FROM suggestions WHERE case_id=? AND variable='FAILURE_TYPE' AND provider='openai'", (r3["id"],))
    check("E6b comparison is symmetric (order of providers does not matter)",
          coding.comparison_kind(a, b) == coding.comparison_kind(b, a) == "same_analysis_version")
    row3 = {r["name"]: r for r in export.case_results(r3["id"])["rows"]}["FAILURE_TYPE"]
    check("E6c with two providers the default suggestion is a neutral combined view (blank when they differ), "
          "never Claude's row", row3["suggestion"]["display_kind"] == "two_providers" and row3["suggestion"]["provider"] is None
          and row3["suggestion"]["value"] == "")

    rC = create("anthropic_only", label="E7")
    run_job(rC["job_id"])
    n0 = len(Fake.CALLS)
    jd = server.api_recode(H(), str(rC["id"]), {"mode": "dual_independent"})["job_id"]
    run_job(jd)
    new = [c["provider"] for c in Fake.CALLS[n0:]]
    check("E7 a Claude-only result is reused when Claude later takes part in dual mode (only OpenAI is sent)",
          new and set(new) == {"openai"}, str(set(new)))
    n0 = len(Fake.CALLS)
    jd2 = server.api_recode(H(), str(r2["id"]), {"mode": "dual_independent"})["job_id"]
    run_job(jd2)
    new = [c["provider"] for c in Fake.CALLS[n0:]]
    check("E8 an OpenAI-only result is reused when OpenAI later takes part in dual mode (only Claude is sent)",
          new and set(new) == {"anthropic"}, str(set(new)))
    n0 = len(Fake.CALLS)
    jd3 = server.api_recode(H(), str(rC["id"]), {"mode": "dual_independent"})["job_id"]
    run_job(jd3)
    check("E9 identical validated inputs → cache hits (no request)", len(Fake.CALLS) == n0)
    hit = db.q1("SELECT cache_status, cache_source_run_id, generated_at, run_id FROM suggestions WHERE case_id=? AND "
                "variable='SYSTEM_LEVEL' AND provider='anthropic' ORDER BY id DESC", (rC["id"],))
    check("E9b a cached result keeps its provenance (original run and generation time)",
          hit["cache_status"] == "hit" and hit["cache_source_run_id"] and hit["cache_source_run_id"] != hit["run_id"]
          and hit["generated_at"], str(hit))
    est = coding.estimate(db.q1("SELECT * FROM cases WHERE id=?", (rC["id"],)),
                          {**DEFAULT_SETTINGS, **json.loads(db.q1("SELECT settings_json FROM cases WHERE id=?", (rC["id"],))["settings_json"])},
                          None, plan=coding.resolve_plan({**DEFAULT_SETTINGS}, "dual_independent")[0])
    check("E16 cached provider requests are estimated at $0 new cost",
          all(p["calls_uncached"] == 0 for p in est["providers"]) and (est["cost_high_new"] or 0) == 0, str(est["cost_high_new"]))
    research.ingest_manual(rC["id"], "text", {"title": "Later update", "text": CORPUS + " A later review found more."})
    n0 = len(Fake.CALLS)
    jd4 = server.api_recode(H(), str(rC["id"]), {"mode": "dual_independent"})["job_id"]
    run_job(jd4)
    snaps = {r["evidence_snapshot_id"] for r in db.q("SELECT evidence_snapshot_id FROM runs WHERE case_id=? AND "
                                                       "provider IS NOT NULL", (rC["id"],))}
    check("E10 a new evidence version → new snapshot (old kept) and cache misses", len(Fake.CALLS) > n0 and len(snaps) >= 2)

    prep = coding.prepare(db.q1("SELECT * FROM cases WHERE id=?", (rC["id"],)), DEFAULT_SETTINGS, ["SYSTEM_LEVEL"])
    fs, ids = prep["batches"][0]
    cl = fake_make_client("openai", "x")
    sysm = coding.system_prompt_for(cl)
    pr = coding.make_prompt(db.q1("SELECT * FROM cases WHERE id=?", (rC["id"],)), fs, ids, prep["pmap"], prep["smeta"])
    base = coding.cache_key(cl, sysm, pr, fs, ids, prep["pmap"], None, prep["codebook"])
    check("E11 different codebook version → different key",
          coding.cache_key(cl, sysm, pr, fs, ids, prep["pmap"], None, "99:other") != base)
    old_pv = coding.PROMPT_VERSION
    coding.PROMPT_VERSION = "test-other-prompt"
    pk = coding.cache_key(cl, sysm, pr, fs, ids, prep["pmap"], None, prep["codebook"])
    coding.PROMPT_VERSION = old_pv
    check("E12 different prompt version → different key", pk != base)
    cl2 = Fake("openai", "gpt-6.1-sol-2026-11")
    check("E13 different model version → different key",
          coding.cache_key(cl2, sysm, pr, fs, ids, prep["pmap"], None, prep["codebook"]) != base)
    rp = pr + coding.review_block(fs, {f["name"]: {"value": "3", "status": "suggested"} for f in fs}, "Claude")
    check("E14 cross-model context (the other model's answer in the prompt) → different key",
          coding.cache_key(cl, sysm, rp, fs, ids, prep["pmap"], None, prep["codebook"]) != base)
    check("E14b the run role label alone never changes the key (K-40)",
          coding.cache_key(cl, sysm, pr, fs, ids, prep["pmap"], None, prep["codebook"], "primary") == base)
    u = lambda jid: db.q1("SELECT COUNT(*) n FROM usage WHERE job_id=? AND kind='search'", (jid,))["n"]
    check("E15b search cost recorded once per query actually sent (first case: every query sent once)",
          u(r1["job_id"]) == n_queries(r1["job_id"]) > 0, f"{u(r1['job_id'])} vs {n_queries(r1['job_id'])}")
    check("E15c the dual case did not add search requests per provider (its identical queries came from saved "
          "results at no charge)", u(r3["job_id"]) <= n_queries(r3["job_id"]) and u(r3["job_id"]) == 0)

    # E17: historical records unchanged by the migration (copy of a database produced by deployed code c57214a)
    src = ROOT / "tests" / "fixtures" / "legacy_c57214a_marshall.sqlite3"
    cp = TMP / "legacy_copy.sqlite3"
    shutil.copy(src, cp)
    con = sqlite3.connect(str(cp))
    con.row_factory = sqlite3.Row
    tabs = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    before = {t: [dict(r) for r in con.execute(f"SELECT * FROM {t}")] for t in tabs}
    from app import migrations
    migrations.migrate(con)
    migrations.migrate(con)  # repeatable
    after = {t: [dict(r) for r in con.execute(f"SELECT * FROM {t}")] for t in tabs}
    same = all([{k: v for k, v in r.items() if k in (before[t][0] if before[t] else {})} for r in after[t]] == before[t]
               for t in tabs)
    check("E17 historical provider records unchanged by the migration (only new empty columns added)", same)
    check("E17b historical rows get NO rewritten role/interpretation; it is derived at read time",
          all(r.get("interpretation") is None for r in after.get("suggestions", []))
          and coding.interpretation_of({"role": None}) == "independent"
          and coding.interpretation_of({"role": "reviewer"}) == "cross_model_review")
    con.close()

    a2 = dict(a); a2["evidence_snapshot_id"] = (a2["evidence_snapshot_id"] or 0) + 1000
    check("E19 independent comparison requires matching versions", coding.comparison_kind(a2, b) == "different_versions")
    rv_ = dict(b); rv_["role"] = "reviewer"; rv_["interpretation"] = None
    check("E20 cross-model results are excluded from independent agreement", coding.comparison_kind(a, rv_) == "cross_model_review")

    # ------------------------------------------------------------------ browser: first form (three choices)
    print("\n[B] Browser: first form, keyboard, disabled reasons, estimates, confirmation, mobile")
    shots = TMP / "shots"
    shots.mkdir(exist_ok=True)
    ui_ok = {}

    def serve(port, an, oa, data_dir=None):
        env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "WFD_TEST_FIXTURE")}
        env.update({"WFD_PORT": str(port), "WFD_DATA_DIR": str(data_dir or TMP / f"ui{port}")})
        if an:
            env["ANTHROPIC_API_KEY"] = "test-not-a-real-key"
        if oa:
            env["OPENAI_API_KEY"] = "test-not-a-real-key"
        p = subprocess.Popen([sys.executable, "-m", "app.server"], cwd=str(ROOT), env=env,
                             stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        for _ in range(80):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=1)
                break
            except Exception:
                time.sleep(0.25)
        return p

    from playwright.sync_api import sync_playwright
    port = 18900 + os.getpid() % 300
    srv = serve(port, True, True, data_dir=TMP / "data")  # same database as above: the review page shows real rows
    try:
        with sync_playwright() as pw:
            br = pw.chromium.launch()
            pg = br.new_page(viewport={"width": 1400, "height": 1000})
            errors = []
            pg.on("pageerror", lambda e: errors.append(str(e)))
            sent = []
            pg.route("**/api/providers/check", lambda route: (sent.append(1), route.fulfill(
                status=200, content_type="application/json",
                body=json.dumps({"mode": "x", "providers": {"anthropic": {"ok": True, "verified": True, "reason": ""},
                                                            "openai": {"ok": True, "verified": True, "reason": ""}}}))))
            created = []
            pg.route("**/api/cases", lambda route: (created.append(1), route.abort()) if route.request.method == "POST" else route.continue_())
            for lang in ("en", "zh"):
                pg.goto(f"http://127.0.0.1:{port}/")
                pg.evaluate(f"localStorage.setItem('wfd_lang','{lang}')")
                pg.reload()
                pg.wait_for_selector("#providerChoice", timeout=8000)
                pg.wait_for_timeout(800)
                txt = pg.inner_text("#app")
                ui_ok[f"no_hierarchy_{lang}"] = not any(w in txt for w in ("primary", "Primary", "secondary", "reviewer",
                                                                            "主编码", "复核模型", "主模型"))
                ests = {}
                for m in ("anthropic_only", "openai_only", "dual_independent"):
                    pg.check(f"input[name=pmode][value={m}]")
                    pg.wait_for_timeout(700)
                    ests[m] = pg.inner_text("#estBox")
                    if lang == "en":
                        pg.locator(".hero .panel.form").screenshot(path=str(shots / f"home_{m}.png"))
                ui_ok[f"estimates_change_{lang}"] = len(set(ests.values())) == 3
                if lang == "en":
                    ui_ok["not_selected_lines"] = "not selected" in ests["anthropic_only"] and "not selected" in ests["openai_only"] \
                        and "not selected" not in ests["dual_independent"]
                    ui_ok["shared_search_line"] = all("Shared web search (runs once)" in e for e in ests.values())
            pg.evaluate("localStorage.setItem('wfd_lang','en')")
            pg.reload()
            pg.wait_for_selector("#providerChoice")
            pg.wait_for_timeout(600)
            ui_ok["default_claude_only"] = pg.is_checked("input[name=pmode][value=anthropic_only]")
            pg.focus("input[name=pmode][value=anthropic_only]")
            pg.keyboard.press("ArrowRight")
            pg.wait_for_timeout(500)
            ui_ok["keyboard_arrow_selects_next"] = pg.is_checked("input[name=pmode][value=openai_only]")
            pg.check("input[name=pmode][value=dual_independent]")
            pg.wait_for_timeout(600)
            pg.fill("#f_name", "Hill Country flash flood")
            pg.click("#startBtn")
            pg.wait_for_selector("#csOk", timeout=5000)
            dlg = pg.inner_text(".modal")
            pg.locator(".modal").screenshot(path=str(shots / "confirm_dual.png"))
            ui_ok["confirm_dialog_mode_and_estimate"] = ("Claude + OpenAI — independent comparison" in dlg
                                                         and "One shared search" in dlg and "Combined (worst case)" in dlg
                                                         and "may still be billed" in dlg)
            pg.click("#csCancel")
            ui_ok["cancel_creates_nothing"] = not created and len(sent) == 1
            pg.set_viewport_size({"width": 390, "height": 900})
            pg.wait_for_timeout(500)
            ui_ok["mobile_no_horizontal_scroll"] = pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
            pg.screenshot(path=str(shots / "home_mobile.png"), full_page=True)
            pg.set_viewport_size({"width": 1500, "height": 1000})
            pg.goto(f"http://127.0.0.1:{port}/#/case/{r3['id']}/review")
            pg.reload()
            pg.wait_for_timeout(1500)
            pg.click("tr[data-v='FAILURE_TYPE']")
            pg.wait_for_timeout(700)
            rtxt = pg.inner_text("#app")
            # provider-related text only: the codebook's own wording ("Primary classification…", "secondary codes")
            # and its rule notes are research content, not a provider hierarchy
            ptxt = pg.evaluate("""() => { const c = document.querySelector('#app').cloneNode(true);
                c.querySelectorAll('.def, .callout.warn, td:nth-child(2)').forEach(e => e.remove()); return c.innerText; }""")
            pg.screenshot(path=str(shots / "review_two_providers.png"))
            pg.locator("#wbDetail").screenshot(path=str(shots / "review_detail_two_providers.png"))
            # phrases the old interface used for a provider hierarchy (the codebook's own words are not checked)
            HIER = ("primary coder", "primary model", "Primary model", "primary result", "primary or most recent",
                    "Claude primary", "OpenAI primary", "secondary model", "secondary coder", "reviewer (saw",
                    "OpenAI review", "Claude review", "Default suggestion", "主编码", "主模型", "复核模型")
            role_badges = pg.evaluate("""() => [...document.querySelectorAll('#app .badge')].map(b => b.innerText.trim())
                .filter(t => ['primary', 'secondary', 'reviewer', '主编码', '独立编码', 'review', '复核'].includes(t))""")
            ui_ok["review_no_hierarchy"] = not any(w in rtxt for w in HIER) and not role_badges
            if not ui_ok["review_no_hierarchy"]:
                print("  hierarchy phrases found:", [w for w in HIER if w in rtxt])
            ui_ok["review_combined_view_and_both_columns"] = ("Both providers — combined view" in rtxt
                                                              and "Claude suggestion" in rtxt and "OpenAI suggestion" in rtxt)
            ui_ok["no_js_errors"] = not errors
            br.close()
    finally:
        srv.terminate()
        srv.wait(10)
    srv = serve(port + 1, True, False)
    try:
        with sync_playwright() as pw:
            br = pw.chromium.launch()
            pg = br.new_page(viewport={"width": 1400, "height": 1000})
            pg.goto(f"http://127.0.0.1:{port + 1}/")
            pg.evaluate("localStorage.setItem('wfd_lang','en')")
            pg.reload()
            pg.wait_for_selector("#providerChoice")
            pg.wait_for_timeout(600)
            ui_ok["disabled_with_reason"] = (pg.is_disabled("input[name=pmode][value=openai_only]")
                                             and pg.is_disabled("input[name=pmode][value=dual_independent]")
                                             and "OPENAI_API_KEY is not set" in pg.inner_text("#providerChoice"))
            pg.locator("#providerChoice").screenshot(path=str(shots / "home_openai_unavailable.png"))
            br.close()
    finally:
        srv.terminate()
        srv.wait(10)
    for k, v in ui_ok.items():
        check(f"browser: {k}", bool(v))
    print("  screenshots in", shots)

    check("P20/E21 no live Tavily, Anthropic or OpenAI request was attempted", not NET["blocked"], str(NET["blocked"]))
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED:", *FAIL, sep="\n  ")
        sys.exit(1)


if __name__ == "__main__":
    main()
