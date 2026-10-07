"""Bulk confirmation of independent model agreement (D-032). Run:  python -m tests.test_bulk_agreement

Offline: two scripted stand-in models ('anthropic' and 'openai') run through the real coding pipeline
(run_coding_plan → server validator → stored suggestions), then the eligibility rules, the bulk-confirm API, the
audit trail, undo/correction, re-analysis and exports are checked. No network, no paid calls.
"""
from __future__ import annotations

import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="wfdbulk_"))
os.environ["WFD_DATA_DIR"] = str(TMP / "data")
for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENAI_BASE_URL", "WFD_PASSWORD", "WFD_TEST_FIXTURE"):
    os.environ.pop(k, None)
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
REAL_SLEEP = time.sleep
PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS " if cond else "  FAIL ") + name + (f"  — {detail}" if detail and not cond else ""))


SRC1 = ("On July 4, 2025 Kerr County did not send a CodeRED alert before the Guadalupe River flash flood. The county "
        "used Everbridge for its local alerting system. The county emergency management office is a county agency. "
        "The National Weather Service issued a flash flood warning at 1:14 a.m. ") * 3
SRC2 = ("A state review of the Hill Country flash flood in Kerr County found that local officials lacked written "
        "procedures for overnight alerting. Training for the alert system was described as informal. ") * 3
PX = re.compile(r"^\[(S\d+-P\d+)\] \(source[^\n]*\)\n([^\n]+)", re.M)


class Model:
    """Scripted stand-in. policy[var] = value, or dict(value=..., fake_quote=True, counter=True, src=1)."""
    supports_schema = False
    CALLS: list = []  # every request any stand-in received (to prove cache reuse)

    def __init__(self, provider, model, policy, fail=False):
        self.provider, self.model, self.policy, self.fail, self.n = provider, model, policy, fail, 0

    def generation_settings(self):
        return {"stand_in": self.provider}

    def complete(self, system, user, max_tokens=4000):
        from app.llm.clients import LLMError
        self.n += 1
        Model.CALLS.append(self.provider)
        if self.fail:
            raise LLMError("HTTP 500 from provider (test)", possibly_billed=True, attempts=1)
        names = [l.split("### ")[1].split("  (")[0] for l in user.splitlines() if l.startswith("### ")]
        ps = PX.findall(user)
        by_src = {}
        for pid, text in ps:
            by_src.setdefault(pid.split("-")[0], []).append((pid, text))
        srcs = list(by_src)
        res = []
        for n in names:
            spec = self.policy.get(n)
            if spec is None or not ps:
                res.append({"variable": n, "value": "", "status": "insufficient_evidence", "evidence_status": "INSUFFICIENT", "evidence": []})
                continue
            spec = spec if isinstance(spec, dict) else {"value": spec}
            pid, text = by_src[srcs[min(spec.get("src", 0), len(srcs) - 1)]][0]
            q = "this sentence is not in the passage" if spec.get("fake_quote") else text.strip()[:60]
            ev = [{"id": pid, "quote": q, "stance": "supports"}]
            if spec.get("counter"):
                ev.append({"id": pid, "quote": text.strip()[:40], "stance": "alternative"})
            codes = [c.strip() for c in spec["value"].split(",")] if spec.get("multi") else []
            res.append({"variable": n, "value": spec["value"], "status": "suggested", "evidence_status": "SUPPORTED", "evidence": ev,
                        "options": [{"code": c, "evidence": ev[:1]} for c in codes] if len(codes) > 1 else [],
                        "rationale": f"{self.provider} rationale", "unresolved": ""})
        return {"text": json.dumps({"results": res}), "input_tokens": 1000, "output_tokens": 200, "stop_reason": "end_turn",
                "attempts": 1}


