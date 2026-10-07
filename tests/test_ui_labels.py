"""Interface terminology (label-only change, 2026-10-06). Run:  python -m tests.test_ui_labels

Offline. Starts a local server with FAKE keys (outbound requests are routed to a closed local port, so no external call
can be made) and renders the pages in Chromium. It checks the new provider / API / model labels everywhere they appear
and that nothing behind them changed: request payloads, settings keys and values, cost numbers, the cache key, the
database schema, the prompt, stored results and Human final values. Pinned fingerprints were computed on `main` at
302a2f2 before the change.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="wfdlbl_"))
os.environ["WFD_DATA_DIR"] = str(TMP / "data")
for k in ("ANTHROPIC_API_KEY", "TAVILY_API_KEY", "BRAVE_API_KEY", "OPENAI_API_KEY", "OPENAI_BASE_URL", "WFD_TEST_FIXTURE",
          "OPENAI_MODEL", "WFD_PASSWORD"):
    os.environ.pop(k, None)
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
PASS, FAIL, NET = [], [], []
_real = socket.socket.connect


def _guard(self, addr):
    host = addr[0] if isinstance(addr, tuple) else str(addr)
    if host not in ("127.0.0.1", "localhost", "::1"):
        NET.append(host)
        raise OSError("network blocked in tests")
    return _real(self, addr)


socket.socket.connect = _guard

# fingerprints computed on main (302a2f2) with the same synthetic input — must be identical after a label-only change
PIN_SCHEMA = "5f231bf5a2af2aad"
PIN_CACHE = {"anthropic": "llm3:ae6ef713619ca7f24bc8bce280acc137c03bf96af88d1493f2a1d3c6b142ad26",
             "openai": "llm3:a82924c4abee492d7d602a6e1ee0445e5a366ca28a047738eda49e597e2c84ab"}
PIN_PROMPT = "64a04116c132078f"
NEUTRAL = "Neither provider is labeled as primary or secondary."


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS " if cond else "  FAIL ") + name + (f"  — {detail}" if detail and not cond else ""))


def no_hierarchy(text: str) -> bool:
    t = text.replace(NEUTRAL, "")
    return not re.search(r"\b(primary|secondary|backup|main model|reviewer)\b", t, re.I) and \
        not any(w in t for w in ("主模型", "次要模型", "备用模型", "复核模型"))


def main():
    from app import coding, db, export, research, server
    from app.llm.structured import build_batch_schema
    db.conn()
    server.bootstrap_schema()
    schema = coding.active_schema()
    F = {f["name"]: f for f in schema["fields"]}

    print("\n[1] Behaviour fingerprints (unchanged)")
    sql = sorted(r["sql"] or "" for r in db.q("SELECT sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"))
    check("13/14 database schema identical to main", hashlib.sha256("\n".join(sql).encode()).hexdigest()[:16] == PIN_SCHEMA)

    class C:
        def __init__(s, p, m):
            s.provider, s.model = p, m

        def generation_settings(s):
            return {"x": 1}
    fs = [F["SYSTEM_LEVEL"], F["SYSTEM_INVOLVED"]]
    pmap = {"S1-P1": {"text": "Kerr County did not send an alert.", "source_id": 1, "page": 1, "para": 1}}
    keys = {p: coding.cache_key(C(p, m), coding.SYSTEM_PROMPT, "PROMPT", fs, ["S1-P1"], pmap,
                                build_batch_schema(fs, ["S1-P1"]) if p == "openai" else None, "1:label")
            for p, m in (("anthropic", "claude-sonnet-5-5"), ("openai", "gpt-6.1-sol"))}
    check("13 cache keys identical to main for both providers", keys == PIN_CACHE, str(keys))
    check("13b system prompt identical to main", hashlib.sha256(coding.SYSTEM_PROMPT.encode()).hexdigest()[:16] == PIN_PROMPT)
    check("13c prompt/export provider labels unchanged (part of historical prompts and exports)",
          coding.PROVIDER_LABELS == {"anthropic": "Claude (Anthropic)", "openai": "OpenAI",
                                     "openai_compatible": "OpenAI-compatible server"})

    print("\n[2] Seed a case with results and a Human final value")
    st = {**server.global_settings()}
    cid = db.insert("cases", {"name": "Hill Country flash flood", "location": "Kerr County, Texas", "date_text": "July 4, 2025",
                              "details": "", "known_links": "", "aliases": "", "schema_version_id": schema["id"],
                              "status": "done", "identity_json": "{}", "settings_json": json.dumps(st),
                              "created_at": time.time(), "updated_at": time.time()})
    research.ingest_manual(cid, "text", {"title": "County statement", "text": "Kerr County officials did not send a "
                                         "CodeRED alert to residents along the Guadalupe River. " * 20})
    db.insert("jobs", {"case_id": cid, "kind": "research", "stage": "review", "status": "done", "progress": 1,
                       "message": "Ready for human review", "params_json": "{}", "state_json": "{}",
                       "created_at": time.time(), "updated_at": time.time()})
    for prov, model, val in (("anthropic", "claude-sonnet-5-5", "3"), ("openai", "gpt-6.1-sol", "3")):
        db.insert("suggestions", {"case_id": cid, "run_id": None, "variable": "SYSTEM_LEVEL", "value": val,
                                  "status": "suggested", "rationale": "r", "evidence_json": "[]", "counter_json": "[]",
                                  "unresolved": "", "validation_json": "{}", "raw_json": "{}", "basis": "model",
                                  "provider": prov, "model": model, "role": "independent", "interpretation": "independent",
                                  "created_at": time.time()})
    server.api_review(type("H", (), {"user": "coder1"})(), str(cid), {"variable": "SYSTEM_LEVEL", "action": "edit",
                                                                       "value": "2", "reason": "AAR"})
    snap = lambda: (db.q("SELECT * FROM suggestions ORDER BY id"), db.q("SELECT * FROM reviews ORDER BY variable"))
    before = snap()
    prov_labels = sorted(m["provider_label"] for m in {r["name"]: r for r in export.case_results(cid)["rows"]}
                         ["SYSTEM_LEVEL"]["providers"])

    print("\n[3] Rendered interface")
    port = 18950 + os.getpid() % 40
    env = {k: v for k, v in os.environ.items()}
    env.update({"WFD_PORT": str(port), "ANTHROPIC_API_KEY": "test-not-a-real-key", "OPENAI_API_KEY": "test-not-a-real-key",
                "TAVILY_API_KEY": "test-not-a-real-key"})
    for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
        env[k] = "http://127.0.0.1:9"  # the test server cannot reach any external service
    env["NO_PROXY"] = env["no_proxy"] = "127.0.0.1,localhost"
    srv = subprocess.Popen([sys.executable, "-m", "app.server"], cwd=str(ROOT), env=env, stdout=subprocess.DEVNULL,
                           stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{port}"
    for _ in range(80):
        try:
            urllib.request.urlopen(base + "/healthz", timeout=1)
            break
        except Exception:
            time.sleep(0.25)
    status = json.loads(urllib.request.urlopen(base + "/api/status").read())
    claude_model, openai_model = status["settings"]["model_name"], status["providers"]["openai"]["model"]
    T, posted = {}, []
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as pw:
            br = pw.chromium.launch()
            pg = br.new_page(viewport={"width": 1400, "height": 1100})
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.route("**/api/providers/check", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(
                {"mode": "x", "providers": {"anthropic": {"ok": True, "verified": True, "reason": ""},
                                            "openai": {"ok": True, "verified": True, "reason": ""}}})))
            def capture(meth):  # record the payload and abort: nothing is created, saved or sent to a model
                def handler(r):
                    if r.request.method == meth:
                        posted.append((r.request.url, r.request.post_data))
                        r.abort()
                    else:
                        r.continue_()
                return handler
            for pat, meth in (("**/api/cases", "POST"), ("**/api/settings", "PUT"), (f"**/api/cases/{cid}/recode", "POST")):
                pg.route(pat, capture(meth))
            for lang in ("en", "zh"):
                pg.goto(base + "/")
                pg.evaluate(f"localStorage.setItem('wfd_lang','{lang}')")
                pg.reload()
                pg.wait_for_selector("#providerChoice", timeout=10000)
                pg.wait_for_timeout(600)
                T[f"{lang}_services"] = pg.locator(".services").locator("xpath=..").inner_text()
                T[f"{lang}_choice"] = pg.inner_text("#providerChoice")
                for m in ("anthropic_only", "dual_independent"):
                    pg.check(f"input[name=pmode][value={m}]")
                    pg.wait_for_timeout(700)
                    T[f"{lang}_est_{m}"] = pg.inner_text("#estBox")
                    if lang == "en":
                        e = json.loads(urllib.request.urlopen(f"{base}/api/estimate_preview?mode={m}").read())
                        money = [pg.evaluate(f"money({x})") for x in [e["combined_high"]] +
                                 [v for p in e["providers"] if p["selected"] for v in (p["cost_low"], p["cost_high"])]]
                        T[f"money_{m}"] = all(x in T[f"{lang}_est_{m}"] for x in money)
                T[f"{lang}_home"] = pg.inner_text("#app")
                if lang == "en":
                    pg.fill("#f_name", "Label test")
                    pg.click("#startBtn")
                    pg.wait_for_selector("#csOk", timeout=8000)
                    T["en_confirm"] = pg.inner_text("#modalRoot")
                    pg.click("#csOk")
                    pg.wait_for_timeout(1000)
                pg.goto(base + "/#/settings")
                pg.wait_for_timeout(1300)
                T[f"{lang}_settings"] = pg.inner_text("#app")
                if lang == "en":
                    pg.click("#saveSet")
                    pg.wait_for_timeout(800)
                pg.goto(f"{base}/#/case/{cid}/progress")
                pg.wait_for_timeout(1500)
                pg.click("#recodeBtn")
                pg.wait_for_selector("#modeSel", timeout=10000)
                opts = pg.eval_on_selector_all("#modeSel option", "els => els.map(e => [e.value, e.textContent])")
                T[f"{lang}_recode_options"] = opts
                for m in ("anthropic_only", "openai_only", "dual_independent"):
                    pg.select_option("#modeSel", m)
                    pg.wait_for_timeout(700)
                    T[f"{lang}_recode_{m}"] = pg.inner_text("#modalRoot")
                if lang == "en":
                    pg.click("#dlgOk")
                    pg.wait_for_timeout(1000)
                pg.goto(f"{base}/#/case/{cid}/progress")
                pg.wait_for_timeout(1000)
                # the per-variable Re-analyze dialog (not awaited: the promise resolves only when the dialog closes)
                pg.evaluate(f"() => {{ startRecode({cid}, ['SYSTEM_LEVEL']); }}")
                pg.wait_for_selector("#modeSel", timeout=10000)
                pg.select_option("#modeSel", "dual_independent")
                pg.wait_for_timeout(700)
                T[f"{lang}_recode_one"] = pg.inner_text("#modalRoot")
                pg.evaluate("document.getElementById('modalRoot').innerHTML=''")
                pg.goto(f"{base}/#/case/{cid}/review")
                pg.wait_for_timeout(1500)
                pg.click("text=SYSTEM_LEVEL")
                pg.wait_for_timeout(800)
                T[f"{lang}_review"] = pg.inner_text("#app")
            T["errors"] = errs
            br.close()
    finally:
        srv.terminate()
        srv.wait(10)

    en = lambda k: T[k]
    s = en("en_services")
    check("1 Services: Web search — Tavily Search API", "Web search — Tavily Search API" in s, s[:300])
    check("1b Services: Claude coding — Anthropic API, with model and status",
          "Claude coding — Anthropic API" in s and f"Model: {claude_model}" in s and "Status: configured" in s)
    check("1c Services: OpenAI coding — OpenAI API, with model", "OpenAI coding — OpenAI API" in s and f"Model: {openai_model}" in s)
    check("1d Services: internal processing (Tesseract OCR, LSA + BM25) and abbreviations expanded",
          "Scanned-document text recognition — Tesseract OCR" in s and "Evidence retrieval — LSA + BM25" in s
          and "API = Application Programming Interface" in s and "BM25 = Best Matching 25 ranking algorithm" in s
          and "OCR = Optical Character Recognition" in s and "LSA = Latent Semantic Analysis" in s, s)
    check("1e Services: groups External services / AI coding providers / Internal processing; no 'Language model'",
          all(x in s for x in ("External services", "AI coding providers", "Internal processing")) and "Language model" not in s)
    check("1f Services (中文): Claude 编码 — Anthropic API", "Claude 编码 — Anthropic API" in T["zh_services"])
    st_txt = en("en_settings")
    labels = ["Search service", "Configured model provider", "Configured model", "Maximum search rounds",
              "Maximum search queries", "Pages per search query", "Results per search query", "Maximum pages to retrieve",
              "Research time limit", "Research budget limit", "Evidence passages per variable",
              "Evidence passages per model request", "Coding-provider selection", "Model-request limit per case",
              "OpenAI coding budget per case", "OpenAI request limit per case", "OpenAI reasoning effort",
              "OpenAI reasoning-token allowance"]
    check("2 Settings: every readable label is shown", all(x in st_txt for x in labels), str([x for x in labels if x not in st_txt]))
    raw = ["search_provider", "model_provider", "max_passages_per_call", "openai_reasoning_reserve_tokens", "coding_mode",
           "max_model_attempts_per_case", "budget_usd"]
    check("2b Settings: raw setting keys are no longer shown as labels", not [x for x in raw if x in st_txt],
          str([x for x in raw if x in st_txt]))
    check("2c Settings: Claude model identified as a Claude model (Anthropic API)",
          "Claude model identifier used with the Anthropic API" in st_txt)
    ch = en("en_choice")
    check("3 Research page: three choices with standardized names",
          all(x in ch for x in ("Claude only — Anthropic API", "OpenAI only — OpenAI API",
                                "Claude + OpenAI — independent comparison")), ch)
    check("3b Research page: model identifiers shown for each choice",
          f"Model: {claude_model}" in ch and f"Model: {openai_model}" in ch and f"Claude: Anthropic API · {claude_model}" in ch
          and f"OpenAI: OpenAI API · {openai_model}" in ch)
    check("3c Research page: explanatory copy",
          "One shared research process, followed by coding with Claude." in ch
          and "One shared research process, followed by coding with OpenAI." in ch
          and "Both providers independently analyze the same available evidence. Requests may be processed sequentially "
              "to protect server responsiveness." in ch)
    e1, e2 = en("en_est_anthropic_only"), en("en_est_dual_independent")
    check("4 Cost estimate: standardized names",
          "Shared web research — Tavily Search API" in e2 and f"Claude coding — Anthropic API · {claude_model}" in e2
          and f"OpenAI coding — OpenAI API · {openai_model}" in e2 and "Expected cost" in e2 and "Maximum estimated cost" in e2, e2)
    check("4b Cost estimate: unselected provider shows 'Not selected — $0.00'", "Not selected — $0.00" in e1, e1)
    check("12 Cost estimate: the numbers shown are exactly the backend's numbers (same money formatting)",
          T.get("money_anthropic_only") is True and T.get("money_dual_independent") is True)
    for k in ("en_recode_dual_independent", "en_recode_one"):
        r = en(k)
        check(f"5 Re-analyze ({'whole case' if k.endswith('dual_independent') else 'one variable'}): labels, models, "
              f"neutral sentence, cached/new requests",
              "Claude coding — Anthropic API" in r and "OpenAI coding — OpenAI API" in r and f"Claude model: {claude_model}" in r
              and f"OpenAI model: {openai_model}" in r and NEUTRAL in r and "Cached requests" in r and "New paid requests" in r, r[:400])
    opts = dict(T["en_recode_options"])
    check("5b Re-analyze: options show the standardized names; submitted values unchanged",
          opts == {"anthropic_only": "Claude only — Anthropic API", "openai_only": "OpenAI only — OpenAI API",
                   "dual_independent": "Claude + OpenAI — independent comparison"}, str(opts))
    check("5c Re-analyze (中文) options", dict(T["zh_recode_options"]).get("anthropic_only") == "仅 Claude — Anthropic API")
    rv = en("en_review")
    check("6/7 Review: Claude suggestion with Anthropic API; OpenAI suggestion with OpenAI API",
          "Claude suggestion" in rv and "Anthropic API" in rv and "OpenAI suggestion" in rv and "OpenAI API" in rv)
    every = json.dumps(T, ensure_ascii=False)
    check("8 'ChatGPT' appears nowhere in the interface or its source",
          "ChatGPT" not in every and "ChatGPT" not in (ROOT / "web" / "app.js").read_text()
          and "ChatGPT" not in (ROOT / "web" / "i18n.js").read_text())
    check("6/7b the old mixed label 'Claude (Anthropic)' is gone from the interface",
          "Claude (Anthropic)" not in every and "Claude (Anthropic)" not in (ROOT / "web" / "app.js").read_text())
    bad = [k for k, v in T.items() if isinstance(v, str) and not no_hierarchy(v)]
    check("9 no primary / secondary / backup / reviewer labels in the affected interfaces", not bad,
          str({k: re.findall(r".{0,40}(?:primary|secondary|backup|main model|reviewer|主模型|次要模型|备用模型|复核模型).{0,40}",
                             T[k].replace(NEUTRAL, ""), re.I) for k in bad}))
    bodies = {u.split("/api/")[1]: json.loads(b) for u, b in posted}
    check("10 provider selection submitted unchanged (new case: mode 'dual_independent')",
          bodies.get("cases", {}).get("mode") == "dual_independent")
    check("10b Re-analyze submits the unchanged payload", bodies.get(f"cases/{cid}/recode") ==
          {"variables": None, "mode": "dual_independent"}, str(bodies.get(f"cases/{cid}/recode")))
    sent = bodies.get("settings", {})
    expect = {k: status["settings"][k] for k in sent}
    check("11 settings save: same keys and values as the stored settings (display labels only)",
          set(sent) >= {"search_provider", "model_provider", "model_name", "coding_mode", "budget_usd",
                        "openai_reasoning_effort", "follow_links", "require_approval_over_budget"}
          and sent == expect, str({k: (sent[k], expect[k]) for k in sent if sent[k] != expect[k]}))
    check("16 stored model results and Human final values unchanged by the interface", snap() == before)
    check("15b every submit was intercepted: no case, job, model call or settings change was created",
          db.q1("SELECT COUNT(*) n FROM cases")["n"] == 1 and db.q1("SELECT COUNT(*) n FROM jobs")["n"] == 1
          and db.q1("SELECT COUNT(*) n FROM model_calls")["n"] == 0)
    check("16b Human final shown in the review table", "Human final" in rv)
    check("16c export provider labels unchanged", prov_labels == ["Claude (Anthropic)", "OpenAI"], str(prov_labels))
    check("no JavaScript errors", not T["errors"], str(T["errors"]))
    check("no network access from the test process", not NET, str(NET))
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED:", *FAIL, sep="\n  ")
        sys.exit(1)


if __name__ == "__main__":
    main()
