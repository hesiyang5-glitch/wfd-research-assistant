"""Provider-neutral evidence status (D-038). Run:  python -m tests.test_evidence_status

Offline: scripted Claude-style (JSON text) and OpenAI-style (strict structured) stand-ins, a network guard, no search,
no paid call. Covers all five evidence statuses for BOTH providers, validation failures (kept separate from evidence
status), agreement never upgrading a status, phenomenon vs cause, human-final separation, legacy rows, migration and
export columns.
"""
from __future__ import annotations

import io
import json
import os
import re
import socket
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="wfdes_"))
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


Q_COUNTY = "Kerr County officials did not send a CodeRED alert to residents"
Q_LOCAL = "the county's local CodeRED system was not activated in time"
Q_CAUSE_A = "officials blamed a software outage at the vendor"
Q_CAUSE_B = "a state review found staff were not trained to send the alert"
Q_SCOPE = "residents along the Guadalupe River"
Q_COORD = "the county and the city exchanged calls during the night"
TEXT = (f"Hill Country flash flood, Kerr County, Texas, July 4, 2025. {Q_COUNTY} along the Guadalupe River before the "
        f"water rose. However, {Q_LOCAL}. In one account {Q_CAUSE_A}; in another, {Q_CAUSE_B}. Reports say "
        f"{Q_SCOPE} were most affected and {Q_COORD}. ")

# variable -> (evidence status, value, kind of evidence) — the same plan is answered by BOTH providers
PLAN = {
    "SYSTEM_LEVEL": "SUPPORTED",                      # county-level system, directly stated
    "SYSTEM_INVOLVED": "SUPPORTED_PHENOMENON",        # documented failure phenomenon (local system not activated)
    "FAILURE_TYPE": "CONFLICTING",                    # cause variable: competing explanations
    "POPULATION_SCOPE": "INFERRED",                   # best interpretation, needs an inference
    "INTERAGENCY_COORDINATION": "AMBIGUOUS",          # two permitted values remain reasonable
    "ALERT_APPROVAL_PROCESS": "INSUFFICIENT",         # nothing in the passages
    "TRAINING_AND_PROCEDURAL_CONTEXT": "INSUFFICIENT_WITH_VALUE",  # model proposes a value anyway
    "GEOCODE_SPECIFICITY": "FABRICATED_QUOTE",        # validation failure: quote not in the passage
    "REDUNDANCY_AND_CHANNEL_BEHAVIOR": "INVALID_CODE",  # validation failure: code not in the codebook
    "ALERT_INITIATION_AUTHORITY": "BAD_STATUS",       # malformed evidence status (Claude only; OpenAI schema forbids it)
}
VARS = list(PLAN)


def sup(pid, q, stance="supports"):
    return {"id": pid, "quote": q, "stance": stance}


