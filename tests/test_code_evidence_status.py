"""Per-code evidence status for multi-select variables (D-047). Run:  python -m tests.test_code_evidence_status

Offline: scripted Claude-style (JSON text) and OpenAI-style (strict structured) stand-ins, a network guard, a local
server + headless browser for the Review table, no search, no paid call. Scenario modelled on the Palisade Fires
POPULATION_RESPONSE_OBSERVED case (2026-11-24): both models choose codes 1, 4, 5, but one of them marks code 1 as an
inference. Agreement on the code set must not hide that.
"""
from __future__ import annotations

import io
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

TMP = Path(tempfile.mkdtemp(prefix="wfdces_"))
os.environ["WFD_DATA_DIR"] = str(TMP / "data")
for k in ("ANTHROPIC_API_KEY", "TAVILY_API_KEY", "BRAVE_API_KEY", "OPENAI_API_KEY", "OPENAI_BASE_URL", "WFD_TEST_FIXTURE",
          "WFD_PASSWORD"):
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


VAR = "POPULATION_RESPONSE_OBSERVED"  # multi-select, codes 1-6
Q1 = "the public did not effectively understand the potential impact of the warning"
Q4 = "residents without charged devices missed critical evacuation updates"
Q5 = "residents complained that evacuation directions were unclear"
TEXT = (f"Palisades wildfire, Los Angeles, January 2025. Based on community input, {Q1}. Some {Q4}. "
        f"At community sessions {Q5}. ")


def sup(pid, q):
    return {"id": pid, "quote": q, "stance": "supports"}


def item(pid, var_status, code_statuses, structured):
    """A reply for VAR selecting 1, 4, 5. code_statuses: dict code -> status, or None to omit per-code statuses."""
    qs = {"1": Q1, "4": Q4, "5": Q5}
    opts = []
    for c in ("1", "4", "5"):
        o = {"code": c, "evidence": [sup(pid, qs[c])]}
        if code_statuses is not None:
            o["evidence_status"] = code_statuses[c]
        opts.append(o)
    return {"variable": VAR, "value": ["1", "4", "5"] if structured else "1, 4, 5", "evidence_status": var_status,
            "evidence": [], "options": opts, "alternatives": [], "missing_evidence": "", "rule_unclear": False,
            "rationale": "codes justified separately", "unresolved": ""}


