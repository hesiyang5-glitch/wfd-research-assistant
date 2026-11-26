"""Claude structured outputs (D-048). Run:  python -m tests.test_claude_structured

Offline: the real AnthropicClient with its HTTP endpoint replaced by scripted replies, a network guard, no paid call.
Checks the Claude schema form (no $ref, no per-batch passage enum, nothing optional, no union types), the request
(`output_config.format`, no beta header), the setting (on by default; off = the earlier JSON-in-text request and cache
identity), the pipeline (parse, case-insensitive enums, unknown passage ids rejected by the validator, invalid JSON /
refusal / cut-off never cached, schema-too-complex error), and that the analysis version, the user prompt and the GPT
side are unchanged.
"""
from __future__ import annotations

import copy
import json
import os
import re
import socket
import sys
import tempfile
import time
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="wfdcso_"))
os.environ["WFD_DATA_DIR"] = str(TMP / "data")
for k in ("TAVILY_API_KEY", "BRAVE_API_KEY", "OPENAI_API_KEY", "OPENAI_BASE_URL", "WFD_TEST_FIXTURE", "WFD_PASSWORD"):
    os.environ.pop(k, None)
FAKE_KEY = "sk-ant-test-0000"
os.environ["ANTHROPIC_API_KEY"] = FAKE_KEY
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
PX = re.compile(r"^\[(S\d+-P\d+)\] \(source[^\n]*\)\n", re.M)


class FakeResp:
    def __init__(self, status, payload=None, text=None):
        self.status_code = status
        self._p = payload
        self.text = text if text is not None else json.dumps(payload)
        self.headers = {"request-id": "req_test"}

    def json(self):
        return self._p


