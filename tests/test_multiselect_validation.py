"""Multi-select validation (2026-10-06, benchmark regression). Run:  python -m tests.test_multiselect_validation

Offline: scripted Claude-style (JSON text) and OpenAI-style (strict structured) stand-ins, a network guard, no search.
Benchmark failure pattern: a multi-select value whose every selected code had valid per-option evidence, but no
redundant top-level evidence (or a JSON-list value), was rejected as a whole ("validation_failed").
"""
from __future__ import annotations

import io
import json
import os
import socket
import sys
import tempfile
import time
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="wfdms_"))
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


WEA_Q = "Wireless Emergency Alerts reached some phones"
LOCAL_Q = "the county's local CodeRED system was not activated"
TEXT = ("Hill Country flash flood, Kerr County, Texas, July 4, 2025. Wireless Emergency Alerts reached some phones in "
        "Kerr County. However, the county's local CodeRED system was not activated in time. ")


def main():
    from app import agreement, coding, db, export, research, server
    from app.config import DEFAULT_SETTINGS
    from app.llm.structured import build_batch_schema, normalize_structured, prop_key
    from app.validator import validate
    db.conn()
    server.bootstrap_schema()
    schema = coding.active_schema()
    F = {f["name"]: f for f in schema["fields"]}
    f_si = F["SYSTEM_INVOLVED"]
    P = {"S1-P1": {"text": TEXT, "source_id": 1}, "S1-P2": {"text": "Sirens were not part of the county plan.", "source_id": 1}}
    sup = lambda pid, q: {"id": pid, "quote": q, "stance": "supports"}
    opt = lambda c, *ev: {"code": c, "evidence": list(ev)}

    print("\n[1] Validator: per-selection validation")
    v = validate(f_si, {"value": "WEA, LOCAL", "evidence": [], "options": [opt("WEA", sup("S1-P1", WEA_Q)),
                                                                            opt("LOCAL", sup("S1-P1", LOCAL_Q))]}, P)
    check("1 BENCHMARK: valid per-option evidence and NO top-level evidence → valid, both codes kept",
          v["ok"] and v["outcome"] == "valid" and v["value"] == "WEA, LOCAL" and not v["errors"]
          and {e["id"] for e in v["evidence"]} == {"S1-P1"}, str(v)[:300])
    v = validate(f_si, {"value": ["WEA", "LOCAL"], "evidence": [], "options": [opt("WEA", sup("S1-P1", WEA_Q)),
                                                                                opt("LOCAL", sup("S1-P1", LOCAL_Q))]}, P)
    check("2 BENCHMARK: value given as a JSON list (allowed by the Claude prompt) is accepted",
          v["outcome"] == "valid" and v["value"] == "WEA, LOCAL", str(v["errors"]))
    v = validate(f_si, {"value": "WEA, LOCAL", "evidence": [], "options": [
        opt("WEA", sup("S1-P1", WEA_Q)), opt("LOCAL", sup("S1-P1", "sirens sounded everywhere in town"))]}, P)
    sel = {s["code"]: s for s in v["selections"]}
    check("3 supported + unsupported (fake quote) → partially valid; supported code kept, rejected one reported",
          v["ok"] and v["outcome"] == "partially_valid" and v["value"] == "WEA"
          and sel["LOCAL"]["outcome"] == "rejected" and "quote_not_found" in sel["LOCAL"]["reasons"]
          and "quote_not_found" in v["reason_codes"], str(v)[:300])
    v = validate(f_si, {"value": "WEA, XYZ", "evidence": [], "options": [opt("WEA", sup("S1-P1", WEA_Q)),
                                                                          opt("XYZ", sup("S1-P1", LOCAL_Q))]}, P)
    check("4 invalid code still rejected (reason invalid_code); the supported code is kept",
          v["outcome"] == "partially_valid" and v["value"] == "WEA" and "invalid_code" in v["reason_codes"]
          and {s["code"]: s["outcome"] for s in v["selections"]}["XYZ"] == "rejected")
    v = validate(f_si, {"value": "XYZ", "evidence": [sup("S1-P1", WEA_Q)], "options": [opt("XYZ", sup("S1-P1", WEA_Q))]}, P)
    check("4b only an invalid code → invalid (validation_failed), nothing kept",
          not v["ok"] and v["outcome"] == "invalid" and v["value"] == "" and "invalid_code" in v["reason_codes"])
    v = validate(f_si, {"value": "WEA, LOCAL", "evidence": [], "options": [
        opt("WEA", sup("S1-P1", WEA_Q)), opt("LOCAL", sup("S9-P9", LOCAL_Q))]}, P)
    check("5 evidence id not supplied → that selection rejected (evidence_id_not_supplied)",
          v["outcome"] == "partially_valid" and "evidence_id_not_supplied" in v["reason_codes"] and v["value"] == "WEA")
    v = validate(f_si, {"value": "WEA, LOCAL", "evidence": [], "options": [
        opt("WEA", sup("S1-P1", WEA_Q)), opt("LOCAL", {"id": "S1-P1", "quote": LOCAL_Q, "stance": "contradicts"})]}, P)
    check("6 valid citation not marked as supporting → evidence_does_not_support_selection",
          v["outcome"] == "partially_valid" and "evidence_does_not_support_selection" in v["reason_codes"])
    v = validate(f_si, {"value": "", "evidence": [], "options": [opt("WEA", sup("S1-P1", WEA_Q))]}, P)
    check("7 blank value but codes in options → malformed_output (never 'insufficient evidence')",
          not v["ok"] and v["reason_codes"] == ["malformed_output"])
    v = validate(f_si, {"value": "WEA", "evidence": "not a list", "options": []}, P)
    check("7b evidence not a list → malformed_output", not v["ok"] and v["reason_codes"] == ["malformed_output"])
    v = validate(f_si, {"value": "WEA, LOCAL", "evidence": [], "options": {"WEA": []}}, P)
    check("7c options not a list → malformed_output", not v["ok"] and v["reason_codes"] == ["malformed_output"])
    v = validate(f_si, {"value": "WEA", "evidence": [sup("S1-P1", WEA_Q)], "options": []}, P)
    check("8 one selected code with top-level evidence (no option entry) → valid as before", v["outcome"] == "valid")
    v = validate(f_si, {"value": "WEA, LOCAL", "evidence": [sup("S1-P1", "made up quotation text")],
                        "options": [opt("WEA", sup("S1-P1", WEA_Q)), opt("LOCAL", sup("S1-P1", LOCAL_Q))]}, P)
    check("9 a fabricated top-level citation is rejected and reported → partially valid (codes kept, human review)",
          v["outcome"] == "partially_valid" and v["value"] == "WEA, LOCAL" and v["rejected_citations"]
          and "quote_not_found" in v["reason_codes"])
    f_sl = F["SYSTEM_LEVEL"]
    v = validate(f_sl, {"value": "3", "evidence": [], "options": [opt("3", sup("S1-P1", WEA_Q))]}, P)
    check("10 single-select rules unchanged: top-level supporting evidence still required",
          not v["ok"] and "no_supporting_evidence" in v["reason_codes"])
    v = validate(f_sl, {"value": "3, 2", "evidence": [sup("S1-P1", WEA_Q)], "options": []}, P)
    check("10b several codes for a single-select variable → invalid", not v["ok"] and "single_select_multiple_codes" in v["reason_codes"])

    print("\n[2] Through the coding pipeline (Claude-style JSON text and OpenAI-style structured output)")
    settings = {**DEFAULT_SETTINGS, "max_search_rounds": 0, "budget_usd": 50, "openai_budget_usd": 50}
    cid = db.insert("cases", {"name": "Hill Country flash flood", "location": "Kerr County, Texas", "date_text": "July 4, 2025",
                              "details": "", "known_links": "", "aliases": "", "schema_version_id": schema["id"],
                              "status": "new", "identity_json": "{}", "settings_json": json.dumps(settings),
                              "created_at": time.time(), "updated_at": time.time()})
    research.ingest_manual(cid, "text", {"title": "County statement", "text": TEXT * 4})
    import re
    PX = re.compile(r"^\[(S\d+-P\d+)\] \(source[^\n]*\)\n", re.M)

    class ClaudeLike:
        provider, model, supports_schema = "anthropic", "claude-sonnet-5-5", False
        n = 0

        def generation_settings(self):
            return {"stand_in": "claude"}

        def complete(self, system, user, max_tokens=4000):
            ClaudeLike.n += 1
            pid = PX.findall(user)[0]
            names = [l.split("### ")[1].split("  (")[0] for l in user.splitlines() if l.startswith("### ")]
            res = []
            for n in names:
                if n == "SYSTEM_INVOLVED":  # the benchmark shape: list value, per-option evidence, empty top-level
                    res.append({"variable": n, "value": ["WEA", "LOCAL"], "status": "suggested", "evidence": [],
                                "options": [opt("WEA", sup(pid, WEA_Q)), opt("LOCAL", sup(pid, LOCAL_Q))],
                                "rationale": "both channels named", "unresolved": ""})
                else:
                    res.append({"variable": n, "value": "", "status": "insufficient_evidence", "evidence": []})
            return {"text": json.dumps({"results": res}), "input_tokens": 900, "output_tokens": 150, "stop_reason": "end_turn"}

    class OpenAILike:
        provider, model, supports_schema = "openai", "gpt-6.1-sol", True
        n = 0

        def generation_settings(self):
            return {"stand_in": "openai"}

        def complete(self, system, user, max_tokens=4000, schema=None):
            OpenAILike.n += 1
            pid = PX.findall(user)[0]
            names = [l.split("### ")[1].split("  (")[0] for l in user.splitlines() if l.startswith("### ")]
            out = {}
            for i, n in enumerate(names):
                if n == "SYSTEM_INVOLVED":  # WEA supported, SIREN with a fabricated quote
                    out[prop_key(i, n)] = {"variable": n, "value": ["WEA", "SIREN"], "status": "suggested", "evidence": [],
                                           "options": [opt("WEA", sup(pid, WEA_Q)),
                                                       opt("SIREN", sup(pid, "sirens wailed across the valley"))],
                                           "rationale": "r", "unresolved": ""}
                else:
                    out[prop_key(i, n)] = {"variable": n, "value": [] if F[n].get("multi") and F[n]["type"] == "categorical" else "",
                                           "status": "insufficient_evidence", "evidence": [], "options": [],
                                           "rationale": "", "unresolved": ""}
            return {"text": json.dumps({"results": out}), "input_tokens": 900, "output_tokens": 150, "stop_reason": "completed"}

    VARS = ["SYSTEM_INVOLVED", "SYSTEM_LEVEL"]
    case = db.q1("SELECT * FROM cases WHERE id=?", (cid,))
    coding.run_coding_plan(case, settings, [(ClaudeLike(), "independent"), (OpenAILike(), "independent")], None,
                           lambda *a: None, None, VARS, mode="dual_independent")
    row = lambda prov: db.q1("SELECT * FROM suggestions WHERE case_id=? AND variable='SYSTEM_INVOLVED' AND provider=? "
                             "ORDER BY id DESC", (cid, prov))
    a, b = row("anthropic"), row("openai")
    va, vb = json.loads(a["validation_json"]), json.loads(b["validation_json"])
    check("11 Claude path: benchmark-shaped reply stored as suggested 'WEA, LOCAL' (not validation_failed)",
          a["status"] == "suggested" and a["value"] == "WEA, LOCAL" and va["outcome"] == "valid", f"{a['status']} {a['value']}")
    check("12 OpenAI structured path: mixed reply stored as partially_valid with WEA kept, SIREN rejected",
          b["status"] == "partially_valid" and b["value"] == "WEA"
          and [s["code"] for s in vb["selections"] if s["outcome"] == "rejected"] == ["SIREN"], f"{b['status']} {b['value']}")
    check("13 machine-readable reasons and the raw provider response are stored",
          vb["reason_codes"] and "quote_not_found" in vb["reason_codes"] and json.loads(b["raw_json"]).get("options"))
    calls = {r["provider"]: r["status"] for r in db.q("SELECT provider, status FROM model_calls WHERE case_id=?", (cid,))}
    check("14 a reply with a rejected selection is NOT cached (D-025); a fully valid one is",
          calls.get("openai") == "complete_with_invalid_items" and calls.get("anthropic") == "complete", str(calls))
    ag = agreement.case_assessments(cid)["SYSTEM_INVOLVED"]
    check("15 partially valid results are never bulk-eligible", not ag["eligible"], str(ag)[:200])
    rows = {r["name"]: r for r in export.case_results(cid)["rows"]}
    check("16 partially valid result is shown with its own state and routed to review",
          rows["SYSTEM_INVOLVED"]["cells"]["openai"]["state"] == "partially_valid"
          and rows["SYSTEM_INVOLVED"]["category"] in ("pending", "disputed"))
    v_un = export.export_value(rows["SYSTEM_INVOLVED"], include_unreviewed=True)
    check("17 a partially valid value is never exported as an unreviewed value", v_un[0] == "", str(v_un))
    server.api_review(type("H", (), {"user": "coder1"})(), str(cid), {"variable": "SYSTEM_LEVEL", "action": "edit",
                                                                       "value": "3", "reason": "AAR"})
    coding.run_coding_plan(case, settings, [(ClaudeLike(), "independent"), (OpenAILike(), "independent")], None,
                           lambda *a: None, None, VARS, mode="dual_independent")
    check("18 Human final unchanged by re-analysis", db.q1("SELECT value, action FROM reviews WHERE case_id=? AND "
                                                         "variable='SYSTEM_LEVEL'", (cid,)) == {"value": "3", "action": "edited"})
    res = normalize_structured({"results": {prop_key(0, "SYSTEM_INVOLVED"): {
        "variable": "SYSTEM_INVOLVED", "value": ["WEA", "LOCAL"], "status": "suggested", "evidence": [],
        "options": [opt("WEA", sup("S1-P1", WEA_Q)), opt("LOCAL", sup("S1-P1", LOCAL_Q))], "rationale": "", "unresolved": ""}}},
        [f_si])
    check("19 OpenAI normalization + validator: per-option evidence without top-level → valid",
          validate(f_si, res[0], P)["outcome"] == "valid")
    check("20 no live or paid API call was attempted", not NET, str(NET))
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED:", *FAIL, sep="\n  ")
        sys.exit(1)


if __name__ == "__main__":
    main()