def main():
    from app import agreement, coding, db, export, research, server
    from app import evidence_status as es_mod
    from app.config import DEFAULT_SETTINGS
    from app.llm.structured import (RESPONSE_SCHEMA_VERSION, SchemaViolation, build_batch_schema, normalize_structured,
                                    prop_key)
    from app.validator import validate
    db.conn()
    server.bootstrap_schema()
    schema = coding.active_schema()
    F = {f["name"]: f for f in schema["fields"]}
    f = F[VAR]
    P = {"S1-P1": {"text": TEXT, "source_id": 1}}
    ALL_SUP = {"1": "SUPPORTED", "4": "SUPPORTED", "5": "SUPPORTED"}
    ONE_INF = {"1": "INFERRED", "4": "SUPPORTED", "5": "SUPPORTED"}

    def res(it):
        v = validate(f, it, P)
        return v, es_mod.resolve(f, it, v, P, validate)

    def row_of(v, r):  # what coding._store + _load_row would make of it
        return {"value": r["value"], "evidence_status": r["evidence_status"], "validation_status": r["validation_status"],
                "validation": {"selections": v["selections"]}}

    print("\n[1] Validator and resolution (unit level)")
    check("0 the test variable is a multi-select categorical field", f["type"] == "categorical" and f.get("multi"))
    v, r = res(item("S1-P1", "INFERRED", ONE_INF, False))
    sel = {s["code"]: s.get("evidence_status") for s in v["selections"]}
    check("1 each kept code carries its own evidence status (stored with the selections)",
          sel == ONE_INF and {o["code"]: o.get("evidence_status") for o in v["options"]} == ONE_INF, str(sel))
    check("2 per-code statuses never change the value or validation (1, 4, 5 kept, valid)",
          r["value"] == "1, 4, 5" and r["validation_status"] == "valid" and r["status"] == "suggested")
    check("3 consistent reply (variable INFERRED, code 1 INFERRED) → no consistency warning, complete",
          not r["warnings"] and r["complete"], str(r["warnings"]))
    rr = es_mod.review_required(row_of(v, r))
    check("4 review reason names the uncertain code", "1 (INFERRED)" in rr and "4 (" not in rr, rr)
    check("4b code_statuses / uncertain_codes helpers", es_mod.code_statuses(row_of(v, r)) == [
        {"code": c, "evidence_status": s} for c, s in ONE_INF.items()]
          and [c["code"] for c in es_mod.uncertain_codes(row_of(v, r))] == ["1"])

    v, r = res(item("S1-P1", "SUPPORTED", ONE_INF, False))
    check("5 variable SUPPORTED but code 1 INFERRED → consistency warning; status NOT rewritten (no upgrade/downgrade)",
          "variable_status_stronger_than_code" in r["reason_codes"] and r["evidence_status"] == "SUPPORTED"
          and r["validation_status"] == "valid", str(r["reason_codes"]))
    rr = es_mod.review_required(row_of(v, r))
    check("6 …and it still needs human review (a variable is no stronger than its weakest code)",
          rr.startswith("code(s) not SUPPORTED: 1 (INFERRED)"), rr)

    v, r = res(item("S1-P1", "SUPPORTED", ALL_SUP, False))
    check("7 all codes SUPPORTED + variable SUPPORTED → no warning, no review reason",
          not r["reason_codes"] and es_mod.review_required(row_of(v, r)) == "")

    v, r = res(item("S1-P1", "SUPPORTED", None, False))
    check("8 per-code statuses missing (new-version reply) → warning, marked incomplete (never cached), value kept",
          "code_evidence_status_missing" in r["reason_codes"] and not r["complete"] and r["value"] == "1, 4, 5"
          and r["validation_status"] == "valid", str(r["reason_codes"]))
    check("8b …and the codes count as not SUPPORTED for review", "not recorded" in es_mod.review_required(row_of(v, r)))

    bad = item("S1-P1", "INFERRED", {"1": "MAYBE", "4": "SUPPORTED", "5": "SUPPORTED"}, False)
    v, r = res(bad)
    check("9 unknown per-code status → reported (not recorded), never a validation failure, codes kept",
          "invalid_code_evidence_status" in r["reason_codes"] and r["validation_status"] == "valid"
          and r["value"] == "1, 4, 5" and {s["code"]: s.get("evidence_status") for s in v["selections"]}["1"] is None
          and not r["complete"], str(r["reason_codes"]))
    it = item("S1-P1", "INFERRED", ONE_INF, False)
    it["options"].append({"code": "6", "evidence_status": "SUPPORTED", "evidence": [sup("S1-P1", "not in the passage at all")]})
    it["value"] = "1, 4, 5, 6"
    v, r = res(it)
    check("10 a rejected code's status is ignored (partially valid; only kept codes have statuses)",
          r["validation_status"] == "partially_valid" and [c["code"] for c in es_mod.code_statuses(row_of(v, r))] == ["1", "4", "5"])

    fs = F["SYSTEM_LEVEL"]  # single-select
    single = {"variable": "SYSTEM_LEVEL", "value": "3", "evidence_status": "SUPPORTED",
              "evidence": [sup("S1-P1", Q4)], "options": [], "alternatives": [], "missing_evidence": ""}
    v1 = validate(fs, single, P)
    r1 = es_mod.resolve(fs, single, v1, P, validate)
    check("11 single-select variables are unaffected (no per-code status, no new warning)",
          not es_mod.code_statuses(row_of(v1, r1)) and not r1["reason_codes"] and r1["complete"])
    legacy = {"value": "1, 4, 5", "evidence_status": "SUPPORTED", "validation_status": "valid",
              "validation": {"selections": [{"code": c, "outcome": "valid"} for c in ("1", "4", "5")]}}
    check("12 rows stored before per-code statuses → no code statuses; earlier review rule unchanged",
          es_mod.code_statuses(legacy) == [] and es_mod.review_required(legacy) == "")

    print("\n[2] Prompt and OpenAI strict schema v3")
    sp, ssp = coding.SYSTEM_PROMPT, coding.STRUCTURED_SYSTEM_PROMPT
    check("13 both prompts ask for a per-code evidence status and the weakest-code rule; new prompt version",
          all("EACH selected code" in x and "no stronger than its weakest selected code" in x for x in (sp, ssp))
          and '"evidence_status": "SUPPORTED" | "INFERRED" | "CONFLICTING"' in sp
          and "its own evidence status (SUPPORTED | INFERRED | CONFLICTING" in ssp
          and coding.PROMPT_VERSION == "wfd-prompt-2026-11-24")
    sch = build_batch_schema([F["SYSTEM_LEVEL"], f], ["S1-P1"])
    opt_schema = sch["properties"]["results"]["properties"][prop_key(1, VAR)]["properties"]["options"]["items"]
    check("14 schema v3: every option requires evidence_status ∈ {SUPPORTED, INFERRED, CONFLICTING}",
          RESPONSE_SCHEMA_VERSION == "wfd-batch-v3" and "evidence_status" in opt_schema["required"]
          and opt_schema["properties"]["evidence_status"]["enum"] == list(es_mod.CODE_EVIDENCE_STATUSES))
    good = {"results": {prop_key(0, VAR): item("S1-P1", "INFERRED", ONE_INF, True)}}
    norm = normalize_structured(good, [f])
    check("15 structured reply keeps per-code statuses through normalization",
          {o["code"]: o["evidence_status"] for o in norm[0]["options"]} == ONE_INF and norm[0]["value"] == "1, 4, 5")
    try:
        normalize_structured({"results": {prop_key(0, VAR): item("S1-P1", "INFERRED",
                                                                 {"1": "AMBIGUOUS", "4": "SUPPORTED", "5": "SUPPORTED"},
                                                                 True)}}, [f])
        viol = False
    except SchemaViolation:
        viol = True
    check("16 an out-of-schema per-code status is a schema violation (not cached)", viol)

    print("\n[3] Both providers through the pipeline: same codes, code 1 inferred by one of them")
    settings = {**DEFAULT_SETTINGS, "max_search_rounds": 0, "budget_usd": 50, "openai_budget_usd": 50}
    PX = re.compile(r"^\[(S\d+-P\d+)\] \(source[^\n]*\)\n", re.M)

    def stand_ins(claude_codes, claude_var, gpt_codes, gpt_var):
        class ClaudeLike:
            provider, model, supports_schema = "anthropic", "claude-sonnet-5-5", False

            def generation_settings(self):
                return {"stand_in": "claude", "plan": json.dumps([claude_codes, claude_var])}

            def complete(self, system, user, max_tokens=4000):
                pid = PX.findall(user)[0]
                names = [l.split("### ")[1].split("  (")[0] for l in user.splitlines() if l.startswith("### ")]
                return {"text": json.dumps({"results": [item(pid, claude_var, claude_codes, False) for n in names
                                                        if n == VAR]}),
                        "input_tokens": 900, "output_tokens": 150, "stop_reason": "end_turn"}

        class OpenAILike:
            provider, model, supports_schema = "openai", "gpt-6.1-sol", True

            def generation_settings(self):
                return {"stand_in": "openai", "plan": json.dumps([gpt_codes, gpt_var])}

            def complete(self, system, user, max_tokens=4000, schema=None):
                pid = PX.findall(user)[0]
                names = [l.split("### ")[1].split("  (")[0] for l in user.splitlines() if l.startswith("### ")]
                return {"text": json.dumps({"results": {prop_key(i, n): item(pid, gpt_var, gpt_codes, True)
                                                        for i, n in enumerate(names) if n == VAR}}),
                        "input_tokens": 900, "output_tokens": 150, "stop_reason": "completed"}
        return ClaudeLike(), OpenAILike()

    def new_case(name, claude_codes, claude_var, gpt_codes, gpt_var):
        cid = db.insert("cases", {"name": name, "location": "Pacific Palisades, Los Angeles", "date_text": "2025-01-07",
                                  "details": "", "known_links": "", "aliases": "", "schema_version_id": schema["id"],
                                  "status": "new", "identity_json": "{}", "settings_json": json.dumps(settings),
                                  "created_at": time.time(), "updated_at": time.time()})
        research.ingest_manual(cid, "text", {"title": "After-action report", "text": TEXT * 3})
        case = db.q1("SELECT * FROM cases WHERE id=?", (cid,))
        c, o = stand_ins(claude_codes, claude_var, gpt_codes, gpt_var)
        coding.run_coding_plan(case, settings, [(c, "independent"), (o, "independent")], None, lambda *a: None, None,
                               [VAR], mode="dual_independent")
        return cid

    cA = new_case("Palisade A (code 1 inferred by Claude)", ONE_INF, "INFERRED", ALL_SUP, "SUPPORTED")
    rows = {r["name"]: r for r in export.case_results(cA)["rows"]}
    row = rows[VAR]
    comp = row["comparison"] or {}
    check("17 comparison: 'uncertain_codes', naming code 1 (Claude INFERRED, GPT SUPPORTED), not plain agreement",
          comp.get("model_status") == "uncertain_codes"
          and comp.get("codes") == [{"code": "1", "anthropic": "INFERRED", "openai": "SUPPORTED"}], str(comp)[:300])
    ag = row["agreement"] or {}
    check("18 agreement: 'Same codes — some uncertain', never bulk-eligible, reason names code 1",
          ag.get("status") == "uncertain_codes" and not ag.get("eligible") and "1 INFERRED" in ag.get("reason", "")
          and ag.get("uncertain_codes") == {"Claude": ["1"]}, str(ag)[:300])
    check("19 not counted among bulk-confirmable variables", VAR not in [e["variable"] for e in
                                                                        agreement.eligible_summary(cA)["eligible"]])
    check("20 routed to human review (Pending), not hidden as agreement",
          row["category"] == "pending", row["category"])
    cells = row["cells"]
    check("21 Review table cells carry each provider's own per-code statuses",
          [c["evidence_status"] for c in cells["anthropic"]["code_statuses"]] == ["INFERRED", "SUPPORTED", "SUPPORTED"]
          and [c["evidence_status"] for c in cells["openai"]["code_statuses"]] == ["SUPPORTED"] * 3)
    v_un = export.export_value(row, include_unreviewed=True)
    check("22 never exported as an unreviewed value", v_un[0] == "", str(v_un))
    buf = io.BytesIO(export.xlsx(cA, include_unreviewed=False))
    import openpyxl
    ws = openpyxl.load_workbook(buf)["Provider_Suggestions"]
    hdr = [c.value for c in ws[1]]
    vals = {r[hdr.index("Provider")]: r[hdr.index("Code evidence status")] for r in ws.iter_rows(min_row=2, values_only=True)
            if r[0] == VAR}
    check("23 Excel Provider_Suggestions: 'Code evidence status' column per provider",
          vals.get("Anthropic API") == "1=INFERRED; 4=SUPPORTED; 5=SUPPORTED"
          and vals.get("OpenAI API") == "1=SUPPORTED; 4=SUPPORTED; 5=SUPPORTED", str(vals))
    calls = {r["provider"]: r["status"] for r in db.q("SELECT provider, status FROM model_calls WHERE case_id=?", (cA,))}
    check("24 consistent replies with per-code statuses are cached normally", calls == {"anthropic": "complete",
                                                                                      "openai": "complete"}, str(calls))

    cB = new_case("Palisade B (all codes supported by both)", ALL_SUP, "SUPPORTED", ALL_SUP, "SUPPORTED")
    rowB = {r["name"]: r for r in export.case_results(cB)["rows"]}[VAR]
    check("25 control: every code SUPPORTED by both → model agreement, bulk-eligible as before",
          (rowB["comparison"] or {}).get("model_status") == "model_agreement" and (rowB["agreement"] or {}).get("eligible"),
          str((rowB["agreement"] or {}).get("reason")))

    cC = new_case("Palisade C (Claude omits per-code statuses)", None, "SUPPORTED", ALL_SUP, "SUPPORTED")
    rowC = {r["name"]: r for r in export.case_results(cC)["rows"]}[VAR]
    callsC = {r["provider"]: r["status"] for r in db.q("SELECT provider, status FROM model_calls WHERE case_id=?", (cC,))}
    check("26 a new-version reply without per-code statuses is shown and flagged, not cached, not bulk-eligible",
          callsC.get("anthropic") == "complete_with_invalid_items" and not (rowC["agreement"] or {}).get("eligible")
          and (rowC["comparison"] or {}).get("model_status") == "uncertain_codes", f"{callsC} {(rowC['agreement'] or {}).get('status')}")

    print("\n[4] Browser: the uncertain code is marked in the Review table")
    env = {**os.environ, "WFD_PORT": "8857"}
    srv = subprocess.Popen([sys.executable, "-m", "app.server"], cwd=str(ROOT), env=env, stdout=subprocess.DEVNULL,
                           stderr=subprocess.STDOUT)
    ui = {}
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen("http://127.0.0.1:8857/healthz", timeout=1)
                break
            except Exception:
                time.sleep(0.5)
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page(viewport={"width": 1500, "height": 900})
            errors = []
            pg.on("pageerror", lambda e: errors.append(str(e)))
            pg.goto("http://127.0.0.1:8857/")
            pg.evaluate("localStorage.setItem('wfd_lang','en')")
            pg.goto(f"http://127.0.0.1:8857/#/case/{cA}/review")
            pg.reload()
            pg.wait_for_timeout(1500)
            marks = pg.locator(".code-unsure")
            ui["n_marks"] = marks.count()
            ui["mark_text"] = marks.first.inner_text() if ui["n_marks"] else ""
            ui["mark_title"] = marks.first.get_attribute("title") if ui["n_marks"] else ""
            ui["badge"] = pg.locator("tr:has(.code-unsure) td.ag-cell").first.inner_text()
            pg.locator(".code-unsure").first.click()
            pg.wait_for_timeout(800)
            ui["detail"] = pg.inner_text("body")
            pg.screenshot(path=str(TMP / "uncertain_codes.png"), full_page=False)
            ui["errors"] = errors
            b.close()
    finally:
        srv.terminate()
        srv.communicate(timeout=10)
    check("27 exactly one code is marked (Claude's code 1, shown as '1?'), with its status in the tooltip",
          ui.get("n_marks") == 1 and ui.get("mark_text", "").replace("\n", "") == "1?"
          and "Inferred" in (ui.get("mark_title") or ""), str({k: v for k, v in ui.items() if k != "detail"}))
    check("28 the comparison column says 'Same codes — some uncertain'", "Same codes" in ui.get("badge", ""), ui.get("badge"))
    check("29 the detail panel lists the evidence status per code; no page errors",
          "Evidence status per code" in ui.get("detail", "") and not ui.get("errors"), str(ui.get("errors")))
    print("  screenshot in", TMP)

    check("30 no live or paid API call was attempted", not NET, str(NET))
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED:", *FAIL, sep="\n  ")
        sys.exit(1)


if __name__ == "__main__":
    main()