def answer(var, pid, structured):
    kind = PLAN[var]
    base = {"variable": var, "value": "", "evidence": [], "options": [], "alternatives": [], "missing_evidence": "",
            "rule_unclear": False, "rationale": f"{kind} rationale", "unresolved": ""}
    if kind == "SUPPORTED":
        return {**base, "value": "3", "evidence_status": "SUPPORTED", "evidence": [sup(pid, Q_COUNTY)]}
    if kind == "SUPPORTED_PHENOMENON":
        val = ["LOCAL"] if structured else "LOCAL"
        return {**base, "value": val, "evidence_status": "SUPPORTED", "evidence": [sup(pid, Q_LOCAL)]}
    if kind == "CONFLICTING":
        return {**base, "value": "", "evidence_status": "CONFLICTING",
                "evidence": [sup(pid, Q_CAUSE_A, "alternative"), sup(pid, Q_CAUSE_B, "alternative")],
                "missing_evidence": "an after-action report establishing the cause"}
    if kind == "INFERRED":
        return {**base, "value": "2", "evidence_status": "INFERRED", "evidence": [sup(pid, Q_SCOPE)],
                "rationale": "the affected area is inferred from the river corridor"}
    if kind == "AMBIGUOUS":
        return {**base, "value": "1", "evidence_status": "AMBIGUOUS", "evidence": [sup(pid, Q_COORD)],
                "alternatives": [{"value": "2", "evidence": [sup(pid, Q_COORD)]}]}
    if kind == "INSUFFICIENT":
        return {**base, "evidence_status": "INSUFFICIENT", "missing_evidence": "the county's approval procedure"}
    if kind == "INSUFFICIENT_WITH_VALUE":
        return {**base, "value": "2", "evidence_status": "INSUFFICIENT", "missing_evidence": "training records"}
    if kind == "FABRICATED_QUOTE":
        return {**base, "value": "2", "evidence_status": "SUPPORTED",
                "evidence": [sup(pid, "the alert reached every home in the county")]}
    if kind == "INVALID_CODE":
        return {**base, "value": "9" if not structured else "0", "evidence_status": "SUPPORTED",
                "evidence": [sup(pid, Q_LOCAL)] if not structured else [sup(pid, "sirens wailed across the valley")]}
    if kind == "BAD_STATUS":
        if structured:  # the strict schema cannot carry an unknown status; OpenAI side: plain INSUFFICIENT
            return {**base, "evidence_status": "INSUFFICIENT"}
        return {**base, "value": "1", "evidence_status": "MAYBE", "evidence": [sup(pid, Q_COUNTY)]}
    raise AssertionError(kind)


