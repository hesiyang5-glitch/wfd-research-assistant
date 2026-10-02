"""Background job runner. Jobs are rows in SQLite; a single worker thread executes them. On server start, jobs that
were running when the server stopped are re-queued and resume from their last completed stage."""
from __future__ import annotations

import json
import threading
import time

from . import db

_worker = None
_wake = threading.Event()


def enqueue(case_id: int, kind: str, params: dict | None = None, behind_active: bool = False) -> int:
    """behind_active=True (provider Resume only) queues a new job after the case's running job instead of
    returning the running one; the single worker runs them one after another."""
    active = db.q1("SELECT id FROM jobs WHERE case_id=? AND status IN ('queued','running')", (case_id,))
    if active and not behind_active:  # prevents duplicate submissions (and duplicate paid calls)
        return active["id"]
    if behind_active:
        dup = db.q1("SELECT id FROM jobs WHERE case_id=? AND status='queued' AND params_json=?",
                    (case_id, json.dumps(params or {})))
        if dup:
            return dup["id"]
    jid = db.insert("jobs", {"case_id": case_id, "kind": kind, "stage": "queued", "status": "queued", "progress": 0,
                             "message": "Waiting to start", "params_json": json.dumps(params or {}), "state_json": "{}",
                             "created_at": time.time(), "updated_at": time.time(), "cancel_requested": 0})
    _wake.set()
    return jid


def resume(job_id: int, params_update: dict) -> None:
    j = db.q1("SELECT * FROM jobs WHERE id=?", (job_id,))
    params = {**json.loads(j["params_json"] or "{}"), **params_update}
    state = json.loads(j["state_json"] or "{}")
    state.pop("awaiting", None)
    db.update("jobs", job_id, {"params_json": json.dumps(params), "state_json": json.dumps(state), "status": "queued",
                               "message": "Resuming", "updated_at": time.time()})
    _wake.set()


def cancel(job_id: int) -> None:
    db.update("jobs", job_id, {"cancel_requested": 1})
    j = db.q1("SELECT status FROM jobs WHERE id=?", (job_id,))
    if j and j["status"] in ("queued", "needs_input"):
        db.update("jobs", job_id, {"status": "cancelled", "message": "Cancelled by user"})


def lower_thread_priority(nice: int = 10) -> bool:
    """Give this (worker) thread a lower CPU priority than the web-request threads, so the health check and the pages
    stay responsive while heavy work runs. Linux only; harmless elsewhere."""
    try:
        import os
        os.setpriority(os.PRIO_PROCESS, threading.get_native_id(), nice)
        return True
    except Exception:
        return False


def recover_interrupted() -> dict:
    """At startup: a job that was running when the server stopped is PAUSED for the owner (never restarted
    automatically: a crash loop must not repeat paid requests), and a model request that was in flight is counted at its
    worst-case cost, because it may have reached the provider and been billed (D-033)."""
    calls = db.q("SELECT * FROM model_calls WHERE status='sending'")
    for r in calls:
        db.update("model_calls", r["id"], {"status": "interrupted_possibly_billed",
                                           "error": "the server stopped while this request was in progress; it may "
                                                    "have been billed and is counted at its worst-case cost"})
        db.insert("usage", {"case_id": r["case_id"], "job_id": r["job_id"], "kind": "model", "provider": r["provider"],
                            "model": r["model"], "input_tokens": None, "output_tokens": None, "units": 1,
                            "cost_usd": r["cost_usd"], "estimated": 1, "at": time.time(), "call_id": r["id"],
                            "note": f"batch {r['batch_no']}: request interrupted by a server restart (counted at worst case)"})
    paused = []
    for j in db.q("SELECT * FROM jobs WHERE status='running'"):
        if j.get("cancel_requested"):
            db.update("jobs", j["id"], {"status": "cancelled", "message": "Cancelled (the server restarted while stopping)",
                                        "updated_at": time.time()})
            continue
        st = json.loads(j.get("state_json") or "{}")
        st["awaiting"] = "interrupted"
        st["interrupted_stage"] = j.get("stage")
        db.update("jobs", j["id"], {"status": "needs_input", "state_json": json.dumps(st), "updated_at": time.time(),
                                    "message": f"Interrupted by a server restart during '{j.get('stage')}'. Nothing runs "
                                               f"again until you click Resume. Completed results are kept; a request "
                                               f"that was in progress is counted at its worst-case cost."})
        db.insert("job_log", {"job_id": j["id"], "at": time.time(), "stage": j.get("stage") or "", "level": "warn",
                              "message": "server restarted while this job was running; paused (not restarted automatically)"})
        paused.append(j["id"])
    return {"interrupted_calls": len(calls), "paused_jobs": paused}


def _loop():
    from .research import run_research
    lower_thread_priority()
    while True:
        job = db.q1("SELECT * FROM jobs WHERE status='queued' ORDER BY id LIMIT 1")
        if not job:
            _wake.wait(timeout=2.0)
            _wake.clear()
            continue
        try:
            run_research(job)
        except Exception as e:  # never let the worker die
            db.update("jobs", job["id"], {"status": "failed", "error": f"{type(e).__name__}: {e}", "updated_at": time.time()})


def start_worker():
    global _worker
    recover_interrupted()  # interrupted jobs are paused for the owner, never restarted automatically
    if _worker is None:
        _worker = threading.Thread(target=_loop, daemon=True, name="wfd-worker")
        _worker.start()
