"""Stage timing and parallel source downloads (DECISIONS D-046). Run:  python -m tests.test_parallel_fetch

Offline: a local web server on 127.0.0.1 plays the websites (slow pages, refused pages, redirects, duplicates, a large
file). No search provider, no model, no paid request. Checks:
  [1] same stored sources with 1 download at a time and with 4 (order, status, text, duplicates, followed links)
  [2] it is faster, never more than 4 downloads at once, never more than 2 from one website
  [3] the reading limit holds: nothing beyond the limit is requested from any website
  [4] Cancel and the time limit stop the reading step; nothing is saved after the stop
  [5] failure states are recorded, not hidden; no half-downloaded file is left behind
  [6] the crash marker (D-042) still names the source being read
  [7] WFD_FETCH_PARALLEL=1 uses no download threads at all (the earlier behaviour)
  [8] time per step is measured, saved with the job, excludes waiting, and is shown on the Progress page
  [9] in a real browser: a search-only run through the job worker shows the times in Chinese and English
"""
from __future__ import annotations

import http.server
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="wfdpf_"))
os.environ["WFD_DATA_DIR"] = str(TMP / "data")
for k in ("ANTHROPIC_API_KEY", "TAVILY_API_KEY", "BRAVE_API_KEY", "OPENAI_API_KEY", "WFD_PASSWORD", "WFD_TEST_FIXTURE",
          "WFD_FETCH_PARALLEL", "WFD_FETCH_PER_HOST"):
    os.environ.pop(k, None)
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS " if cond else "  FAIL ") + name + (f"  — {detail}" if detail and not cond else ""))


# ----------------------------------------------------------------------------- local test websites
DELAY = 0.25
LOG = {"requests": [], "now": 0, "peak": 0, "host_now": {}, "host_peak": {}}
LOCK = threading.Lock()
TOPICS = ["siren activation", "wireless emergency alert", "evacuation order", "river gauge", "county dispatch",
          "camp counselors", "weather service forecast", "sheriff briefing", "state legislature", "volunteer rescue",
          "cell coverage", "reverse 911 call", "flood insurance", "road closures"]


def page(i: int) -> bytes:
    topic = TOPICS[i % len(TOPICS)]
    paras = "".join(f"<p>Report {i}, part {k}: during the Test flood of 2025 in Somewhere, Texas, the {topic} record "
                    f"number {i * 100 + k} describes what officials did and when residents were warned.</p>" for k in range(6))
    link = '<p><a href="/doc/timeline-report.pdf.html">Official after-action report timeline</a></p>' if i == 0 else ""
    return f"<html><head><title>Test flood 2025 report {i}</title></head><body><article>{paras}{link}</article></body></html>".encode()


