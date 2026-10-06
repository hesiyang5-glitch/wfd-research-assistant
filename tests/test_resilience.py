"""Resilience tests for the 2026-10-01 production incident (DECISIONS D-033). Run:  python -m tests.test_resilience

Offline: fake model client, local server on 127.0.0.1, no paid calls. Checks:
  [1] numerical libraries use one thread (not one per host CPU)
  [2] the evidence index is built once per case and evidence set, rebuilt when passages change, shared by threads
  [3] a model request is in the ledger BEFORE it is sent
  [4] after a restart, interrupted jobs are paused (not restarted) and in-flight requests are counted at worst case
  [5] the background worker runs at a lower CPU priority
  [6] the health check stays fast while several cost estimates run at once on ONE CPU core
The real Render limit (0.5 CPU quota) cannot be reproduced here; [6] approximates it by pinning the server to one core.
"""
from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="wfdres_"))
os.environ["WFD_DATA_DIR"] = str(TMP / "data")
for k in ("ANTHROPIC_API_KEY", "TAVILY_API_KEY", "BRAVE_API_KEY", "OPENAI_API_KEY", "OPENAI_BASE_URL",
          "WFD_TEST_FIXTURE", "WFD_PASSWORD", "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.pop(k, None)
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
UP = os.environ.get("WFD_TEST_PDFS") or (glob.glob("/root/.claude/uploads/*/") or [""])[0]

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS " if cond else "  FAIL ") + name + (f"  — {detail}" if detail and not cond else ""))


THREADS_PROBE = ("import app, numpy, sklearn.decomposition; from threadpoolctl import threadpool_info; "
                 "print(max([i['num_threads'] for i in threadpool_info()] or [0]))")


def main():
    print("\n[1] Numerical libraries use one thread")
    env = {k: v for k, v in os.environ.items() if not k.endswith("_NUM_THREADS")}
    out = subprocess.run([sys.executable, "-c", THREADS_PROBE], cwd=str(ROOT), env=env, capture_output=True, text=True)
    check("importing the app limits BLAS/OpenMP pools to 1 thread", out.stdout.strip() == "1", out.stdout + out.stderr[-300:])
    out = subprocess.run([sys.executable, "-c", THREADS_PROBE], cwd=str(ROOT), env={**env, "WFD_NATIVE_THREADS": "2"},
                         capture_output=True, text=True)
    check("WFD_NATIVE_THREADS overrides the limit", out.stdout.strip() in ("2", "1") and out.returncode == 0,
          out.stdout + out.stderr[-300:])
    out = subprocess.run([sys.executable, "-c", THREADS_PROBE], cwd=str(ROOT), env={**env, "OPENBLAS_NUM_THREADS": "3",
                                                                                     "OMP_NUM_THREADS": "3"},
                         capture_output=True, text=True)
    check("an explicit OMP/OPENBLAS setting is respected (setdefault)", out.stdout.strip() in ("3", "1") and out.returncode == 0,
          out.stdout + out.stderr[-300:])
    dk = (ROOT / "Dockerfile").read_text()
    check("Dockerfile sets the thread limits too", "OMP_NUM_THREADS=1" in dk and "OPENBLAS_NUM_THREADS=1" in dk)

    from app import coding, db, jobs, research, retrieval
    from app.config import DEFAULT_SETTINGS
    from app.server import bootstrap_schema

    db.conn()
    bootstrap_schema()
    schema = coding.active_schema()
    settings = {**DEFAULT_SETTINGS, "max_search_rounds": 0}

    def new_case(name):
        cid = db.insert("cases", {"name": name, "location": "Kerr County, Texas", "date_text": "July 4, 2025",
                                  "details": "", "known_links": "", "aliases": "", "schema_version_id": schema["id"],
                                  "status": "new", "identity_json": "{}", "settings_json": json.dumps(settings),
                                  "created_at": time.time(), "updated_at": time.time()})
        pdfs = sorted(glob.glob(os.path.join(UP, "*.pdf")))[:2]
        for p in pdfs:
            research.ingest_manual(cid, "file", {"filename": os.path.basename(p), "path": p, "title": os.path.basename(p)})
        if not pdfs:
            research.ingest_manual(cid, "text", {"title": "note", "text": ("Kerr County did not send CodeRED alerts during "
                                                                           "the July 4, 2025 flash flood. " * 200)})
        return cid

    print("\n[2] Evidence index is built once and shared")
    cid = new_case("Hill Country flash flood")
    case = db.q1("SELECT * FROM cases WHERE id=?", (cid,))
    n0 = retrieval.INDEX_BUILDS["n"]
    i1 = retrieval.get_index(cid)
    i2 = retrieval.get_index(cid)
    check("second request reuses the same index", i1 is i2 and retrieval.INDEX_BUILDS["n"] == n0 + 1,
          f"builds={retrieval.INDEX_BUILDS['n'] - n0}")
    n1 = retrieval.INDEX_BUILDS["n"]
    for _ in range(3):
        coding.estimate(case, settings, ["SYSTEM_LEVEL"])
    coding.estimate(case, settings, None)
    check("repeated cost estimates do not rebuild the index", retrieval.INDEX_BUILDS["n"] == n1,
          f"builds={retrieval.INDEX_BUILDS['n'] - n1}")
    research.ingest_manual(cid, "text", {"title": "Hill Country flash flood note",
                                         "text": ("During the July 4, 2025 Hill Country flash flood in Kerr County, Texas, "
                                                  "sirens were not sounded along the Guadalupe River. ") * 30})
    i3 = retrieval.get_index(cid)
    check("adding a source rebuilds the index (no stale evidence)", i3 is not i1 and retrieval.INDEX_BUILDS["n"] == n1 + 1, f"same={i3 is i1} builds={retrieval.INDEX_BUILDS['n'] - n1}")
    newest = db.q1("SELECT MAX(id) m FROM passages WHERE case_id=?", (cid,))["m"]
    check("rebuilt index contains the new passage", newest in {p["id"] for p in i3.passages})
    sid = db.q1("SELECT source_id FROM passages WHERE id=?", (newest,))["source_id"]
    db.update("sources", sid, {"excluded": 1})
    i4 = retrieval.get_index(cid)
    check("excluding a source rebuilds the index without it", i4 is not i3 and newest not in {p["id"] for p in i4.passages})
    db.update("sources", sid, {"excluded": 0})
    check("restoring it returns the cached earlier index", retrieval.get_index(cid) is i3)
    # concurrent callers wait for one build
    retrieval._INDEX_CACHE.clear()
    n2 = retrieval.INDEX_BUILDS["n"]
    got = []
    ts = [threading.Thread(target=lambda: got.append(retrieval.get_index(cid))) for _ in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    check("4 simultaneous requests cause exactly one build", retrieval.INDEX_BUILDS["n"] == n2 + 1 and len({id(x) for x in got}) == 1,
          f"builds={retrieval.INDEX_BUILDS['n'] - n2}")
    cid2 = new_case("Hill Country flash flood")
    check("another case gets its own index", retrieval.get_index(cid2) is not retrieval.get_index(cid))

    print("\n[3] A model request is in the ledger before it is sent")
    seen = {}

    class Fake:
        provider, model = "fake", "claude-sonnet-5-5"

        def complete(self, system, user, max_tokens=4000):
            seen["rows"] = db.q("SELECT status, cost_usd, http_attempts FROM model_calls WHERE case_id=? ORDER BY id DESC",
                                (cid,))
            names = [l.split("### ")[1].split("  (")[0] for l in user.splitlines() if l.startswith("### ")]
            body = json.dumps({"results": [{"variable": x, "value": "", "status": "insufficient_evidence", "evidence_status": "INSUFFICIENT", "evidence": []}
                                           for x in names]})
            return {"text": body, "input_tokens": 1000, "output_tokens": 300, "stop_reason": "end_turn"}

    coding.run_coding(case, settings, Fake(), None, lambda *a: None, 10.0, ["SYSTEM_LEVEL"])
    top = (seen.get("rows") or [{}])[0]
    check("during the request a 'sending' row exists", top.get("status") == "sending", str(top))
    check("the 'sending' row carries the worst-case cost and 1 attempt", (top.get("cost_usd") or 0) > 0 and top.get("http_attempts") == 1)
    after = db.q1("SELECT status FROM model_calls WHERE case_id=? ORDER BY id DESC", (cid,))
    check("after the reply the same row is completed (no duplicate row)",
          after["status"].startswith("complete") and db.q1("SELECT COUNT(*) n FROM model_calls WHERE case_id=?", (cid,))["n"] == 1,
          str(after))

    class Boom(Fake):
        def complete(self, *a, **k):
            from app.llm.clients import LLMError
            raise LLMError("read timeout", possibly_billed=True)

    coding.run_coding(case, settings, Boom(), None, lambda *a: None, 10.0, ["COUNTRY"])
    rows = db.q("SELECT status FROM model_calls WHERE case_id=? ORDER BY id", (cid,))
    check("a failed request updates its row (one row per request)",
          [r["status"] for r in rows] == [rows[0]["status"], "possibly_billed_error"], str(rows))

    print("\n[4] After a restart: pause, do not restart; count in-flight requests")
    jid = db.insert("jobs", {"case_id": cid, "kind": "recode", "stage": "coding", "status": "running", "progress": 0.8,
                             "message": "", "params_json": "{}", "state_json": json.dumps({"done": ["identify"]}),
                             "created_at": time.time(), "updated_at": time.time()})
    jid_c = db.insert("jobs", {"case_id": cid, "kind": "recode", "stage": "coding", "status": "running", "progress": 0.8,
                               "message": "", "params_json": "{}", "state_json": "{}", "cancel_requested": 1,
                               "created_at": time.time(), "updated_at": time.time()})
    spent0 = coding.case_spent(cid)
    call = db.insert("model_calls", {"case_id": cid, "job_id": jid, "provider": "openai", "model": "gpt-6.1-sol",
                                     "batch_no": 3, "status": "sending", "http_attempts": 1, "cost_usd": 0.25,
                                     "cost_estimated": 1, "at": time.time()})
    res = jobs.recover_interrupted()
    j = db.q1("SELECT * FROM jobs WHERE id=?", (jid,))
    stj = json.loads(j["state_json"])
    check("running job becomes needs_input, not queued", j["status"] == "needs_input", j["status"])
    check("state says it was interrupted and keeps completed stages",
          stj.get("awaiting") == "interrupted" and stj.get("done") == ["identify"] and stj.get("interrupted_stage") == "coding")
    check("message tells the owner nothing runs until Resume", "Resume" in (j["message"] or ""))
    check("a job that was being cancelled ends cancelled",
          db.q1("SELECT status FROM jobs WHERE id=?", (jid_c,))["status"] == "cancelled")
    c = db.q1("SELECT * FROM model_calls WHERE id=?", (call,))
    check("in-flight request is marked interrupted_possibly_billed", c["status"] == "interrupted_possibly_billed")
    check("its worst-case cost is added to the case spend", abs(coding.case_spent(cid) - spent0 - 0.25) < 1e-9,
          f"{coding.case_spent(cid) - spent0}")
    u = db.q1("SELECT * FROM usage WHERE call_id=?", (call,))
    check("usage row is marked estimated and linked to the request", u and u["estimated"] == 1 and u["provider"] == "openai")
    res2 = jobs.recover_interrupted()
    check("running recovery twice changes nothing (no double counting)",
          res2 == {"interrupted_calls": 0, "paused_jobs": []} and abs(coding.case_spent(cid) - spent0 - 0.25) < 1e-9, str(res2))
    check("the attempt still counts toward the attempt limit", coding.case_ledger(cid)["attempts_by"].get("openai", 0) >= 1)
    jobs.resume(jid, {})
    j = db.q1("SELECT * FROM jobs WHERE id=?", (jid,))
    check("Resume queues the job again and clears the interrupted flag",
          j["status"] == "queued" and "awaiting" not in json.loads(j["state_json"]))
    db.update("jobs", jid, {"status": "done"})
    src = (ROOT / "app" / "jobs.py").read_text()
    check("startup no longer re-queues running jobs", "Resumed after restart" not in src and "recover_interrupted()" in src)
    js = (ROOT / "web" / "app.js").read_text()
    check("interface shows the interrupted job with Resume / Cancel", 'st.awaiting === "interrupted"' in js and "cancelBtn2" in js)

    print("\n[5] Worker thread runs at lower CPU priority")
    if sys.platform.startswith("linux"):
        r = {}

        def probe():
            r["ok"] = jobs.lower_thread_priority()
            r["nice"] = os.getpriority(os.PRIO_PROCESS, threading.get_native_id())
        t = threading.Thread(target=probe)
        t.start(); t.join()
        main_nice = os.getpriority(os.PRIO_PROCESS, threading.get_native_id())
        check("worker thread is niced; request threads are not",
              r.get("ok") and r.get("nice", 0) > main_nice, f"{r} main={main_nice}")
    else:
        print("  SKIP (not Linux)")

    print("\n[6] Health check stays fast during several estimates (server pinned to one CPU core)")
    port = 18765 + (os.getpid() % 500)
    env2 = {k: v for k, v in os.environ.items() if not k.endswith("_NUM_THREADS")}
    env2.update({"WFD_PORT": str(port), "WFD_DATA_DIR": str(TMP / "data")})
    cmd = [sys.executable, "-m", "app.server"]
    if shutil.which("taskset"):
        cmd = ["taskset", "-c", "0"] + cmd
    srv = subprocess.Popen(cmd, cwd=str(ROOT), env=env2, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(80):
            try:
                urllib.request.urlopen(base + "/healthz", timeout=1); break
            except Exception:
                time.sleep(0.25)
        stop = time.time() + 12
        errors = []

        def load(var):
            while time.time() < stop:
                try:
                    urllib.request.urlopen(f"{base}/api/cases/{cid}/estimate?mode=single&variables={var}", timeout=60).read()
                except Exception as e:
                    errors.append(str(e)[:120])
        ts = [threading.Thread(target=load, args=(v,)) for v in ("SYSTEM_LEVEL", "COUNTRY", "")]
        [t.start() for t in ts]
        lat = []
        while time.time() < stop:
            t0 = time.time()
            try:
                urllib.request.urlopen(base + "/healthz", timeout=10).read(); lat.append(time.time() - t0)
            except Exception:
                lat.append(10.0)
            time.sleep(0.2)
        [t.join() for t in ts]
        lat.sort()
        check("estimates actually ran", not errors or len(errors) < 3, "; ".join(errors[:2]))
        check("no health check took 2 s or more (Render gives up at 5 s)", lat and lat[-1] < 2.0,
              f"n={len(lat)} max={lat[-1]*1000:.0f} ms" if lat else "no samples")
        print(f"     health checks: n={len(lat)}, median {lat[len(lat)//2]*1000:.0f} ms, max {lat[-1]*1000:.0f} ms")
    finally:
        srv.terminate()
        try:
            srv.wait(10)
        except subprocess.TimeoutExpired:
            srv.kill()

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED:", *FAIL, sep="\n  ")
        sys.exit(1)


if __name__ == "__main__":
    main()
