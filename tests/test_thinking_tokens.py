"""Claude thinking tokens are recorded (D-046). Run:  python -m tests.test_thinking_tokens

Offline: the Anthropic HTTP endpoint is replaced with scripted replies (the real AnthropicClient is used), a network
guard blocks everything else, no paid call. Checks that `usage.output_tokens_details.thinking_tokens` is read into the
existing `reasoning_tokens` columns of `model_calls` and `usage`, that a missing breakdown is stored as unknown (NULL,
never 0), and that nothing model-visible or billed changes: same request body, same cost, same cache key.
"""
from __future__ import annotations

import json
import os
import re
import socket
import sys
import tempfile
import time
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="wfdthink_"))
os.environ["WFD_DATA_DIR"] = str(TMP / "data")
for k in ("ANTHROPIC_API_KEY", "TAVILY_API_KEY", "BRAVE_API_KEY", "OPENAI_API_KEY", "OPENAI_BASE_URL", "WFD_TEST_FIXTURE"):
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


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS " if cond else "  FAIL ") + name + (f"  — {detail}" if detail and not cond else ""))


Q = "Kerr County officials did not send a CodeRED alert to residents"
TEXT = f"Hill Country flash flood, Kerr County, Texas, July 4, 2025. {Q} along the Guadalupe River. "


class FakeResp:
    def __init__(self, status, payload):
        self.status_code = status
        self._p = payload
        self.text = json.dumps(payload)
        self.headers = {"request-id": "req_test"}

    def json(self):
        return self._p