def main():
    from app import agreement, coding, db, export, migrations, research, server
    from app import evidence_status as es_mod
    from app.config import DEFAULT_SETTINGS
    from app.llm.structured import (RESPONSE_SCHEMA_VERSION, SchemaViolation, build_batch_schema, normalize_structured,
                                    prop_key)
    from app.validator import validate
    db.conn()
    server.bootstrap_schema()
    schema = coding.active_schema()
    F = {f["name"]: f for f in schema["fields"]}
    P = {"S1-P1": {"text": TEXT, "source_id": 1}}

    print("\n[1] Resolution rules (unit level)")
    f = F["SYSTEM_LEVEL"]

    def res(item):
        v = validate(f, item, P)
        return es_mod.resolve(f, item, v, P, validate)
    r = res(answer("SYSTEM_LEVEL", "S1-P1", False))
    check("1 SUPPORTED + valid evidence → suggested, value kept, validation valid",
          (r["status"], r["value"], r["evidence_status"], r["validation_status"]) == ("suggested", "3", "SUPPORTED", "valid"))
    r = res({"variable": "SYSTEM_LEVEL", "value": "2", "evidence_status": "INFERRED", "evidence": [sup("S1-P1", Q_SCOPE)]})
    check("2 INFERRED → value kept as a candidate (status suggested) with evidence status INFERRED",
          r["value"] == "2" and r["evidence_status"] == "INFERRED" and r["validation_status"] == "valid")
    check("2b INFERRED requires human review (never treated as a final value)",
          bool(es_mod.review_required({"validation_status": "valid", "evidence_status": "INFERRED"})))
    r = res({"value": "1", "evidence_status": "AMBIGUOUS", "evidence": [sup("S1-P1", Q_COORD)],
             "alternatives": [{"value": "2", "evidence": [sup("S1-P1", Q_COORD)]},
                              {"value": "99", "evidence": [sup("S1-P1", Q_COORD)]}]})
    check("3 AMBIGUOUS → disputed; best candidate may be kept; supported alternative kept; invalid alternative rejected",
          r["status"] == "disputed" and r["value"] == "1" and [a["value"] for a in r["alternatives"]] == ["2"]
          and "alternative_rejected" in r["reason_codes"] and r["validation_status"] == "valid", str(r)[:300])
    r = res({"value": "", "evidence_status": "AMBIGUOUS", "evidence": []})
    check("3b AMBIGUOUS without alternatives → consistency warning (not a validation failure)",
          "ambiguous_without_alternatives" in r["reason_codes"] and r["validation_status"] == "valid")
    r = res({"value": "4", "evidence_status": "INSUFFICIENT", "evidence": [], "missing_evidence": "x"})
    check("4 INSUFFICIENT + proposed value (no evidence) → value NOT kept, blank, warning, not a validation failure",
          r["status"] == "insufficient_evidence" and r["value"] == "" and "value_with_insufficient" in r["reason_codes"]
          and r["validation_status"] == "valid", str(r)[:300])
    r = res({"value": "", "evidence_status": "CONFLICTING", "evidence": [sup("S1-P1", Q_CAUSE_A, "contradicts")]})
    check("5 CONFLICTING with counter-evidence → disputed, blank allowed, no warning",
          r["status"] == "disputed" and r["value"] == "" and not r["reason_codes"])
    r = res({"value": "", "evidence_status": "CONFLICTING", "evidence": []})
    check("5b CONFLICTING without any counter-evidence → consistency warning",
          "conflicting_without_counter_evidence" in r["reason_codes"])
    r = res({"value": "3", "evidence_status": "MAYBE", "evidence": [sup("S1-P1", Q_COUNTY)]})
    check("6 unknown evidence status → validation_failed (invalid_evidence_status), never a value",
          r["status"] == "validation_failed" and r["value"] == "" and "invalid_evidence_status" in r["reason_codes"])
    r = res({"value": "3", "evidence_status": "SUPPORTED", "evidence": [sup("S1-P1", "made up quotation text here")]})
    check("7 SUPPORTED but fabricated quote → validation invalid; evidence status kept as reported (separate dimension)",
          r["status"] == "validation_failed" and r["validation_status"] == "invalid" and r["evidence_status"] == "SUPPORTED")
    r = res({"value": "3", "status": "suggested", "evidence": [sup("S1-P1", Q_COUNTY)]})
    check("8 reply without evidence status → stored as 'not recorded' + warning, marked incomplete (not cached)",
          r["evidence_status"] is None and not r["complete"] and "evidence_status_missing" in r["reason_codes"])
    r = res({"value": "", "evidence_status": "SUPPORTED", "evidence": []})
    check("9 SUPPORTED without a value → blank, warning status_without_value (status is not silently changed)",
          r["status"] == "insufficient_evidence" and r["evidence_status"] == "SUPPORTED"
          and "status_without_value" in r["reason_codes"])

    print("\n[2] OpenAI strict schema v2")
    sch = build_batch_schema([F["SYSTEM_LEVEL"], F["SYSTEM_INVOLVED"]], ["S1-P1"])
    item = sch["properties"]["results"]["properties"][prop_key(0, "SYSTEM_LEVEL")]
    check("10 schema v2 requires evidence_status (enum of the five), alternatives, missing_evidence, rule_unclear",
          RESPONSE_SCHEMA_VERSION == "wfd-batch-v2"
          and {"evidence_status", "alternatives", "missing_evidence", "rule_unclear"} <= set(item["required"])
          and item["properties"]["evidence_status"]["enum"] == list(es_mod.EVIDENCE_STATUSES)
          and "status" not in item["properties"])
    check("10b alternatives' values are limited to codebook codes",
          item["properties"]["alternatives"]["items"]["properties"]["value"]["enum"] == [c["code"] for c in F["SYSTEM_LEVEL"]["codes"]])
    try:
        normalize_structured({"results": {prop_key(0, "SYSTEM_LEVEL"): {**answer("SYSTEM_LEVEL", "S1-P1", True),
                                                                       "evidence_status": "PROBABLY"}}}, [F["SYSTEM_LEVEL"]])
        bad = False
    except SchemaViolation:
        bad = True
    check("11 OpenAI reply with an out-of-schema evidence status is a schema violation (not cached)", bad)

    print("\n[3] Both providers through the coding pipeline (Claude JSON text, OpenAI structured)")
    settings = {**DEFAULT_SETTINGS, "max_search_rounds": 0, "budget_usd": 50, "openai_budget_usd": 50}
    cid = db.insert("cases", {"name": "Hill Country flash flood", "location": "Kerr County, Texas", "date_text": "July 4, 2025",
                              "details": "", "known_links": "", "aliases": "", "schema_version_id": schema["id"],
                              "status": "new", "identity_json": "{}", "settings_json": json.dumps(settings),
                              "created_at": time.time(), "updated_at": time.time()})
    research.ingest_manual(cid, "text", {"title": "County statement", "text": TEXT * 3})
    PX = re.compile(r"^\[(S\d+-P\d+)\] \(source[^\n]*\)\n", re.M)
    SEEN = {"system": []}

    class ClaudeLike:
        provider, model, supports_schema = "anthropic", "claude-sonnet-5-5", False

        def generation_settings(self):
            return {"stand_in": "claude"}

        def complete(self, system, user, max_tokens=4000):
            SEEN["system"].append(system)
            pid = PX.findall(user)[0]
            names = [l.split("### ")[1].split("  (")[0] for l in user.splitlines() if l.startswith("### ")]
            return {"text": json.dumps({"results": [answer(n, pid, False) for n in names]}), "input_tokens": 900,
                    "output_tokens": 150, "stop_reason": "end_turn"}

    class OpenAILike:
        provider, model, supports_schema = "openai", "gpt-6.1-sol", True

        def generation_settings(self):
            return {"stand_in": "openai"}

        def complete(self, system, user, max_tokens=4000, schema=None):
            SEEN["system"].append(system)
            pid = PX.findall(user)[0]
            names = [l.split("### ")[1].split("  (")[0] for l in user.splitlines() if l.startswith("### ")]
            return {"text": json.dumps({"results": {prop_key(i, n): answer(n, pid, True) for i, n in enumerate(names)}}),
                    "input_tokens": 900, "output_tokens": 150, "stop_reason": "completed"}

    case = db.q1("SELECT * FROM cases WHERE id=?", (cid,))
    coding.run_coding_plan(case, settings, [(ClaudeLike(), "independent"), (OpenAILike(), "independent")], None,
                           lambda *a: None, None, VARS, mode="dual_independent")
    check("12 the shared rules sent to both providers define all five evidence statuses",
          SEEN["system"] and all(all(s in sp for s in es_mod.EVIDENCE_STATUSES) for sp in SEEN["system"]))

    def row(var, prov):
        return db.q1("SELECT * FROM suggestions WHERE case_id=? AND variable=? AND provider=? ORDER BY id DESC",
                     (cid, var, prov))
    for prov, label in (("anthropic", "Claude"), ("openai", "OpenAI")):
        s = {v: row(v, prov) for v in VARS}
        check(f"13 {label}: SUPPORTED stored (value 3, suggested, validation valid)",
              (s["SYSTEM_LEVEL"]["evidence_status"], s["SYSTEM_LEVEL"]["status"], s["SYSTEM_LEVEL"]["value"],
               s["SYSTEM_LEVEL"]["validation_status"]) == ("SUPPORTED", "suggested", "3", "valid"), str(s["SYSTEM_LEVEL"]["status"]))
        check(f"14 {label}: INFERRED stored with its best candidate and status INFERRED (not upgraded)",
              s["POPULATION_SCOPE"]["evidence_status"] == "INFERRED" and s["POPULATION_SCOPE"]["value"] == "2")
        alts = json.loads(s["INTERAGENCY_COORDINATION"]["alternatives_json"] or "[]")
        check(f"15 {label}: AMBIGUOUS → disputed, best candidate + validated alternative stored",
              s["INTERAGENCY_COORDINATION"]["evidence_status"] == "AMBIGUOUS"
              and s["INTERAGENCY_COORDINATION"]["status"] == "disputed" and [a["value"] for a in alts] == ["2"])
        check(f"16 {label}: INSUFFICIENT → blank value, missing evidence recorded",
              s["ALERT_APPROVAL_PROCESS"]["evidence_status"] == "INSUFFICIENT" and s["ALERT_APPROVAL_PROCESS"]["value"] == ""
              and s["ALERT_APPROVAL_PROCESS"]["status"] == "insufficient_evidence"
              and "approval procedure" in (s["ALERT_APPROVAL_PROCESS"]["missing_evidence"] or ""))
        t = s["TRAINING_AND_PROCEDURAL_CONTEXT"]
        check(f"16b {label}: INSUFFICIENT with a proposed value → the value is not forced (blank, warned)",
              t["value"] == "" and t["status"] == "insufficient_evidence"
              and "value_with_insufficient" in json.loads(t["validation_json"])["reason_codes"])
        c = s["FAILURE_TYPE"]
        check(f"17 {label}: CONFLICTING cause → disputed, blank, both competing passages kept as counter-evidence",
              c["evidence_status"] == "CONFLICTING" and c["status"] == "disputed" and c["value"] == ""
              and len(json.loads(c["counter_json"])) == 2)
        ph = s["SYSTEM_INVOLVED"]
        check(f"18 {label}: cause uncertainty does not erase the separately supported failure phenomenon",
              ph["evidence_status"] == "SUPPORTED" and ph["value"] == "LOCAL" and ph["status"] == "suggested")
        g = s["GEOCODE_SPECIFICITY"]
        check(f"19 {label}: fabricated quote → validation_failed / invalid, separate from evidence status",
              g["status"] == "validation_failed" and g["validation_status"] == "invalid" and g["value"] == ""
              and g["evidence_status"] == "SUPPORTED")
        ic = s["REDUNDANCY_AND_CHANNEL_BEHAVIOR"]
        check(f"20 {label}: invalid code / unsupported quote → validation_failed",
              ic["status"] == "validation_failed" and ic["validation_status"] == "invalid" and ic["value"] == "")
    bs = row("ALERT_INITIATION_AUTHORITY", "anthropic")
    check("21 Claude: malformed evidence status → validation_failed (invalid_evidence_status)",
          bs["status"] == "validation_failed" and "invalid_evidence_status" in json.loads(bs["validation_json"])["reason_codes"])
    calls = db.q("SELECT provider, status, variables_json FROM model_calls WHERE case_id=?", (cid,))
    bad_vars = {"GEOCODE_SPECIFICITY", "REDUNDANCY_AND_CHANNEL_BEHAVIOR"}
    with_bad = [c for c in calls if bad_vars & set(json.loads(c["variables_json"] or "[]"))]
    check("22 a reply with invalid items is not cached (D-025); fully valid batches are",
          with_bad and all(c["status"] == "complete_with_invalid_items" for c in with_bad)
          and all(c["status"] == "complete" for c in calls if c not in with_bad
                  and "ALERT_INITIATION_AUTHORITY" not in json.loads(c["variables_json"] or "[]")),
          str([(c["provider"], c["status"], c["variables_json"]) for c in calls]))

    print("\n[4] Agreement, export and human-final separation")
    ag = agreement.case_assessments(cid)
    check("23 both SUPPORTED + same value → bulk-eligible", ag["SYSTEM_LEVEL"]["eligible"], str(ag["SYSTEM_LEVEL"])[:200])
    check("24 both INFERRED + same value → NOT eligible; agreement does not upgrade INFERRED",
          not ag["POPULATION_SCOPE"]["eligible"] and "does not upgrade" in ag["POPULATION_SCOPE"]["reason"],
          str(ag["POPULATION_SCOPE"])[:300])
    check("25 both AMBIGUOUS with the same best candidate → NOT eligible", not ag["INTERAGENCY_COORDINATION"]["eligible"])
    check("26 agreement result carries each provider's own evidence status",
          ag["POPULATION_SCOPE"].get("evidence_statuses") == {"claude": "INFERRED", "openai": "INFERRED"})
    rows = {r["name"]: r for r in export.case_results(cid)["rows"]}
    d = rows["POPULATION_SCOPE"]["suggestion"]
    check("27 combined view keeps INFERRED (never shown as SUPPORTED because the models agree)",
          d["evidence_status"] == "INFERRED" and d["evidence_review_reason"])
    check("28 cells show evidence status and validation status separately",
          rows["SYSTEM_LEVEL"]["cells"]["anthropic"]["evidence_status"] == "SUPPORTED"
          and rows["GEOCODE_SPECIFICITY"]["cells"]["openai"]["validation_state"] == "invalid"
          and rows["GEOCODE_SPECIFICITY"]["cells"]["openai"]["evidence_status"] == "SUPPORTED")
    ev = lambda n: export.export_value(rows[n], include_unreviewed=True)[0]
    check("29 unreviewed export: SUPPORTED agreement exported (marked UNREVIEWED); INFERRED/AMBIGUOUS/INSUFFICIENT/"
          "CONFLICTING blank", ev("SYSTEM_LEVEL") == "3" and ev("POPULATION_SCOPE") == "" and ev("INTERAGENCY_COORDINATION") == ""
          and ev("ALERT_APPROVAL_PROCESS") == "" and ev("FAILURE_TYPE") == "",
          str({n: ev(n) for n in VARS}))
    check("29b nothing is exported as a value when exporting reviewed values only",
          all(export.export_value(rows[n], include_unreviewed=False)[0] == "" for n in VARS))
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(export.xlsx(cid, include_unreviewed=True)))
    hdr = [c.value for c in wb["Results"][1]]
    check("30 Results sheet has separate 'Evidence status' and 'Validation status' columns",
          "Evidence status" in hdr and "Validation status" in hdr)
    res_rows = {r[0]: dict(zip(hdr, r)) for r in wb["Results"].iter_rows(min_row=2, values_only=True)}
    check("30b Results: per-provider evidence statuses for a two-provider variable",
          res_rows["POPULATION_SCOPE"]["Evidence status"] == "Anthropic API: INFERRED; OpenAI API: INFERRED", res_rows["POPULATION_SCOPE"]["Evidence status"])
    ph = [c.value for c in wb["Provider_Suggestions"][1]]
    check("31 Provider_Suggestions has evidence status, validation status, alternatives, missing evidence",
          {"Evidence status", "Validation status", "Alternative values", "Missing evidence"} <= set(ph))
    ps = [dict(zip(ph, r)) for r in wb["Provider_Suggestions"].iter_rows(min_row=2, values_only=True)]
    amb = [p for p in ps if p["Variable"] == "INTERAGENCY_COORDINATION"]
    check("31b Provider_Suggestions rows: AMBIGUOUS with its alternative for both providers",
          len(amb) == 2 and all(p["Evidence status"] == "AMBIGUOUS" and p["Alternative values"].startswith("2 [") for p in amb))
    case_row = [c.value for c in wb["Case_Row"][1]]
    check("31c Case_Row (workbook-aligned) layout unchanged: one column per workbook header",
          len(case_row) == len(schema["fields"]))
    out = agreement.bulk_confirm(cid, ["SYSTEM_LEVEL", "POPULATION_SCOPE", "INTERAGENCY_COORDINATION"], "coder1")
    check("32 bulk confirmation writes only the SUPPORTED agreement; INFERRED/AMBIGUOUS skipped with reasons",
          [c["variable"] for c in out["confirmed"]] == ["SYSTEM_LEVEL"]
          and {s["variable"] for s in out["skipped"]} == {"POPULATION_SCOPE", "INTERAGENCY_COORDINATION"}, str(out)[:300])
    server.api_review(type("H", (), {"user": "coder1"})(), str(cid), {"variable": "POPULATION_SCOPE", "action": "edit",
                                                                       "value": "3", "reason": "county AAR"})
    coding.run_coding_plan(case, settings, [(ClaudeLike(), "independent"), (OpenAILike(), "independent")], None,
                           lambda *a: None, None, VARS, mode="dual_independent")
    rv = {r["variable"]: (r["value"], r["action"]) for r in db.q("SELECT * FROM reviews WHERE case_id=?", (cid,))}
    check("33 human-final values stay separate and unchanged by re-analysis",
          rv.get("POPULATION_SCOPE") == ("3", "edited") and rv.get("SYSTEM_LEVEL") == ("3", "accepted"), str(rv))
    check("33b the model's INFERRED suggestion is still stored separately from the human value",
          row("POPULATION_SCOPE", "anthropic")["value"] == "2" and row("POPULATION_SCOPE", "anthropic")["evidence_status"] == "INFERRED")

    print("\n[5] Results stored before evidence statuses (legacy) and migration")
    sid = db.insert("suggestions", {"case_id": cid, "run_id": None, "variable": "POLICY_CHANGE_LEVEL", "value": "2",
                                    "status": "suggested", "rationale": "old", "evidence_json": "[]", "counter_json": "[]",
                                    "unresolved": "", "validation_json": "{}", "raw_json": "{}", "basis": "model",
                                    "provider": "anthropic", "created_at": time.time()})
    lr = coding._load_row(dict(db.q1("SELECT * FROM suggestions WHERE id=?", (sid,))))
    check("34 legacy row: evidence status 'not recorded', validation status derived at read time ('valid')",
          lr["evidence_status"] is None and not lr["evidence_recorded"] and lr["validation_state"] == "valid"
          and not lr["evidence_review_reason"])
    check("34b legacy row not rewritten in the database",
          db.q1("SELECT evidence_status, validation_status FROM suggestions WHERE id=?", (sid,)) ==
          {"evidence_status": None, "validation_status": None})
    check("34c export text for a legacy row says 'not recorded'", export.evidence_status_text(lr) == "not recorded")
    c2 = sqlite3.connect(str(TMP / "data" / "wfd.sqlite3")) if (TMP / "data" / "wfd.sqlite3").exists() else None
    if c2 is None:
        dbs = list((TMP / "data").glob("*.sqlite*")) + list((TMP / "data").glob("*.db"))
        c2 = sqlite3.connect(str([p for p in dbs if p.suffix in (".sqlite3", ".sqlite", ".db")][0]))
    again = migrations.migrate(c2)
    cols = {r[1] for r in c2.execute("PRAGMA table_info(suggestions)")}
    mig = c2.execute("SELECT status FROM schema_migrations WHERE id=?", (migrations.MIGRATION_ID_3,)).fetchone()
    check("35 migration is additive and repeatable (second run changes nothing; columns present; recorded)",
          again == [] and {"evidence_status", "validation_status", "alternatives_json", "missing_evidence"} <= cols
          and mig and mig[0] == "applied", str(again))
    n_before = c2.execute("SELECT COUNT(*) FROM suggestions").fetchone()[0]
    migrations.migrate(c2)
    check("35b migration is non-destructive (row count unchanged)", c2.execute("SELECT COUNT(*) FROM suggestions").fetchone()[0] == n_before)
    c2.close()

    print("\n[6] Review UI text")
    js = (ROOT / "web" / "app.js").read_text()
    check("36 review UI labels evidence status and validation status separately (both languages)",
          all(s in js for s in ("Evidence status", "Validation status", "证据状态", "验证状态", "Inferred", "推断",
                                "agreement never upgrades an evidence status", "not recorded")))
    check("37 no live or paid API call was attempted", not NET, str(NET))
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED:", *FAIL, sep="\n  ")
        sys.exit(1)


if __name__ == "__main__":
    main()
