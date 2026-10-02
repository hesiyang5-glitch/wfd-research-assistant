"""Cost-safety tests. Run:  python -m tests.test_costs

Everything here is offline: the Anthropic HTTP endpoint is replaced with scripted responses and the model with a
scripted fake client, so these tests check the app's budget and retry rules, not real billing or model quality.
"""
from __future__ import annotations

import glob
import json
import os
import sys
import tempfile
import time
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="wfdcost_"))
os.environ["WFD_DATA_DIR"] = str(TMP / "data")
for k in ("ANTHROPIC_API_KEY", "TAVILY_API_KEY", "BRAVE_API_KEY", "OPENAI_API_KEY", "OPENAI_BASE_URL", "WFD_TEST_FIXTURE"):
    os.environ.pop(k, None)
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
UP = os.environ.get("WFD_TEST_PDFS") or (glob.glob("/root/.claude/uploads/*/") or [""])[0]

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS " if cond else "  FAIL ") + name + (f"  — {detail}" if detail and not cond else ""))


class FakeResp:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._p = payload or {}
        self.text = json.dumps(self._p)

    def json(self):
        return self._p


def ok_payload():
    return {"content": [{"type": "text", "text": '{"results": []}'}], "usage": {"input_tokens": 10, "output_tokens": 5},
            "stop_reason": "end_turn"}