def main():
    from app import coding, db, research, server
    from app.config import DEFAULT_SETTINGS
    from app.llm import clients
    from app.llm.clients import LLMError
    from app.llm.structured import (build_batch_schema, normalize_structured, prop_key, schema_complexity,
                                    schema_hash)
    db.conn()
    server.bootstrap_schema()
    schema = coding.active_schema()
    F = {f["name"]: f for f in schema["fields"]}
    coded = [f for f in schema["fields"] if f.get("field_class") in ("sourced", "judgment") and not f.get("rule_missing")]
    big = sorted(coded, key=lambda f: -len(f.get("codes") or []))[:12]
    ids40 = [f"S{i}-P{j}" for i in range(1, 9) for j in range(1, 6)]

    print("\n[1] Schema forms")
    oa = build_batch_schema(big, ids40)
    oa_explicit = build_batch_schema(big, ids40, for_anthropic=False)
    an = build_batch_schema(big, ids40, for_anthropic=True)
    check("1 OpenAI form unchanged: $defs evidence with a per-batch passage-id enum; default == explicit",
          oa == oa_explicit and oa["$defs"]["evidence"]["properties"]["id"]["enum"] == ids40
          and schema_complexity(oa)["refs"] > 0)
    ca = schema_complexity(an)
    check("2 Claude form: no $ref / $defs, passage id is a plain string (no per-batch enum)",
          "$defs" not in an and ca["refs"] == 0 and '"S1-P1"' not in json.dumps(an)
          and an["properties"]["results"]["properties"][prop_key(0, big[0]["name"])]["properties"]["evidence"]["items"]
          ["properties"]["id"] == {"type": "string", "description": "A passage id from the EVIDENCE PASSAGES list, e.g. S12-P3."})

    def strip_ev(s):
        s = copy.deepcopy(s)
        s.pop("$defs", None)
        txt = json.dumps(s, sort_keys=True)
        txt = txt.replace(json.dumps({"$ref": "#/$defs/evidence"}, sort_keys=True), "EV")
        ev_inline = json.dumps(build_batch_schema(big[:1], ids40, for_anthropic=True)["properties"]["results"]["properties"]
                               [prop_key(0, big[0]["name"])]["properties"]["evidence"]["items"], sort_keys=True)
        return txt.replace(ev_inline, "EV")
    check("3 apart from the evidence object, both forms are identical (same variables, required keys, code enums)",
          strip_ev(oa) == strip_ev(an))
    check("4 worst-case batch (12 variables, most codes): 0 optional properties, 0 union types — far under Anthropic's "
          "documented limits (24 / 16)", ca["optional"] == 0 and ca["union"] == 0, str(ca))

    def all_closed(o):
        if isinstance(o, dict):
            if o.get("type") == "object" and (o.get("additionalProperties") is not False
                                              or set(o.get("required") or []) != set(o.get("properties") or {})):
                return False
            return all(all_closed(v) for v in o.values())
        if isinstance(o, list):
            return all(all_closed(v) for v in o)
        return True
    check("5 every object in the Claude form is closed (additionalProperties false) with every property required",
          all_closed(an))

    print("\n[2] Client and setting")
    c_on = clients.make_client("anthropic", "claude-sonnet-5-5", {})
    c_off = clients.make_client("anthropic", "claude-sonnet-5-5", {"claude_structured_output": False})
    check("6 on by default (setting claude_structured_output defaults to true)",
          DEFAULT_SETTINGS["claude_structured_output"] is True and c_on.supports_schema and c_on.structured)
    check("7 off → exactly the earlier client: no schema, generation settings {'api': 'messages'} (old cache identity)",
          not c_off.supports_schema and c_off.generation_settings() == {"api": "messages"}
          and c_on.generation_settings() == {"api": "messages", "output": "json_schema"})
    sent = []
    script = {"reply": None}

    def fake_post(url, json=None, headers=None, **kw):
        sent.append({"url": url, "json": json, "headers": headers or {}})
        r = script["reply"]
        return r(json) if callable(r) else r
    orig_post = clients.httpx.post
    clients.httpx.post = fake_post
    try:
        script["reply"] = FakeResp(200, {"id": "m", "stop_reason": "end_turn", "usage": {"input_tokens": 5, "output_tokens": 5},
                                         "content": [{"type": "text", "text": '{"results": {}}'}]})
        small = build_batch_schema([F["SYSTEM_LEVEL"]], ["S1-P1"], for_anthropic=True)
        c_on.complete("sys", "user", max_tokens=100, schema=small)
        b = sent[-1]
        check("8 structured request: output_config.format = {type: json_schema, schema}; no beta header; "
              "no thinking/temperature", b["json"].get("output_config") == {"format": {"type": "json_schema", "schema": small}}
              and not any(k.lower() == "anthropic-beta" for k in b["headers"])
              and set(b["json"]) == {"model", "max_tokens", "system", "messages", "output_config"})
        c_off.complete("sys", "user", max_tokens=100)
        check("9 setting off → request body exactly as before (no output_config)",
              set(sent[-1]["json"]) == {"model", "max_tokens", "system", "messages"})
        script["reply"] = FakeResp(400, text='{"type":"error","error":{"type":"invalid_request_error","message":"Schema is too complex for compilation."}}')
        try:
            c_on.complete("sys", "user", max_tokens=100, schema=small)
            e = None
        except LLMError as x:
            e = x
        check("10 'Schema is too complex' → clear message naming the setting; not billed, not a config error",
              e is not None and "too complex" in str(e) and "structured output" in str(e)
              and not e.possibly_billed and not e.config_error, str(e))
    finally:
        clients.httpx.post = orig_post

    print("\n[3] Through the coding pipeline")
    settings = {**DEFAULT_SETTINGS, "max_search_rounds": 0, "budget_usd": 50}

    def new_case(name):
        cid = db.insert("cases", {"name": name, "location": "Kerr County, Texas", "date_text": "July 4, 2025",
                                  "details": "", "known_links": "", "aliases": "", "schema_version_id": schema["id"],
                                  "status": "new", "identity_json": "{}", "settings_json": json.dumps(settings),
                                  "created_at": time.time(), "updated_at": time.time()})
        research.ingest_manual(cid, "text", {"title": "County statement", "text": TEXT * 3})
        return cid

    VARS = ["SYSTEM_LEVEL", "POPULATION_SCOPE"]

    def structured_reply(mutate=None, stop="end_turn", raw_text=None):
        def r(body):
            user = body["messages"][0]["content"]
            pid = PX.findall(user)[0]
            names = [l.split("### ")[1].split("  (")[0] for l in user.splitlines() if l.startswith("### ")]
            res = {}
            for i, n in enumerate(names):
                it = {"variable": n, "value": "3" if n == "SYSTEM_LEVEL" else "",
                      "evidence_status": "SUPPORTED" if n == "SYSTEM_LEVEL" else "INSUFFICIENT", "rule_unclear": False,
                      "evidence": [{"id": pid, "quote": Q, "stance": "supports"}] if n == "SYSTEM_LEVEL" else [],
                      "options": [], "alternatives": [], "missing_evidence": "" if n == "SYSTEM_LEVEL" else "not stated",
                      "rationale": "r", "unresolved": ""}
                if mutate:
                    it = mutate(n, it)
                res[prop_key(i, n)] = it
            text = raw_text if raw_text is not None else json.dumps({"results": res})
            return FakeResp(200, {"id": "msg", "stop_reason": stop, "usage": {"input_tokens": 900, "output_tokens": 400},
                                  "content": [{"type": "text", "text": text}]})
        return r

    def run(cid, reply, client=None):
        script["reply"] = reply
        sent.clear()
        clients.httpx.post = fake_post
        try:
            case = db.q1("SELECT * FROM cases WHERE id=?", (cid,))
            cl = client or clients.make_client("anthropic", "claude-sonnet-5-5", settings)
            coding.run_coding_plan(case, settings, [(cl, "independent")], None, lambda *a: None, None, VARS,
                                   mode="anthropic_only")
        finally:
            clients.httpx.post = orig_post
        sug = {r["variable"]: r for r in db.q("SELECT * FROM suggestions WHERE case_id=? AND provider='anthropic' "
                                               "ORDER BY id", (cid,))}
        calls = [r["status"] for r in db.q("SELECT status FROM model_calls WHERE case_id=? AND provider='anthropic' "
                                            "ORDER BY id", (cid,))]
        return sug, calls

    c1 = new_case("structured ok")
    sug, calls = run(c1, structured_reply())
    req = sent[0]["json"] if sent else {}
    check("11 structured reply parsed, validated and stored (SYSTEM_LEVEL 3, SUPPORTED, suggested)",
          sug.get("SYSTEM_LEVEL") and (sug["SYSTEM_LEVEL"]["value"], sug["SYSTEM_LEVEL"]["evidence_status"],
                                       sug["SYSTEM_LEVEL"]["status"]) == ("3", "SUPPORTED", "suggested")
          and calls and set(calls) == {"complete"}, f"{calls} {dict(sug.get('SYSTEM_LEVEL') or {}).get('status')}")
    check("12 the request carried the Claude schema form and the structured system prompt",
          "output_config" in req and "$defs" not in json.dumps(req["output_config"])
          and req.get("system") == coding.STRUCTURED_SYSTEM_PROMPT)
    oa_prompt_like = coding.make_prompt(db.q1("SELECT * FROM cases WHERE id=?", (c1,)),
                                        *coding.prepare(db.q1("SELECT * FROM cases WHERE id=?", (c1,)), settings, VARS)["batches"][0],
                                        coding.prepare(db.q1("SELECT * FROM cases WHERE id=?", (c1,)), settings, VARS)["pmap"],
                                        coding.prepare(db.q1("SELECT * FROM cases WHERE id=?", (c1,)), settings, VARS)["smeta"])
    check("13 the user prompt (case + evidence + variable rules) is the same one GPT receives",
          req["messages"][0]["content"] == oa_prompt_like)
    n_before = len(calls)
    sug2, calls2 = run(c1, structured_reply())
    check("14 same input again → cache hits only, no new paid call", set(calls2[n_before:]) == {"cache_hit"} and not sent,
          str(calls2))

    def lower_enums(n, it):
        it = {**it, "variable": n.lower(), "evidence_status": it["evidence_status"].lower()}
        it["evidence"] = [{**e, "stance": e["stance"].upper()} for e in it["evidence"]]
        return it
    c2 = new_case("lowercase enums")
    sug, calls = run(c2, structured_reply(lower_enums))
    check("15 enum capitalization is not guaranteed by Anthropic → accepted case-insensitively and stored canonically",
          sug.get("SYSTEM_LEVEL") and sug["SYSTEM_LEVEL"]["evidence_status"] == "SUPPORTED"
          and sug["SYSTEM_LEVEL"]["status"] == "suggested" and calls and set(calls) == {"complete"}, str(calls))

    def bad_pid(n, it):
        if n == "SYSTEM_LEVEL":
            it = {**it, "evidence": [{"id": "S999-P1", "quote": Q, "stance": "supports"}]}
        return it
    c3 = new_case("unknown passage id")
    sug, calls = run(c3, structured_reply(bad_pid))
    v = json.loads(sug["SYSTEM_LEVEL"]["validation_json"] or "{}") if sug.get("SYSTEM_LEVEL") else {}
    check("16 a passage id that was not sent (possible now that ids are not an enum) is rejected by the validator",
          sug.get("SYSTEM_LEVEL") and sug["SYSTEM_LEVEL"]["status"] == "validation_failed"
          and "S999-P1" in json.dumps(v), f"{dict(sug.get('SYSTEM_LEVEL') or {}).get('status')} {str(v)[:200]}")

    c4 = new_case("invalid json")
    sug, calls = run(c4, structured_reply(raw_text='{"results": {"v01_SYSTEM'))
    check("17 invalid JSON → recorded as invalid_json, nothing suggested, not cached",
          calls and set(calls) == {"invalid_json"} and not any(r["status"] == "suggested" for r in sug.values()), str(calls))
    n_before = len(calls)
    sug, calls = run(c4, structured_reply())
    check("17b …and the next run sends new requests (the bad replies were not cached)",
          set(calls[n_before:]) == {"complete"} and sent, str(calls))

    c5 = new_case("refusal")
    sug, calls = run(c5, structured_reply(stop="refusal", raw_text="I can't help with that."))
    check("18 stop_reason refusal → recorded as refusal, nothing suggested, not cached",
          calls and set(calls) == {"refusal"} and not any(r["status"] == "suggested" for r in sug.values()), str(calls))

    c6 = new_case("cut off")
    sug, calls = run(c6, structured_reply(stop="max_tokens", raw_text='{"results": {'))
    check("19 stop_reason max_tokens → recorded as incomplete, discarded, not cached",
          calls and set(calls) == {"incomplete"} and not any(r["status"] == "suggested" for r in sug.values()), str(calls))

    print("\n[4] Versions and the GPT side")
    a1 = coding.analysis_spec("cb", {**settings, "claude_structured_output": True})
    a2 = coding.analysis_spec("cb", {**settings, "claude_structured_output": False})
    check("20 analysis version is the same with the setting on or off (wire format is provider-specific, D-036) "
          "and the prompt version is unchanged", a1 == a2 and coding.PROMPT_VERSION == "wfd-prompt-2026-11-24")
    case = db.q1("SELECT * FROM cases WHERE id=?", (c1,))
    prep = coding.prepare(case, settings, VARS)
    fs0, ids0 = prep["batches"][0]
    prompt = coding.make_prompt(case, fs0, ids0, prep["pmap"], prep["smeta"])

    def key(c):
        return coding.cache_key(c, coding.system_prompt_for(c), prompt, fs0, ids0, prep["pmap"],
                                coding.response_schema_for(c, fs0, ids0), prep["codebook"])
    check("21 Claude's cache key differs between structured and JSON-text (replies are never mixed)",
          key(c_on) != key(c_off))

    class GPTLike:
        provider, model, supports_schema = "openai", "gpt-6.1-sol", True

        def generation_settings(self):
            return {"api": "responses", "reasoning_effort": "medium", "store": False}
    g = GPTLike()
    check("22 GPT side unchanged: its schema is the OpenAI form, identical to build_batch_schema's default",
          schema_hash(coding.response_schema_for(g, fs0, ids0)) == schema_hash(build_batch_schema(fs0, ids0)))
    e_on = coding.estimate(case, {**settings, "claude_structured_output": True}, VARS)
    e_off = coding.estimate(case, {**settings, "claude_structured_output": False}, VARS)
    check("23 the cost estimate counts the schema sent to Claude", e_on["input_tokens"] > e_off["input_tokens"],
          f"{e_on['input_tokens']} vs {e_off['input_tokens']}")

    class H:
        user = "t"
    out = server.api_put_settings(H(), {"claude_structured_output": False})
    out2 = server.api_put_settings(H(), {"claude_structured_output": True})
    check("24 Settings: the switch is saved as a true/false value", out["claude_structured_output"] is False
          and out2["claude_structured_output"] is True)
    norm = normalize_structured({"results": {prop_key(0, "SYSTEM_LEVEL"): {
        "variable": "SYSTEM_LEVEL", "value": "3", "evidence_status": "SUPPORTED", "evidence": [], "options": [],
        "alternatives": [], "missing_evidence": "", "rule_unclear": False, "rationale": "", "unresolved": ""}}},
        [F["SYSTEM_LEVEL"]])
    check("25 exact-case replies (OpenAI) normalize exactly as before", norm[0]["value"] == "3"
          and norm[0]["evidence_status"] == "SUPPORTED")
    check("26 the fake API key never appears in stored data",
          FAKE_KEY not in json.dumps([dict(r) for r in db.q("SELECT * FROM model_calls")])
          and FAKE_KEY not in json.dumps([dict(r) for r in db.q("SELECT * FROM suggestions")]))
    check("27 no live or paid API call was attempted", not NET, str(NET))
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED:", *FAIL, sep="\n  ")
        sys.exit(1)


if __name__ == "__main__":
    main()