def main():
    from app import agreement, coding, db, export, research, server
    from app.config import DEFAULT_SETTINGS
    db.conn()
    server.bootstrap_schema()
    schema = coding.active_schema()
    fields = {f["name"]: f for f in schema["fields"]}

    class H:
        user = "coder1"

    def new_case(label):
        st = {**DEFAULT_SETTINGS, "max_search_rounds": 0, "budget_usd": 50, "openai_budget_usd": 50}
        cid = db.insert("cases", {"name": "Hill Country flash flood", "location": "Kerr County, Texas", "date_text": "July 4, 2025",
                                  "details": label, "known_links": "", "aliases": "", "schema_version_id": schema["id"],
                                  "status": "new", "identity_json": "{}", "settings_json": json.dumps(st),
                                  "created_at": time.time(), "updated_at": time.time()})
        research.ingest_manual(cid, "text", {"title": "County statement", "text": SRC1})
        research.ingest_manual(cid, "text", {"title": "State review", "text": SRC2})
        return cid, st

    case = lambda cid: db.q1("SELECT * FROM cases WHERE id=?", (cid,))
    log = lambda *a: None

    def run(cid, st, plan, variables, mode):
        return coding.run_coding_plan(case(cid), st, plan, None, log, None, variables, mode=mode)

    def ag(cid):
        return agreement.case_assessments(cid)

    A_POL = {"SYSTEM_LEVEL": "3", "SYSTEM_INVOLVED": {"value": "WEA, LOCAL", "multi": True}, "EVENT_DATE": "2025-07-04",
             "DELIVERY_COVERAGE": "13.5", "FAILURE_TYPE": "2", "INTERAGENCY_COORDINATION": "1", "ALERT_APPROVAL_PROCESS": "1",
             "SUMMARY": "Kerr County did not send a CodeRED alert.", "ALERT_ORIGINATOR_PLATFORM": "Everbridge",
             "TRANSMISSION_PATHWAY": "Carrier pigeon", "ALERTING_AUTHORITY_TYPE": {"value": "3", "counter": True},
             "TRAINING_AND_PROCEDURAL_CONTEXT": {"value": "1", "src": 0}, "MESSAGE_ARCHIVAL_STATUS": "1"}
    O_POL = {"SYSTEM_LEVEL": "3", "SYSTEM_INVOLVED": {"value": "LOCAL, WEA", "multi": True}, "EVENT_DATE": "2025-07-04",
             "DELIVERY_COVERAGE": "13.50", "FAILURE_TYPE": "6", "INTERAGENCY_COORDINATION": "9",
             "ALERT_APPROVAL_PROCESS": {"value": "1", "fake_quote": True}, "SUMMARY": "Kerr County did not send a CodeRED alert.",
             "ALERT_ORIGINATOR_PLATFORM": "everbridge", "TRANSMISSION_PATHWAY": "Carrier pigeon", "ALERTING_AUTHORITY_TYPE": "3",
             "TRAINING_AND_PROCEDURAL_CONTEXT": {"value": "1", "src": 1}, "MESSAGE_ARCHIVAL_STATUS": "1"}
    VARS = list(A_POL) + ["POPULATION_SCOPE"]
    claude = lambda pol=A_POL, fail=False: Model("anthropic", "claude-sonnet-5-5", pol, fail)
    openai = lambda pol=O_POL, fail=False: Model("openai", "gpt-6.1-sol", pol, fail)

    print("\n[1] Eligibility rules on one dual-independent run")
    cA, stA = new_case("bulk A")
    run(cA, stA, [(claude(), "independent"), (openai(), "independent")], VARS, "dual_independent")
    a = ag(cA)
    st = lambda v: (a.get(v) or {}).get("status")
    check("exact agreement (3 = 3) → eligible", st("SYSTEM_LEVEL") == "eligible", str(a.get("SYSTEM_LEVEL")))
    check("multi-select 'WEA, LOCAL' = 'LOCAL, WEA' → eligible", st("SYSTEM_INVOLVED") == "eligible", str(a.get("SYSTEM_INVOLVED")))
    check("dates normalized (ISO) → eligible", st("EVENT_DATE") == "eligible", str(a.get("EVENT_DATE")))
    check("numbers normalized (13.5 = 13.50) → eligible", st("DELIVERY_COVERAGE") == "eligible", str(a.get("DELIVERY_COVERAGE")))
    check("open list: listed option, case-insensitive ('Everbridge' = 'everbridge') → eligible",
          st("ALERT_ORIGINATOR_PLATFORM") == "eligible", str(a.get("ALERT_ORIGINATOR_PLATFORM")))
    check("open list: value not among the codebook's listed options → not eligible",
          st("TRANSMISSION_PATHWAY") == "pending" and "listed options" in a["TRANSMISSION_PATHWAY"]["reason"], str(a.get("TRANSMISSION_PATHWAY")))
    check("disagreement (2 vs 6) → Value disagreement", st("FAILURE_TYPE") == "value_disagreement")
    check("both blank → Both insufficient (never an agreed value)", st("POPULATION_SCOPE") == "both_insufficient"
          and not a["POPULATION_SCOPE"]["eligible"])
    check("invalid codebook value (9) → Validation failed", st("INTERAGENCY_COORDINATION") == "validation_failed")
    check("same value but invalid citation (quote not in passage) → Validation failed", st("ALERT_APPROVAL_PROCESS") == "validation_failed")
    check("free-text field with identical text → never eligible", st("SUMMARY") == "pending" and "free-text" in a["SUMMARY"]["reason"])
    check("counter-evidence reported → not eligible", st("ALERTING_AUTHORITY_TYPE") == "pending" and "contradicting" in a["ALERTING_AUTHORITY_TYPE"]["reason"])
    td = a.get("TRAINING_AND_PROCEDURAL_CONTEXT") or {}
    check("same value, different (valid) evidence sources → eligible, labelled 'evidence difference'",
          td.get("status") == "eligible_evidence_difference" and td.get("evidence_difference"), str(td))
    check("administrative / derived / generated fields are never assessed", not any(
        v in a for v in fields if fields[v].get("field_class") in ("admin", "derived", "analyst_note")))
    sid = db.q1("SELECT id FROM suggestions WHERE case_id=? AND variable='MESSAGE_ARCHIVAL_STATUS' AND provider='openai' ORDER BY id DESC", (cA,))["id"]
    check("before marking stale: MESSAGE_ARCHIVAL_STATUS eligible", st("MESSAGE_ARCHIVAL_STATUS") == "eligible")
    db.update("suggestions", sid, {"stale": 1, "stale_reason": "cites excluded source (test)"})
    check("a result citing a source excluded later → not eligible", ag(cA)["MESSAGE_ARCHIVAL_STATUS"]["status"] == "pending")
    check("eligibility requires the prompt version recorded on both runs",
          all(r["prompt_version"] == coding.PROMPT_VERSION for r in db.q("SELECT prompt_version FROM runs WHERE case_id=? AND provider IS NOT NULL", (cA,))))

    print("\n[2] Providers not completed, review mode, separate runs")
    cB, stB = new_case("bulk B")
    run(cB, stB, [(claude(), "primary")], VARS, "anthropic_only")
    check("one provider not run → Claude only", ag(cB)["SYSTEM_LEVEL"]["status"] == "claude_only")
    cC, stC = new_case("bulk C")
    run(cC, stC, [(claude(), "independent"), (openai(fail=True), "independent")], VARS, "dual_independent")
    check("failed provider → Claude only (not eligible)", ag(cC)["SYSTEM_LEVEL"]["status"] == "claude_only")
    cS, stS = new_case("bulk S")
    jid = db.insert("jobs", {"case_id": cS, "kind": "recode", "stage": "coding", "status": "running", "progress": 0.8, "message": "",
                             "params_json": "{}", "state_json": "{}", "created_at": time.time(), "updated_at": time.time(), "cancel_requested": 0})
    server.api_stop_provider(H(), str(jid), "openai")
    coding.run_coding_plan(case(cS), stS, [(claude(), "independent"), (openai(), "independent")], jid, log, None, VARS, mode="dual_independent")
    db.update("jobs", jid, {"status": "done"})
    check("stopped provider → Claude only (not eligible)", ag(cS)["SYSTEM_LEVEL"]["status"] == "claude_only")
    cD, stD = new_case("bulk D")
    coding.ALLOW_CROSS_MODEL_REVIEW = True  # historical-style data only; refused for new runs (D-036)
    run(cD, stD, [(claude(), "independent"), (openai(), "reviewer")], VARS, "anthropic_primary_openai_review")
    coding.ALLOW_CROSS_MODEL_REVIEW = False
    check("cross-model review (second model saw the first) → excluded from independent agreement",
          ag(cD)["SYSTEM_LEVEL"]["status"] == "cross_model_review" and not ag(cD)["SYSTEM_LEVEL"]["eligible"])
    # D-036: separate jobs on the SAME evidence snapshot and analysis version are comparable (D-035 replaced)
    cE, stE = new_case("bulk E")
    run(cE, stE, [(claude(), "independent")], VARS, "anthropic_only")
    run(cE, stE, [(openai(), "independent")], VARS, "openai_only")
    aE = ag(cE)
    check("Claude-only job, then OpenAI-only job, same evidence and analysis version → eligible (no warning)",
          aE["SYSTEM_LEVEL"]["status"] == "eligible" and aE["SYSTEM_LEVEL"]["eligible"]
          and "matched analysis version" in aE["SYSTEM_LEVEL"]["label"], str(aE["SYSTEM_LEVEL"]))
    check("their provenance is kept (two different runs, not relabelled 'same run')",
          aE["SYSTEM_LEVEL"]["claude"]["run_id"] != aE["SYSTEM_LEVEL"]["openai"]["run_id"])
    check("core checks still block (counter-evidence)", not aE["ALERTING_AUTHORITY_TYPE"]["eligible"]
          and aE["ALERTING_AUTHORITY_TYPE"]["status"] == "pending", str(aE["ALERTING_AUTHORITY_TYPE"]))
    check("core checks still block (invalid quote / validation)", not aE["ALERT_APPROVAL_PROCESS"]["eligible"])
    check("disagreement still a disagreement", aE["FAILURE_TYPE"]["status"] == "value_disagreement")
    check("free text never eligible", not aE["SUMMARY"]["eligible"])
    check("open list value not in the codebook never eligible", not aE["TRANSMISSION_PATHWAY"]["eligible"])
    check("both blank stays 'Both insufficient'", aE["POPULATION_SCOPE"]["status"] == "both_insufficient")
    # a later dual run on unchanged evidence reuses BOTH providers' validated replies from cache (K-40 fixed)
    n_req = len(Model.CALLS)
    n_uncacheable = db.q1("SELECT COUNT(*) n FROM model_calls WHERE case_id=? AND status='complete_with_invalid_items'",
                          (cE,))["n"]  # replies with an invalid item are never cached (D-025) and must be re-sent
    run(cE, stE, [(claude(), "independent"), (openai(), "independent")], VARS, "dual_independent")
    aE3 = ag(cE)["SYSTEM_LEVEL"]
    check("dual run after single-provider runs: only never-cached (invalid) batches are sent again; every complete, "
          "valid reply is reused from cache", len(Model.CALLS) - n_req == n_uncacheable and n_uncacheable >= 1,
          f"{len(Model.CALLS) - n_req} new vs {n_uncacheable} uncacheable")
    cs = {r["provider"]: r["cache_status"] for r in db.q("SELECT provider, cache_status FROM suggestions WHERE case_id=? "
                                                          "AND variable='SYSTEM_LEVEL' ORDER BY id DESC LIMIT 2", (cE,))}
    check("SYSTEM_LEVEL: both providers' results in the dual run came from cache", set(cs.values()) == {"hit"}, str(cs))
    check("cached results are eligible and labelled 'reused from validated cache', with original runs kept",
          aE3["eligible"] and aE3["reused_from_cache"] and "validated cache" in aE3["reason"]
          and aE3["claude"]["original_run_id"] != aE3["claude"]["run_id"], str(aE3))
    # results without recorded versions (before D-036) are not comparable
    rid_c = db.q1("SELECT run_id FROM suggestions WHERE case_id=? AND variable='SYSTEM_LEVEL' AND provider='anthropic' "
                  "ORDER BY id DESC", (cE,))["run_id"]
    db.ex("UPDATE suggestions SET evidence_snapshot_id=NULL, analysis_spec_id=NULL WHERE run_id=?", (rid_c,))
    aE2 = ag(cE)["SYSTEM_LEVEL"]
    check("result without a recorded evidence/analysis version → cross-version agreement, still eligible (D-035)",
          aE2["status"] == "eligible_cross_version" and aE2["eligible"] and "version not recorded" in aE2["differences"],
          str(aE2))
    db.ex("UPDATE suggestions SET evidence_snapshot_id=(SELECT evidence_snapshot_id FROM runs WHERE id=?), "
          "analysis_spec_id=(SELECT analysis_spec_id FROM runs WHERE id=?) WHERE run_id=?", (rid_c, rid_c, rid_c))
    sv = db.q1("SELECT schema_version_id FROM runs WHERE id=?", (rid_c,))["schema_version_id"]
    db.update("runs", rid_c, {"schema_version_id": (sv or 0) + 999})
    check("different codebook version blocks", not ag(cE)["SYSTEM_LEVEL"]["eligible"])
    db.update("runs", rid_c, {"schema_version_id": sv})
    rE = server.api_bulk_confirm(H(), str(cE), {"variables": ["SYSTEM_LEVEL"], "confirmed": True})
    rvE = db.q1("SELECT * FROM reviews WHERE case_id=? AND variable='SYSTEM_LEVEL'", (cE,))
    auE = db.q1("SELECT * FROM bulk_confirmations WHERE case_id=? AND variable='SYSTEM_LEVEL'", (cE,))
    check("confirmation writes Human final; the reason names the analysis version and the cache reuse",
          rE["confirmed"] and rvE["method"] == "bulk_independent_agreement" and "matched analysis version" in rvE["reason"]
          and "validated cache" in rvE["reason"], str(rvE))
    check("audit row keeps original runs, cache status, generation times, evidence and analysis versions",
          auE["evidence_snapshot_id"] and auE["analysis_spec_id"] and auE["claude_run_id"] and auE["openai_run_id"]
          and auE["claude_cache_status"] != "new" and auE["claude_generated_at"] and auE["openai_generated_at"], str(auE))
    check("after confirmation the status is 'human confirmed'", ag(cE)["SYSTEM_LEVEL"]["status"] == "confirmed")
    # evidence changed between the two providers' runs → not comparable
    cH, stH = new_case("bulk H")
    run(cH, stH, [(claude(), "independent")], VARS, "anthropic_only")
    research.ingest_manual(cH, "text", {"title": "Later county update", "text": SRC1 + " Additional detail was released later."})
    run(cH, stH, [(openai(), "independent")], VARS, "openai_only")
    check("Claude and OpenAI interpreted different evidence versions → cross-version agreement, eligible with disclosure",
          ag(cH)["SYSTEM_LEVEL"]["status"] == "eligible_cross_version" and ag(cH)["SYSTEM_LEVEL"]["eligible"]
          and "evidence version" in ag(cH)["SYSTEM_LEVEL"]["differences"], str(ag(cH)["SYSTEM_LEVEL"]))
    import openpyxl

    print("\n[3] Dialog data, explicit confirmation, unchecking, protection of existing Human final")
    server.api_review(H(), str(cA), {"variable": "EVENT_DATE", "action": "edit", "value": "2025-07-05", "reason": "AAR timeline"})
    server.api_review(H(), str(cA), {"variable": "DELIVERY_COVERAGE", "action": "defer"})
    n_rev = db.q1("SELECT COUNT(*) n FROM reviews WHERE case_id=?", (cA,))["n"]
    summ = server.api_bulk_agreements(H(), str(cA))
    names = {x["variable"] for x in summ["eligible"]}
    check("opening the dialog writes nothing", db.q1("SELECT COUNT(*) n FROM reviews WHERE case_id=?", (cA,))["n"] == n_rev)
    check("existing Human final (EVENT_DATE) excluded from the list", "EVENT_DATE" not in names)
    check("deferred variable excluded from the list", "DELIVERY_COVERAGE" not in names)
    check("dialog lists eligible variables with values and both model identifiers",
          names == {"SYSTEM_LEVEL", "SYSTEM_INVOLVED", "ALERT_ORIGINATOR_PLATFORM", "TRAINING_AND_PROCEDURAL_CONTEXT"}
          and all(x["claude"]["model"] == "claude-sonnet-5-5" and x["openai"]["model"] == "gpt-6.1-sol" and x["value"] for x in summ["eligible"]),
          str(sorted(names)))
    check("dialog reports excluded count and the warning", summ["excluded_count"] > 0 and "does not independently prove" in summ["note"])
    try:
        server.api_bulk_confirm(H(), str(cA), {"variables": ["SYSTEM_LEVEL"]})
        check("no write without explicit confirmation", False)
    except server.ApiError:
        check("no write without explicit confirmation", db.q1("SELECT COUNT(*) n FROM reviews WHERE case_id=?", (cA,))["n"] == n_rev)
    chosen = ["SYSTEM_LEVEL", "ALERT_ORIGINATOR_PLATFORM", "TRAINING_AND_PROCEDURAL_CONTEXT", "EVENT_DATE", "FAILURE_TYPE"]  # SYSTEM_INVOLVED unchecked
    r = server.api_bulk_confirm(H(), str(cA), {"variables": chosen, "confirmed": True})
    check("only the checked, still-eligible variables were confirmed",
          {x["variable"] for x in r["confirmed"]} == {"SYSTEM_LEVEL", "ALERT_ORIGINATOR_PLATFORM", "TRAINING_AND_PROCEDURAL_CONTEXT"}, str(r))
    check("existing Human final and ineligible variables were skipped with reasons",
          {x["variable"] for x in r["skipped"]} == {"EVENT_DATE", "FAILURE_TYPE"} and all(x["reason"] for x in r["skipped"]))
    ev = db.q1("SELECT * FROM reviews WHERE case_id=? AND variable='EVENT_DATE'", (cA,))
    check("existing Human final never overwritten", ev["value"] == "2025-07-05" and ev["action"] == "edited" and not ev["method"])
    check("unchecked variable stays eligible and unreviewed", ag(cA)["SYSTEM_INVOLVED"]["status"] == "eligible"
          and not db.q1("SELECT 1 x FROM reviews WHERE case_id=? AND variable='SYSTEM_INVOLVED'", (cA,)))
    rv = db.q1("SELECT * FROM reviews WHERE case_id=? AND variable='SYSTEM_LEVEL'", (cA,))
    check("Human final written with method bulk_independent_agreement, reviewer and time",
          rv["value"] == "3" and rv["action"] == "accepted" and rv["method"] == "bulk_independent_agreement"
          and rv["reviewer"] == "coder1" and rv["updated_at"] > 0)
    au = db.q1("SELECT * FROM bulk_confirmations WHERE case_id=? AND variable='SYSTEM_LEVEL'", (cA,))
    check("audit row: value, both result ids, both models, codebook + prompt versions, reviewer, time, method, previous value",
          au and au["value"] == "3" and au["claude_suggestion_id"] and au["openai_suggestion_id"] and au["claude_model"] == "claude-sonnet-5-5"
          and au["openai_model"] == "gpt-6.1-sol" and au["codebook_version"] and au["prompt_version"] == coding.PROMPT_VERSION
          and au["reviewer"] == "coder1" and au["at"] and au["method"] == "bulk_independent_agreement" and au["previous_value"] is None, str(au))
    check("history entry records the bulk method", db.q1("SELECT method FROM review_history WHERE case_id=? AND variable='SYSTEM_LEVEL' ORDER BY id DESC", (cA,))["method"] == "bulk_independent_agreement")
    check("status becomes 'Independent model agreement — human confirmed'", ag(cA)["SYSTEM_LEVEL"]["status"] == "confirmed")
    check("both provider results preserved after confirmation",
          db.q1("SELECT COUNT(*) n FROM suggestions WHERE case_id=? AND variable='SYSTEM_LEVEL' AND provider IN ('anthropic','openai')", (cA,))["n"] == 2)
    server.api_review(H(), str(cA), {"variable": "SYSTEM_INVOLVED", "action": "edit", "value": "WEA", "reason": "changed meanwhile"})
    r2 = server.api_bulk_confirm(H(), str(cA), {"variables": ["SYSTEM_INVOLVED"], "confirmed": True})
    check("eligibility re-checked at write time (changed meanwhile → skipped, not overwritten)",
          not r2["confirmed"] and db.q1("SELECT value FROM reviews WHERE case_id=? AND variable='SYSTEM_INVOLVED'", (cA,))["value"] == "WEA")

    print("\n[4] Export, re-analysis, undo and correction")
    import openpyxl
    xl = openpyxl.load_workbook(io.BytesIO(export.xlsx(cA)))
    hdr = [c.value for c in xl["Case_Row"][1]]
    row2 = [c.value for c in xl["Case_Row"][2]]
    col = lambda v: hdr.index(fields[v]["raw_header"])
    check("Case_Row contains the bulk-confirmed value", row2[col("SYSTEM_LEVEL")] == 3)
    check("Case_Row leaves disputed / pending / unconfirmed variables blank",
          row2[col("FAILURE_TYPE")] in (None, "") and row2[col("POPULATION_SCOPE")] in (None, "") and row2[col("TRANSMISSION_PATHWAY")] in (None, ""))
    res = {r[0].value: [c.value for c in r] for r in xl["Results"].iter_rows(min_row=2)}
    rh = [c.value for c in xl["Results"][1]]
    check("Results shows the value and its origin as human-approved model agreement",
          res["SYSTEM_LEVEL"][1] == 3 or res["SYSTEM_LEVEL"][1] == "3")
    check("Results 'Confirmation method' column says human-approved model agreement",
          res["SYSTEM_LEVEL"][rh.index("Confirmation method")] == "human-approved model agreement (bulk)"
          and "bulk confirmation" in res["SYSTEM_LEVEL"][rh.index("Explanation")])
    check("Bulk_Confirmations audit sheet present with the 3 confirmations", "Bulk_Confirmations" in xl.sheetnames
          and len(list(xl["Bulk_Confirmations"].iter_rows(min_row=2))) == 3)
    ps = [[c.value for c in r] for r in xl["Provider_Suggestions"].iter_rows(min_row=2) if r[0].value == "SYSTEM_LEVEL"]
    check("Provider_Suggestions keeps the separate Claude and OpenAI results", {p[1] for p in ps} == {"Anthropic API", "OpenAI API"})  # display names (2026-10-06)
    before = {r["variable"]: (r["value"], r["method"]) for r in db.q("SELECT * FROM reviews WHERE case_id=?", (cA,))}
    pol2 = {**A_POL, "SYSTEM_LEVEL": "5"}
    run(cA, stA, [(claude(pol2), "independent"), (openai({**O_POL, "SYSTEM_LEVEL": "4"}), "independent")], ["SYSTEM_LEVEL", "ALERT_ORIGINATOR_PLATFORM"], "dual_independent")
    after = {r["variable"]: (r["value"], r["method"]) for r in db.q("SELECT * FROM reviews WHERE case_id=?", (cA,))}
    check("re-analysis never overwrites a bulk-confirmed Human final", before == after)
    server.api_review(H(), str(cA), {"variable": "ALERT_ORIGINATOR_PLATFORM", "action": "edit", "value": "CodeRED", "reason": "AAR names CodeRED"})
    rv = db.q1("SELECT * FROM reviews WHERE case_id=? AND variable='ALERT_ORIGINATOR_PLATFORM'", (cA,))
    check("later manual correction through the normal review panel works", rv["value"] == "CodeRED" and rv["action"] == "edited" and not rv["method"])
    check("audit row of the original bulk confirmation is kept after correction",
          db.q1("SELECT COUNT(*) n FROM bulk_confirmations WHERE case_id=? AND variable='ALERT_ORIGINATOR_PLATFORM'", (cA,))["n"] == 1)
    server.api_review(H(), str(cA), {"variable": "TRAINING_AND_PROCEDURAL_CONTEXT", "action": "reset", "reason": "undo"})
    check("undo (Reset) removes the Human final; the variable becomes eligible again",
          not db.q1("SELECT 1 x FROM reviews WHERE case_id=? AND variable='TRAINING_AND_PROCEDURAL_CONTEXT'", (cA,))
          and ag(cA)["TRAINING_AND_PROCEDURAL_CONTEXT"]["eligible"])
    rows = {r["name"]: r for r in export.case_results(cA)["rows"]}
    check("word 'confirmed' only after a human action: unconfirmed eligible rows are not 'confirmed'",
          rows["TRAINING_AND_PROCEDURAL_CONTEXT"]["category"] != "confirmed" and rows["SYSTEM_LEVEL"]["category"] == "confirmed")

    print("\n[5] Browser: button, dialog, unchecking, confirm")
    cF, stF = new_case("bulk F (browser)")
    run(cF, stF, [(claude(), "independent"), (openai(), "independent")], ["SYSTEM_LEVEL", "SYSTEM_INVOLVED", "ALERT_ORIGINATOR_PLATFORM", "FAILURE_TYPE"], "dual_independent")
    n_el = len(server.api_bulk_agreements(H(), str(cF))["eligible"])
    cG, stG = new_case("bulk G (browser, two jobs on the same evidence)")
    run(cG, stG, [(claude(), "independent")], ["SYSTEM_LEVEL"], "anthropic_only")
    run(cG, stG, [(openai(), "independent")], ["SYSTEM_LEVEL"], "openai_only")
    sep_ok = False
    env = {**os.environ, "WFD_PORT": "8851"}
    srv = subprocess.Popen([sys.executable, "-m", "app.server"], cwd=str(ROOT), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    ok = False
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen("http://127.0.0.1:8851/healthz", timeout=1)
                break
            except Exception:
                REAL_SLEEP(0.5)
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page(viewport={"width": 1500, "height": 900})
            errors = []
            pg.on("pageerror", lambda e: errors.append(str(e)))
            pg.goto("http://127.0.0.1:8851/")
            pg.evaluate("localStorage.setItem('wfd_lang','en')")
            pg.goto(f"http://127.0.0.1:8851/#/case/{cF}/review")
            pg.reload()
            pg.wait_for_timeout(1500)
            btn = pg.inner_text("#bulkBtn")
            print("  button:", btn)
            pg.click("#bulkBtn")
            pg.wait_for_selector("#bulkTable", timeout=5000)
            n_rows = pg.locator(".bulkChk").count()
            dlg = pg.inner_text(".modal")
            pg.screenshot(path=str(TMP / "bulk_dialog.png"))
            pg.locator(".bulkChk").first.uncheck()
            k = pg.inner_text("#bulkK")
            pg.click("#bulkOk")
            pg.wait_for_timeout(1500)
            written = db.q1("SELECT COUNT(*) n FROM reviews WHERE case_id=? AND method='bulk_independent_agreement'", (cF,))["n"]
            pg.screenshot(path=str(TMP / "bulk_after.png"))
            pg.goto(f"http://127.0.0.1:8851/#/case/{cG}/review")
            pg.reload()
            pg.wait_for_timeout(1500)
            pg.click("#bulkBtn")
            pg.wait_for_selector("#bulkTable", timeout=5000)
            g_checked = pg.locator(".bulkChk").first.is_checked()
            g_ok_disabled = pg.locator("#bulkOk").is_disabled()
            g_dlg = pg.inner_text(".modal")
            pg.screenshot(path=str(TMP / "bulk_two_jobs_dialog.png"))
            pg.click("#bulkOk")
            pg.wait_for_timeout(1500)
            g_written = db.q1("SELECT COUNT(*) n FROM reviews WHERE case_id=? AND method='bulk_independent_agreement'", (cG,))["n"]
            sep_ok = (g_checked and not g_ok_disabled and "Separate runs" not in g_dlg and g_written == 1)
            print(f"  two-job item: checked-by-default={g_checked} confirm-disabled={g_ok_disabled} written={g_written}")
            ok = (f"Confirm {n_el} model agreement" in btn and n_rows == n_el and "does not independently prove" in dlg
                  and "gpt-6.1-sol" in dlg and "claude-sonnet-5-5" in dlg and k == str(n_el - 1) and written == n_el - 1 and not errors)
            print(f"  eligible={n_el} rows={n_rows} after-uncheck={k} written={written} errors={errors}")
            b.close()
    finally:
        srv.terminate()
        srv.communicate(timeout=10)
    check("browser: button shows the count; dialog lists models and warning; unchecked item not written", ok)
    check("browser: agreement from two jobs on the same evidence/analysis version is ticked like any eligible item "
          "(no separate-runs warning) and confirming writes it", sep_ok)
    print("  screenshots in", TMP)
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED:", FAIL)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
