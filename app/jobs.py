"""Background job runner. Jobs are rows in SQLite; a single worker thread executes them. On server start, jobs that
were running when the server stopped are re-queued and resume from their last completed stage."""
from __future__ import annotations

import json
import threading
import time

from . import db

_worker = None
_wake = threading.Event()


def enqueue(case_id: int, kind: str, params: dict | None = None) -> int:
    active = db.q1("SELECT id FROM jobs WHERE case_id=? AND status IN ('queued','running')", (case_id,))
    if active:  # prevents duplicate submissions (and duplicate paid calls)
        return active["id"]
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


def _loop():
    from .research import run_research
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
    # recover interrupted jobs
    db.ex("UPDATE jobs SET status='queued', message='Resumed after restart' WHERE status='running'")
    if _worker is None:
        _worker = threading.Thread(target=_loop, daemon=True, name="wfd-worker")
        _worker.start()
