"""Public-mode (login) tests. Run:  python -m tests.test_auth"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS " if cond else "  FAIL ") + name + (f"  — {detail}" if detail and not cond else ""))


def start(env_extra, port):
    tmp = tempfile.mkdtemp(prefix="wfdauth_")
    env = {**os.environ, "WFD_DATA_DIR": tmp, "WFD_PORT": str(port), **env_extra}
    for k in ("ANTHROPIC_API_KEY", "TAVILY_API_KEY", "BRAVE_API_KEY", "WFD_TEST_FIXTURE"):
        env.pop(k, None)
    return subprocess.Popen([sys.executable, "-m", "app.server"], cwd=str(ROOT), env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def main():
    print("\n[1] Refuses to listen publicly without a password")
    p = start({"WFD_HOST": "0.0.0.0", "WFD_PASSWORD": ""}, 8811)
    try:
        code = p.wait(timeout=15)
    except subprocess.TimeoutExpired:
        p.kill()
        code = None
    check("server exits instead of running unprotected", code == 2, f"exit={code}")

    print("\n[2] Login required")
    srv = start({"WFD_HOST": "0.0.0.0", "WFD_PASSWORD": "correct horse battery staple", "WFD_TRUST_PROXY": "1"}, 8812)
    time.sleep(2.5)
    B = "http://127.0.0.1:8812"
    try:
        r = httpx.get(B + "/healthz")
        check("health check is public", r.status_code == 200)
        check("security headers present", r.headers.get("x-frame-options") == "DENY" and "frame-ancestors 'none'" in r.headers.get("content-security-policy", ""))
        check("API blocked when logged out", httpx.get(B + "/api/status").status_code == 401)
        check("export blocked when logged out", httpx.get(B + "/api/cases/1/export?format=tsv").status_code == 401)
        check("login page (static files) still loads", httpx.get(B + "/").status_code == 200)
        me = httpx.get(B + "/api/me").json()
        check("/api/me reports login required", me == {"user": None, "login_required": True}, str(me))
        t0 = time.time()
        r = httpx.post(B + "/api/login", json={"name": "Siyang", "password": "wrong"}, headers={"CF-Connecting-IP": "9.9.9.1"})
        check("wrong password rejected and slowed down", r.status_code == 401 and time.time() - t0 >= 0.45)
        r = httpx.post(B + "/api/login", json={"name": "", "password": "correct horse battery staple"}, headers={"CF-Connecting-IP": "9.9.9.2"})
        check("name required", r.status_code == 401 and "name" in r.json()["error"].lower())
        r = httpx.post(B + "/api/login", json={"name": "Siyang", "password": "correct horse battery staple"}, headers={"CF-Connecting-IP": "9.9.9.2"})
        ck = r.headers.get("set-cookie", "")
        check("login sets HttpOnly SameSite cookie", r.status_code == 200 and "HttpOnly" in ck and "SameSite=Lax" in ck, ck)
        c = httpx.Client(base_url=B, cookies=r.cookies)
        check("API works after login", c.get("/api/status").status_code == 200)
        check("non-JSON POST rejected (CSRF guard)", c.post("/api/cases", content="name=x", headers={"Content-Type": "application/x-www-form-urlencoded"}).status_code == 415)
        cid = c.post("/api/cases", json={"name": "Test incident", "location": "Denver, CO", "date_text": "2026", "start": False}).json()["id"]
        c.post(f"/api/cases/{cid}/sources", json={"kind": "text", "title": "note", "text": "Denver issued an alert on 2026-01-17. " * 20})
        r = c.post(f"/api/cases/{cid}/review", json={"variable": "COUNTRY", "action": "edit", "value": "United States", "reason": "test"})
        h = c.get(f"/api/cases/{cid}/history?variable=COUNTRY").json()
        check("review history records the reviewer's name", r.status_code == 200 and h["reviews"][-1]["reviewer"] == "Siyang", str(h["reviews"][-1:]))
        src = c.get(f"/api/cases/{cid}/sources").json()[0]
        check("added sources record who added them", src["added_by"] == "Siyang")
        tok = c.cookies.get("wfd_session")
        bad = tok[:-4] + ("0000" if not tok.endswith("0000") else "1111")
        check("tampered session rejected", httpx.get(B + "/api/status", cookies={"wfd_session": bad}).status_code == 401)
        c.post("/api/logout", json={})
        check("logout clears session", httpx.post(B + "/api/logout", json={}).headers.get("set-cookie", "").find("Max-Age=0") >= 0)
        for i in range(8):
            httpx.post(B + "/api/login", json={"name": "x", "password": f"guess{i}"},
                       headers={"CF-Connecting-IP": "7.7.7.7", "X-Forwarded-For": f"1.2.3.{i}"}, timeout=10)
        r = httpx.post(B + "/api/login", json={"name": "x", "password": "correct horse battery staple"},
                       headers={"CF-Connecting-IP": "7.7.7.7", "X-Forwarded-For": "5.5.5.5"})
        check("lockout after repeated failures (even with right password)", r.status_code == 401 and "Too many" in r.json()["error"])
        check("faking X-Forwarded-For does not get around the lockout", "Too many" in r.json()["error"])

        print("\n[3] Browser login flow")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            b = pw.chromium.launch()
            pg = b.new_page()
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(B + "/#/cases")
            pg.wait_for_selector("#loginForm", timeout=8000)
            check("browser shows login screen", True)
            pg.fill("#lgName", "Siyang")
            pg.fill("#lgPw", "correct horse battery staple")
            pg.click("#loginForm button")
            pg.wait_for_timeout(1500)
            check("after login the case list shows", "Test incident" in pg.inner_text("#app"))
            check("header shows reviewer name", "Siyang" in pg.inner_text("#userBox"))
            check("no page errors (CSP allows the app)", not errs, str(errs))
            b.close()

        print("\n[4] Site-wide backstop when addresses are faked")
        r0 = httpx.post(B + "/api/login", json={"name": "Elise", "password": "correct horse battery staple"},
                        headers={"CF-Connecting-IP": "8.8.8.8"})
        c2 = httpx.Client(base_url=B, cookies=r0.cookies)
        import concurrent.futures as cf
        def bad(i):
            return httpx.post(B + "/api/login", json={"name": "x", "password": "nope"},
                              headers={"CF-Connecting-IP": f"10.0.{i // 250}.{i % 250}"}, timeout=20).status_code
        with cf.ThreadPoolExecutor(10) as ex:
            list(ex.map(bad, range(40)))
        r = httpx.post(B + "/api/login", json={"name": "Siyang", "password": "correct horse battery staple"},
                       headers={"CF-Connecting-IP": "8.8.4.4"})
        check("40 failures from many addresses pause sign-in for everyone", r.status_code == 401 and "paused" in r.json()["error"])
        check("people already signed in keep working during the pause", c2.get("/api/status").status_code == 200)
    finally:
        srv.terminate()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