class H(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *a):
        pass

    def do_GET(self):
        host = self.headers.get("Host", "")
        with LOCK:
            LOG["requests"].append(self.path)
            LOG["now"] += 1
            LOG["peak"] = max(LOG["peak"], LOG["now"])
            LOG["host_now"][host] = LOG["host_now"].get(host, 0) + 1
            LOG["host_peak"][host] = max(LOG["host_peak"].get(host, 0), LOG["host_now"][host])
        try:
            time.sleep(DELAY)
            path = self.path
            if path.startswith("/forbidden"):
                return self._send(403, b"no")
            if path.startswith("/missing"):
                return self._send(404, b"no")
            if path.startswith("/redirect"):
                self.send_response(302)
                self.send_header("Location", "/p/1")
                self.end_headers()
                return
            if path.startswith("/big"):
                return self._send(200, b"x" * 300_000, "application/octet-stream")
            if path.startswith("/pdf-as-html"):
                return self._send(200, b"%PDF-1.4 not really a pdf", "text/html")
            if path.startswith("/copy"):
                return self._send(200, page(2))  # same content as /p/2 at another address
            if path.startswith("/doc/"):
                return self._send(200, page(77))
            return self._send(200, page(int(path.rsplit("/", 1)[-1])))
        finally:
            with LOCK:
                LOG["now"] -= 1
                LOG["host_now"][host] -= 1

    def _send(self, code, body, ctype="text/html"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def reset_log():
    with LOCK:
        LOG.update({"requests": [], "now": 0, "peak": 0, "host_now": {}, "host_peak": {}})


def browser_part(A, B):
    import sqlite3
    import subprocess
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        check("browser check ran (Playwright available)", False, "Playwright is not installed")
        return
    data = TMP / "data_ui"
    fx = TMP / "fx.json"
    fx.write_text(json.dumps({"results": [
        {"url": f"{(A, B)[i % 2]}/p/{i}", "title": f"Test flood 2025 Somewhere Texas report {i}", "snippet": "Test flood Somewhere TX 2025"}
        for i in range(1, 9)]}))
    env = {**os.environ, "WFD_DATA_DIR": str(data), "WFD_TEST_FIXTURE": str(fx), "WFD_PORT": "8797"}
    srv = subprocess.Popen([sys.executable, "-m", "app.server"], cwd=str(ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    time.sleep(2.5)
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page(viewport={"width": 1400, "height": 950})
            errors = []
            pg.on("pageerror", lambda e: errors.append(str(e)))
            pg.goto("http://127.0.0.1:8797/#/")
            pg.fill("#f_name", "Test flood")
            pg.fill("#f_location", "Somewhere, Texas")
            pg.fill("#f_date", "2025")
            pg.check("input[name=rmode][value=search_only]")
            pg.click("#startBtn")
            pg.wait_for_url("**/progress", timeout=10000)
            for _ in range(90):
                if pg.locator("#rerunBtn").count():
                    break
                pg.wait_for_timeout(1000)
            zh = pg.inner_text("#stageTimes") if pg.locator("#stageTimes").count() else ""
            pg.click("#langBtn")
            pg.wait_for_timeout(800)
            en = pg.inner_text("#stageTimes") if pg.locator("#stageTimes").count() else ""
            pg.screenshot(path=str(TMP / "progress_times.png"))
            b.close()
        con = sqlite3.connect(str(data / "wfd.sqlite3"))
        job = con.execute("SELECT status, state_json FROM jobs ORDER BY id DESC LIMIT 1").fetchone()
        n_ok = con.execute("SELECT COUNT(*) FROM sources WHERE fetch_status='ok'").fetchone()[0]
        log = [r[0] for r in con.execute("SELECT message FROM job_log")]
        tm = json.loads(job[1]).get("timings", {})
        check("the search-only run finished and read the fixture pages", job[0] == "done" and n_ok == 8, f"{job[0]} / {n_ok} read")
        check("the job worker downloaded 4 at a time", any("up to 4 download" in m for m in log), str(log[-4:]))
        check("the job stored a time for the search and reading steps", tm.get("fetch", 0) > 0 and "search" in tm, str(tm))
        check("Progress page shows the per-step times (Chinese)", "本次运行各步骤用时" in zh and "合计" in zh and "秒" in zh, zh)
        check("Progress page shows the per-step times (English)", "Time spent per step in this run" in en and "total" in en, en)
        check("no page errors in the browser", not errors, str(errors))
        print("  screenshot:", TMP / "progress_times.png")
    finally:
        srv.terminate()


def main():
    from app import config, db, ingest, jobs, research, server
    from app.config import DEFAULT_SETTINGS
    db.conn()
    server.bootstrap_schema()
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    A, B = f"http://127.0.0.1:{port}", f"http://localhost:{port}"  # two "websites" (different host names)

    def new_case(**over):
        s = {**DEFAULT_SETTINGS, "follow_links": True, **over}
        return db.insert("cases", {"name": "Test flood", "location": "Somewhere, TX", "date_text": "2025", "details": "",
                                   "known_links": "", "aliases": "", "schema_version_id": 1, "status": "new",
                                   "identity_json": "{}", "settings_json": json.dumps(s),
                                   "created_at": time.time(), "updated_at": time.time()})

    def new_ctx(cid):
        jid = jobs.enqueue(cid, "research", {"identity_confirmed": True})
        return research.Ctx(db.q1("SELECT * FROM jobs WHERE id=?", (jid,)))

    def cands(urls):
        # scores fall with position so the ranked order is fixed and known
        return [{"url": u, "title": "Test flood 2025 Somewhere TX", "snippet": "", "published": "",
                 "identity_score": round(0.99 - 0.001 * i, 3), "purpose": "test"} for i, u in enumerate(urls)]

    def snapshot(cid, base):
        rows = db.q("SELECT * FROM sources WHERE case_id=? ORDER BY id", (cid,))
        ids = {r["id"]: n for n, r in enumerate(rows)}
        out = []
        for r in rows:
            text = "\n".join(p["text"] for p in db.q("SELECT text FROM passages WHERE source_id=? ORDER BY seq", (r["id"],)))
            out.append((r["url"].replace(base[0], "A").replace(base[1], "B"), (r["final_url"] or "").replace(base[0], "A").replace(base[1], "B"),
                        r["fetch_status"], r["fetch_error"], r["origin"], r["content_type"], r["content_hash"],
                        ids.get(r["duplicate_of"]), ids.get(r["near_duplicate_of"]), r["relevance_status"], r["n_passages"],
                        (r["found_via"] or "").split(" in S")[0], text))
        return out

    urls = ([f"{A}/p/{i}" for i in range(0, 6)] + [f"{B}/p/{i}" for i in range(6, 10)] +
            [f"{A}/forbidden/aar", f"{B}/missing/x", f"{A}/copy/2", f"{B}/redirect/1", f"{A}/pdf-as-html", f"{B}/p/12"])
    weak = {"url": f"{A}/p/50", "title": "unrelated", "snippet": "", "identity_score": 0.1, "purpose": "test"}

    def run(workers, cid=None, c=None, **over):
        config.FETCH_PARALLEL = workers
        cid = cid or new_case(**over)
        ctx = new_ctx(cid)
        reset_log()
        t0 = time.time()
        err = None
        try:
            research.fetch_candidates(ctx, c if c is not None else cands(urls) + [weak])
            q = ctx.state.pop("link_queue", [])
            if q:
                research.fetch_candidates(ctx, q, "followed link")
        except (research.Budget, research.Cancelled) as e:
            err = e
        return cid, ctx, time.time() - t0, err

    print("\n[1] Same stored sources with 1 download at a time and with 4")
    c1, _, t_serial, _ = run(1)
    req_serial = sorted(LOG["requests"])
    c4, ctx4, t_par, _ = run(4)
    req_par = sorted(LOG["requests"])
    s1, s4 = snapshot(c1, (A, B)), snapshot(c4, (A, B))
    check("same sources, same order, same status / error / text / duplicate and relevance marks", s1 == s4,
          next((f"{a[:4]} != {b[:4]}" for a, b in zip(s1, s4) if a != b), f"{len(s1)} vs {len(s4)} rows"))
    check("the run covers ok, refused (403), missing (404), duplicate, redirect and followed-link sources",
          {r[2] for r in s4} == {"ok", "failed"} and any("403" in (r[3] or "") for r in s4) and
          any(r[7] is not None for r in s4) and any(r[4] == "followed_link" for r in s4), str([(r[0], r[2], r[4]) for r in s4]))
    check("exactly the same requests reached the websites (no extra, none missing)", req_serial == req_par and
          len(req_par) == 18, f"{req_serial} vs {req_par}")  # 16 candidates + 1 redirect target + 1 followed link
    check("the weak-identity candidate was not requested", not any("/p/50" in r for r in req_par))
    check("content declared as a web page but starting with %PDF- is stored as a PDF (as before)",
          any(r[0].endswith("/pdf-as-html") and r[5] == "application/pdf" for r in s4), str([(r[0], r[5]) for r in s4]))
    logs = [r["message"] for r in db.q("SELECT message FROM job_log WHERE job_id=?", (ctx4.id,))]
    check("the run log says how long the reading step took", any(m.startswith("reading step:") and "up to 4 download" in m for m in logs), str(logs[-3:]))

    print("\n[2] Faster, and polite")
    check(f"4 at a time is clearly faster ({t_par:.1f} s vs {t_serial:.1f} s one at a time)", t_par < 0.6 * t_serial)
    check("never more than 4 downloads at once", 1 < LOG["peak"] <= 4, str(LOG["peak"]))
    check("never more than 2 downloads from one website at once", max(LOG["host_peak"].values()) <= 2, str(LOG["host_peak"]))

    print("\n[3] The reading limit holds")
    cl, ctxl, _, err = run(4, max_fetch=3, c=cands([f"{A}/p/{i}" for i in range(20, 30)]))
    n_rows = db.q1("SELECT COUNT(*) n FROM sources WHERE case_id=?", (cl,))["n"]
    check("exactly 3 pages stored at a limit of 3", n_rows == 3, str(n_rows))
    time.sleep(DELAY * 3)  # anything wrongly started would have arrived by now
    check("exactly 3 pages requested from the website — nothing beyond the limit", len(LOG["requests"]) == 3, str(LOG["requests"]))
    check("the limit is reported", isinstance(err, research.Budget) and any("fetch limit" in x for x in ctxl.state["limits_hit"]))
    check("the three highest-ranked pages were the ones read",
          [r["url"][-2:] for r in db.q("SELECT url FROM sources WHERE case_id=? ORDER BY id", (cl,))] == ["20", "21", "22"])

    print("\n[4] Cancel and time limit")
    cc = new_case()
    ctxc = new_ctx(cc)
    config.FETCH_PARALLEL = 4
    real_one = research._fetch_one
    seen = []

    def cancel_after_two(ctx, url, meta, download=None):
        r = real_one(ctx, url, meta, download)
        seen.append(url)
        if len(seen) == 2:
            db.update("jobs", ctx.id, {"cancel_requested": 1})
        return r
    research._fetch_one = cancel_after_two
    reset_log()
    try:
        research.fetch_candidates(ctxc, cands([f"{A}/p/{i}" for i in range(30, 40)]))
        cancelled = False
    except research.Cancelled:
        cancelled = True
    research._fetch_one = real_one
    time.sleep(DELAY * 3)
    n_rows = db.q1("SELECT COUNT(*) n FROM sources WHERE case_id=?", (cc,))["n"]
    check("Cancel stops the reading step", cancelled)
    check("only the pages read before Cancel are stored", n_rows == 2, str(n_rows))
    check("at most the downloads already started reached the website (2 read + up to 3 in flight)", len(LOG["requests"]) <= 5, str(len(LOG["requests"])))
    ct = new_case(time_limit_minutes=0.001)
    ctxt = new_ctx(ct)
    ctxt.state["started"] = time.time() - 60
    reset_log()
    try:
        research.fetch_candidates(ctxt, cands([f"{A}/p/{i}" for i in range(40, 44)]))
        stopped = False
    except research.Budget:
        stopped = True
    time.sleep(DELAY * 2)
    check("time limit: the step stops and nothing is requested or stored", stopped and not LOG["requests"] and
          db.q1("SELECT COUNT(*) n FROM sources WHERE case_id=?", (ct,))["n"] == 0, str(LOG["requests"]))

    print("\n[5] Failure states")
    dead = f"http://127.0.0.1:{port + 1 if port < 65000 else port - 1}/x"
    old_max = ingest.MAX_BYTES
    ingest.MAX_BYTES = 100_000
    cf, _, _, _ = run(4, c=cands([f"{A}/big/file", dead, f"{A}/forbidden/a", f"{A}/p/60"]))
    ingest.MAX_BYTES = old_max
    rows = {r["url"]: r for r in db.q("SELECT * FROM sources WHERE case_id=?", (cf,))}
    check("a file over the size cap is recorded as failed with the reason", rows[f"{A}/big/file"]["fetch_status"] == "failed" and
          "larger than" in rows[f"{A}/big/file"]["fetch_error"], str(dict(rows[f"{A}/big/file"]))[:200])
    check("a network error is recorded as failed with the reason", rows[dead]["fetch_status"] == "failed" and
          "network error" in rows[dead]["fetch_error"], rows[dead]["fetch_error"])
    check("an access-restricted page is recorded as failed, not bypassed", "403" in rows[f"{A}/forbidden/a"]["fetch_error"])
    check("a good page after three failures is still read", rows[f"{A}/p/60"]["fetch_status"] == "ok")
    parts = list(ingest.FILES.glob("dl-*.part"))
    check("no half-downloaded file is left behind", not parts, str(parts))
    good = Path(rows[f"{A}/p/60"]["file_path"]) if rows[f"{A}/p/60"].get("file_path") else None
    check("the stored file is the page as served", good is not None and good.read_bytes() == page(60), str(good))
    (ingest.FILES / "dl-deadbeef.part").write_bytes(b"cut off")
    keep = ingest.FILES / "keep.html"
    keep.write_bytes(b"kept")
    jobs.recover_interrupted()
    check("startup removes cut-off downloads and nothing else", not (ingest.FILES / "dl-deadbeef.part").exists() and keep.exists())

    print("\n[6] Crash marker (D-042) still names the source being read")
    cm = new_case()
    ctxm = new_ctx(cm)
    marks = []

    def spy(ctx, url, meta, download=None):
        on_disk = json.loads(db.q1("SELECT state_json FROM jobs WHERE id=?", (ctx.id,))["state_json"])
        marks.append((url, (on_disk.get("fetch_in_progress") or {}).get("url")))
        return real_one(ctx, url, meta, download)
    research._fetch_one = spy
    research.fetch_candidates(ctxm, cands([f"{A}/p/{i}" for i in range(70, 75)]))
    research._fetch_one = real_one
    check("before each source is read, that source is the one recorded on disk", len(marks) == 5 and all(a == b for a, b in marks), str(marks))
    check("the marker is cleared afterwards", "fetch_in_progress" not in json.loads(
        db.q1("SELECT state_json FROM jobs WHERE id=?", (ctxm.id,))["state_json"]))

    print("\n[7] WFD_FETCH_PARALLEL=1 is the earlier one-at-a-time behaviour")
    made = []
    real_pre = research.Prefetch

    class Spy(real_pre):
        def __init__(self, *a):
            made.append(a)
            super().__init__(*a)
    research.Prefetch = Spy
    run(1, c=cands([f"{A}/p/{i}" for i in range(80, 83)]))
    check("no download threads are created", not made and LOG["peak"] == 1, f"{made} peak {LOG['peak']}")
    run(4, c=cands([f"{A}/p/{i}" for i in range(83, 86)]))
    check("with 4, downloads run on the download threads", len(made) == 1 and made[0] == (4, config.FETCH_PER_HOST), str(made))
    research.Prefetch = real_pre
    check("the setting is bounded to 1–8 and bad values fall back to the default",
          config._int_env("WFD_NOPE", 4, 1, 8) == 4 and
          [(os.environ.__setitem__("WFD_T", v), config._int_env("WFD_T", 4, 1, 8))[1] for v in ("0", "99", "abc", "2")] == [1, 8, 4, 2])

    print("\n[8] Time per step")
    ctm = new_case()
    ctx = new_ctx(ctm)
    ctx.stage("search", 0.15)
    time.sleep(0.4)
    ctx.stage("fetch", 0.35)
    time.sleep(0.7)
    ctx.save(status="needs_input")
    paused_state = json.loads(db.q1("SELECT state_json FROM jobs WHERE id=?", (ctx.id,))["state_json"])
    saved = paused_state["timings"]
    check("time is recorded per step and saved with the job", 0.3 <= saved.get("search", 0) <= 0.7 and 0.6 <= saved.get("fetch", 0) <= 1.0, str(saved))
    time.sleep(0.6)  # the job waits for the researcher (or the server restarts) …
    ctx2 = research.Ctx(db.q1("SELECT * FROM jobs WHERE id=?", (ctx.id,)))  # … then resumes
    time.sleep(0.2)
    ctx2.stage("coding", 0.85)
    ctx2.save()
    t2 = ctx2.state["timings"]
    check("waiting time is not counted; the resumed step keeps adding up", 0.7 <= t2["fetch"] <= 1.2, str(t2))
    check("timing adds only the 'timings' entry to the job state", set(ctx2.state) == set(paused_state) and
          set(t2) == {"search", "fetch", "coding"}, f"{sorted(ctx2.state)} / {t2}")
    js = (ROOT / "web" / "app.js").read_text()
    check("the Progress page shows the time per step in Chinese and English",
          "timingLine(st)" in js and "本次运行各步骤用时" in js and "Time spent per step in this run" in js)
    check("the time line is display only (no request is sent from it)", "api(" not in js[js.index("function timingLine"):js.index("\n}\n", js.index("function timingLine"))])

    print("\n[9] In the browser: a real run through the job worker (search-only, TEST-FIXTURE search, default 4 downloads)")
    browser_part(A, B)

    srv.shutdown()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