def main():
    import httpx

    from app import coding, db, jobs, research
    from app.config import DEFAULT_SETTINGS
    from app.llm import clients
    from app.server import api_resume, bootstrap_schema

    clients.time.sleep = lambda *_: None  # no waiting during retry tests

    print("\n[1] Retries only when the request certainly was not processed")

    def run_client(script):
        calls = []

        def fake_post(*a, **k):
            calls.append(1)
            step = script[min(len(calls) - 1, len(script) - 1)]
            if isinstance(step, Exception):
                raise step
            return step
        orig = clients.httpx.post
        clients.httpx.post = fake_post
        try:
            out = clients.AnthropicClient("claude-sonnet-5-5", "test-key").complete("s", "u", max_tokens=100)
            return out, None, len(calls)
        except clients.LLMError as e:
            return None, e, len(calls)
        finally:
            clients.httpx.post = orig

    out, err, n = run_client([FakeResp(429, {"error": "rate"}), FakeResp(200, ok_payload())])
    check("429 (rejected before processing) is retried", out is not None and n == 2, f"n={n} err={err}")
    out, err, n = run_client([FakeResp(529, {"error": "overloaded"}), FakeResp(200, ok_payload())])
    check("529 overloaded is retried", out is not None and n == 2)
    out, err, n = run_client([httpx.ConnectError("refused"), FakeResp(200, ok_payload())])
    check("connection failure (never sent) is retried", out is not None and n == 2)
    out, err, n = run_client([httpx.ReadTimeout("slow"), FakeResp(200, ok_payload())])
    check("read timeout is NOT retried and is marked possibly billed", err is not None and err.possibly_billed and n == 1, f"n={n}")
    out, err, n = run_client([FakeResp(500, {"error": "internal"}), FakeResp(200, ok_payload())])
    check("server error is NOT retried and is marked possibly billed", err is not None and err.possibly_billed and n == 1)
    out, err, n = run_client([FakeResp(400, {"error": "bad request"})])
    check("client error is not retried and not counted as billed", err is not None and not err.possibly_billed and n == 1)
    sent = {}

    def capture(*a, **k):
        sent.update(k.get("json") or {})
        return FakeResp(200, ok_payload())
    orig = clients.httpx.post
    clients.httpx.post = capture
    clients.AnthropicClient("claude-sonnet-5-5", "test-key").complete("s", "u", max_tokens=100)
    clients.httpx.post = orig
    check("Anthropic request no longer sends `temperature` (rejected by current models)",
          "temperature" not in sent and sent.get("model") == "claude-sonnet-5-5", str(sorted(sent)))

    print("\n[2] Coding loop: worst-case budget check, failed-call accounting, safe caching")
    db.conn()
    bootstrap_schema()
    schema = coding.active_schema()
    settings = {**DEFAULT_SETTINGS, "max_search_rounds": 0}
    cid = db.insert("cases", {"name": "Hill Country flash flood", "location": "Kerr County, Texas", "date_text": "July 4, 2025",
                              "details": "", "known_links": "", "aliases": "", "schema_version_id": schema["id"],
                              "status": "new", "identity_json": "{}", "settings_json": json.dumps(settings),
                              "created_at": time.time(), "updated_at": time.time()})
    pdf = (glob.glob(os.path.join(UP, "*DID_WARNINGS*")) or [None])[0]
    if pdf:
        research.ingest_manual(cid, "file", {"filename": "report.pdf", "path": pdf, "title": "Did warnings fail victims?"})
    else:
        research.ingest_manual(cid, "text", {"title": "note", "text": ("Kerr County did not send CodeRED alerts during the "
                                                                       "July 4, 2025 Hill Country flash flood. " * 40)})
    case = db.q1("SELECT * FROM cases WHERE id=?", (cid,))

    class Fake:
        provider, model = "fake", "claude-sonnet-5-5"

        def __init__(self, mode):
            self.mode, self.n = mode, 0

        def complete(self, system, user, max_tokens=4000):
            self.n += 1
            if self.mode == "billed_fail":
                raise clients.LLMError("read timeout", possibly_billed=True)
            names = [l.split("### ")[1].split("  (")[0] for l in user.splitlines() if l.startswith("### ")]
            body = json.dumps({"results": [{"variable": x, "value": "", "status": "insufficient_evidence", "evidence": []}
                                           for x in names]})
            if self.mode == "truncated":
                return {"text": body[: len(body) // 2], "input_tokens": 1000, "output_tokens": max_tokens, "stop_reason": "max_tokens"}
            return {"text": body, "input_tokens": 1000, "output_tokens": 300, "stop_reason": "end_turn"}

    log = lambda *a: None
    f1 = Fake("truncated")
    coding.run_coding(case, settings, f1, None, log, 10.0, ["SYSTEM_LEVEL"])
    coding.run_coding(case, settings, f1, None, log, 10.0, ["SYSTEM_LEVEL"])
    check("truncated reply is not cached (re-analysis calls the model again)", f1.n == 2, f"calls={f1.n}")
    st = db.q1("SELECT status, rationale FROM suggestions WHERE case_id=? AND variable='SYSTEM_LEVEL' ORDER BY id DESC", (cid,))
    check("truncated reply is reported, not silently used", st["status"] == "model_error" and "cut off" in st["rationale"])

    f2 = Fake("good")
    coding.run_coding(case, settings, f2, None, log, 10.0, ["COUNTRY"])
    coding.run_coding(case, settings, f2, None, log, 10.0, ["COUNTRY"])
    check("complete reply is cached (identical re-analysis makes no new call)", f2.n == 1, f"calls={f2.n}")

    # Output allowance: the first live run was cut off at 450 tokens/variable (9 of 16 batches).
    check("output allowance is at least 1,200 tokens per variable plus a base",
          coding.batch_max_tokens(3) >= 3 * 1200 + 1000 and coding.batch_max_tokens(1) >= 2200,
          f"3 vars → {coding.batch_max_tokens(3)}")
    model_fields = [f for f in schema["fields"] if f.get("field_class") in coding.MODEL_CLASSES and not f.get("rule_missing")]
    big = {**settings, "max_passages_per_call": 100000}  # only the variable cap can split batches here
    bts, _, _, _ = coding.build_batches(cid, model_fields, big)
    most = max(len(fs) for fs, _ in bts)
    check("no call codes more than 12 variables", most <= coding.MAX_VARS_PER_CALL == 12, f"largest batch {most}")
    check("largest batch's allowance stays under the 16,000-token ceiling (never silently clipped)",
          coding.OUT_BASE_TOKENS + coding.OUT_TOKENS_PER_VAR * most <= coding.MAX_OUT_TOKENS,
          str(coding.batch_max_tokens(most)))
    check("every model variable is still placed in some batch",
          sum(len(fs) for fs, _ in bts) == len(model_fields), f"{sum(len(fs) for fs, _ in bts)} of {len(model_fields)}")

    before = coding.case_spent(cid)
    f3 = Fake("billed_fail")
    rep = coding.run_coding(case, settings, f3, None, log, 10.0, ["CITY_OR_TOWN"])
    row = db.q1("SELECT * FROM usage WHERE case_id=? ORDER BY id DESC", (cid,))
    check("possibly-billed failure is counted at worst case", f3.n == 1 and row["estimated"] == 1 and row["cost_usd"] > 0
          and coding.case_spent(cid) > before, str(row))

    class Rejecting(Fake):
        def complete(self, system, user, max_tokens=4000):
            self.n += 1
            raise clients.LLMError('HTTP 400: {"error":{"message":"`temperature` is deprecated for this model."}}')
    f5 = Rejecting("x")
    rep5 = coding.run_coding(case, settings, f5, None, log, 10.0, None)
    n_batches = rep5["failed_calls"]
    check("same provider error twice in a row stops the run (no 16 identical failures)", f5.n == 2,
          f"calls={f5.n}")
    skipped = db.q1("SELECT COUNT(*) n FROM suggestions WHERE run_id=? AND rationale LIKE 'Not sent:%'", (rep5["run_id"],))["n"]
    check("variables not sent are marked with the reason", skipped > 0)

    f4 = Fake("good")
    rep = coding.run_coding(case, settings, f4, None, log, 0.001, ["STATE_OR_TERRITORY", "COUNTY_OR_PARISH"])
    check("call is skipped when its worst case exceeds the remaining budget", f4.n == 0 and rep["not_coded_budget"],
          str(rep["not_coded_budget"]))

    print("\n[3] Budget is per case across runs; approval raises it to a set amount")
    import app.llm.clients as cl
    orig_get = cl.get_client
    fake = Fake("good")
    cl.get_client = lambda provider, model: fake
    check("default case budget is $5 (D-034)", DEFAULT_SETTINGS["budget_usd"] == 5.0, str(DEFAULT_SETTINGS["budget_usd"]))
    check("OpenAI sub-budget stays $3 (unchanged by D-034)", DEFAULT_SETTINGS["openai_budget_usd"] == 3.0)
    check("raised default is still a finite number, not unlimited",
          isinstance(DEFAULT_SETTINGS["budget_usd"], float) and 0 < DEFAULT_SETTINGS["budget_usd"] < 100)
    # Simulate earlier runs of this case having spent almost the whole default budget.
    pre = DEFAULT_SETTINGS["budget_usd"] - 0.05
    db.insert("usage", {"case_id": cid, "job_id": 999, "kind": "model", "provider": "fake", "model": "claude-sonnet-5-5",
                        "input_tokens": 0, "output_tokens": 0, "units": 1, "cost_usd": pre - coding.case_spent(cid),
                        "estimated": 0, "at": time.time(), "note": "earlier run"})
    jid = jobs.enqueue(cid, "recode", {})
    research.run_research(db.q1("SELECT * FROM jobs WHERE id=?", (jid,)))
    j = db.q1("SELECT * FROM jobs WHERE id=?", (jid,))
    stj = json.loads(j["state_json"])
    check("a new run sees what earlier runs of the case spent", j["status"] == "needs_input" and stj.get("awaiting") == "budget"
          and abs(stj["budget"]["spent_usd"] - pre) < 0.01, f"{j['status']} {stj.get('budget')}")
    check("no model call is made while waiting for approval", fake.n == 0)

    class H:
        user = "tester"
    api_resume(H(), str(jid), {"approve_over_budget": True})
    new_budget = json.loads(db.q1("SELECT settings_json FROM cases WHERE id=?", (cid,))["settings_json"])["budget_usd"]
    expected = round(pre + stj["estimate"]["cost_high"], 2)
    check("approval sets the budget to spent + worst-case estimate (a number, not unlimited)",
          abs(new_budget - expected) <= 0.011 and new_budget < 100, f"new={new_budget} expected≈{expected}")
    logged = db.q1("SELECT message FROM job_log WHERE job_id=? AND message LIKE '%budget changed%'", (jid,))
    check("budget change is logged with who approved it", logged and "tester" in logged["message"])
    research.run_research(db.q1("SELECT * FROM jobs WHERE id=?", (jid,)))
    j = db.q1("SELECT * FROM jobs WHERE id=?", (jid,))
    check("run completes after approval", j["status"] == "done", j["message"])
    check("total case spend stays within the approved budget", coding.case_spent(cid) <= new_budget + 1e-9,
          f"{coding.case_spent(cid)} > {new_budget}")

    print("\n[4] Unknown model price pauses instead of running uncapped")

    class Local(Fake):
        provider, model = "openai", "local-llama"
    cl.get_client = lambda provider, model: Local("good")
    jid2 = jobs.enqueue(cid, "recode", {})
    research.run_research(db.q1("SELECT * FROM jobs WHERE id=?", (jid2,)))
    j2 = db.q1("SELECT * FROM jobs WHERE id=?", (jid2,))
    check("model without a price → paused, asks for the price", j2["status"] == "needs_input"
          and json.loads(j2["state_json"]).get("awaiting") == "price", j2["message"])
    cl.get_client = orig_get
    db.ex("UPDATE jobs SET status='cancelled' WHERE id=?", (jid2,))

    print("\n[5] Search spending is counted and capped by the case budget")
    data = TMP / "data"
    pricing = json.loads((ROOT / "config" / "pricing.json").read_text())
    check("Tavily price is pre-filled ($0.016 per advanced request)",
          pricing["search"]["tavily"]["usd_per_1000_queries"] == 16.0)
    pricing["search"]["TEST-FIXTURE"] = {"usd_per_1000_queries": 16.0}
    (data / "pricing.json").write_text(json.dumps(pricing))
    fx = TMP / "fx.json"
    fx.write_text(json.dumps({"results": []}))
    os.environ["WFD_TEST_FIXTURE"] = str(fx)
    s2 = {**DEFAULT_SETTINGS, "budget_usd": 0.05, "model_provider": "none", "max_search_rounds": 1}
    cid2 = db.insert("cases", {"name": "Test flood", "location": "Somewhere, TX", "date_text": "2025", "details": "",
                               "known_links": "", "aliases": "", "schema_version_id": schema["id"], "status": "new",
                               "identity_json": "{}", "settings_json": json.dumps(s2), "created_at": time.time(),
                               "updated_at": time.time()})
    jid3 = jobs.enqueue(cid2, "research", {"identity_confirmed": True})
    research.run_research(db.q1("SELECT * FROM jobs WHERE id=?", (jid3,)))
    billed = db.q("SELECT cost_usd FROM usage WHERE case_id=? AND kind='search'", (cid2,))
    j3 = json.loads(db.q1("SELECT state_json FROM jobs WHERE id=?", (jid3,))["state_json"])
    check("each search is recorded at $0.016", billed and all(abs(b["cost_usd"] - 0.016) < 1e-9 for b in billed))
    check("searches stop before exceeding a $0.05 case budget (3 × $0.016)", len(billed) == 3, f"{len(billed)} searches")
    check("stopping is reported as a limit, not as 'no information exists'",
          any("case cost budget" in x for x in j3.get("limits_hit", [])), str(j3.get("limits_hit")))
    os.environ.pop("WFD_TEST_FIXTURE", None)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