def main():
    from app import coding, db, research, server
    from app.config import DEFAULT_SETTINGS
    from app.llm import clients

    db.conn()
    server.bootstrap_schema()
    schema = coding.active_schema()

    print("\n[1] Reading the breakdown (unit level)")
    f = clients.anthropic_thinking_tokens
    check("1 thinking_tokens is read from usage.output_tokens_details",
          f({"output_tokens": 900, "output_tokens_details": {"thinking_tokens": 612}}) == 612)
    check("2 no breakdown reported → None (unknown), never 0", f({"output_tokens": 900}) is None)
    check("3 a reported 0 stays 0 (Claude chose not to think)", f({"output_tokens_details": {"thinking_tokens": 0}}) == 0)
    check("4 malformed values are ignored (None), never guessed",
          f({"output_tokens_details": {"thinking_tokens": "612"}}) is None
          and f({"output_tokens_details": {"thinking_tokens": -1}}) is None
          and f({"output_tokens_details": {"thinking_tokens": True}}) is None
          and f({"output_tokens_details": None}) is None and f(None) is None)

    print("\n[2] AnthropicClient.complete returns it; the request itself does not change")
    sent = []

    def payload(thinking):
        usage = {"input_tokens": 900, "output_tokens": 1000}
        if thinking is not None:
            usage["output_tokens_details"] = {"thinking_tokens": thinking}
        return {"id": "msg_test", "stop_reason": "end_turn", "usage": usage,
                "content": [{"type": "thinking", "thinking": "private reasoning text"},
                            {"type": "text", "text": '{"results": []}'}]}

    script = {"thinking": 700}

    def fake_post(*a, **k):
        sent.append(k.get("json") or {})
        return FakeResp(200, payload(script["thinking"]))
    orig = clients.httpx.post
    clients.httpx.post = fake_post
    try:
        c = clients.AnthropicClient("claude-sonnet-5-5", "test-key")
        out = c.complete("system", "user", max_tokens=100)
        check("5 reasoning_tokens returned with output_tokens unchanged",
              out["reasoning_tokens"] == 700 and out["output_tokens"] == 1000, str(out))
        check("6 the thinking text is not returned or kept (only visible text)",
              out["text"] == '{"results": []}' and "private reasoning" not in json.dumps(out))
        check("7 request body unchanged: no `thinking`, `output_config` or `temperature` parameter is sent",
              set(sent[-1]) == {"model", "max_tokens", "system", "messages"}, str(sorted(sent[-1])))
        script["thinking"] = None
        out = c.complete("system", "user", max_tokens=100)
        check("8 reply without the breakdown → reasoning_tokens None", out["reasoning_tokens"] is None)
    finally:
        clients.httpx.post = orig

    print("\n[3] Through the coding pipeline: stored in model_calls and usage; cost and cache key unchanged")
    settings = {**DEFAULT_SETTINGS, "max_search_rounds": 0, "budget_usd": 50}
    cid = db.insert("cases", {"name": "Hill Country flash flood", "location": "Kerr County, Texas", "date_text": "July 4, 2025",
                              "details": "", "known_links": "", "aliases": "", "schema_version_id": schema["id"],
                              "status": "new", "identity_json": "{}", "settings_json": json.dumps(settings),
                              "created_at": time.time(), "updated_at": time.time()})
    research.ingest_manual(cid, "text", {"title": "County statement", "text": TEXT * 3})
    PX = re.compile(r"^\[(S\d+-P\d+)\] \(source[^\n]*\)\n", re.M)
    script["thinking"] = 1234

    def coding_post(*a, **k):
        body = k.get("json") or {}
        user = body["messages"][0]["content"]
        pid = PX.findall(user)[0]
        names = [l.split("### ")[1].split("  (")[0] for l in user.splitlines() if l.startswith("### ")]
        items = [{"variable": n, "value": "3" if n == "SYSTEM_LEVEL" else "", "evidence_status":
                  "SUPPORTED" if n == "SYSTEM_LEVEL" else "INSUFFICIENT",
                  "evidence": [{"id": pid, "quote": Q, "stance": "supports"}] if n == "SYSTEM_LEVEL" else [],
                  "options": [], "alternatives": [], "missing_evidence": "" if n == "SYSTEM_LEVEL" else "not stated",
                  "rule_unclear": False, "rationale": "r", "unresolved": ""} for n in names]
        usage = {"input_tokens": 900, "output_tokens": 2000}
        if script["thinking"] is not None:
            usage["output_tokens_details"] = {"thinking_tokens": script["thinking"]}
        return FakeResp(200, {"id": "msg_x", "stop_reason": "end_turn", "usage": usage,
                              "content": [{"type": "text", "text": json.dumps({"results": items})}]})

    clients.httpx.post = coding_post
    try:
        case = db.q1("SELECT * FROM cases WHERE id=?", (cid,))
        client = clients.AnthropicClient("claude-sonnet-5-5", "test-key")
        coding.run_coding_plan(case, settings, [(client, "independent")], None, lambda *a: None, None,
                               ["SYSTEM_LEVEL", "POPULATION_SCOPE"], mode="anthropic_only")
        mc = db.q("SELECT * FROM model_calls WHERE case_id=? AND provider='anthropic' AND status!='cache_hit'", (cid,))
        us = db.q("SELECT * FROM usage WHERE case_id=? AND kind='model'", (cid,))
        check("9 model_calls.reasoning_tokens holds Claude's thinking tokens",
              mc and all(r["reasoning_tokens"] == 1234 for r in mc), str([(r["status"], r["reasoning_tokens"]) for r in mc]))
        check("10 usage.reasoning_tokens holds them too (same column OpenAI already uses)",
              us and all(r["reasoning_tokens"] == 1234 for r in us), str([r["reasoning_tokens"] for r in us]))
        expect = clients.cost_usd("claude-sonnet-5-5", 900, 2000)
        check("11 cost is still input + output_tokens only (thinking is inside output_tokens, not added again)",
              us and all(abs((r["cost_usd"] or 0) - expect) < 1e-9 for r in us), f"{[r['cost_usd'] for r in us]} vs {expect}")
        sug = db.q1("SELECT * FROM suggestions WHERE case_id=? AND variable='SYSTEM_LEVEL' AND provider='anthropic'", (cid,))
        check("12 coding result unaffected (SYSTEM_LEVEL 3, SUPPORTED, suggested)",
              sug and (sug["value"], sug["evidence_status"], sug["status"]) == ("3", "SUPPORTED", "suggested"))

        # same model-visible input again → served from cache (the change must not alter cache identity)
        n_before = len(db.q("SELECT id FROM model_calls WHERE case_id=? AND status!='cache_hit'", (cid,)))
        coding.run_coding_plan(case, settings, [(client, "independent")], None, lambda *a: None, None,
                               ["SYSTEM_LEVEL", "POPULATION_SCOPE"], mode="anthropic_only")
        n_after = len(db.q("SELECT id FROM model_calls WHERE case_id=? AND status!='cache_hit'", (cid,)))
        hits = db.q("SELECT id FROM model_calls WHERE case_id=? AND status='cache_hit'", (cid,))
        check("13 re-analysis of the same input is a cache hit (cache identity unchanged, no new paid call)",
              n_after == n_before and hits, f"{n_before}->{n_after}, hits={len(hits)}")
        check("14 generation settings (part of the cache key) carry no thinking-related field",
              not any("think" in str(k).lower() for k in (client.generation_settings() or {})))
    finally:
        clients.httpx.post = orig

    check("15 no live or paid API call was attempted", not NET, str(NET))
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
