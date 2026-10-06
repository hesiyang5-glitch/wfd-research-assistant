"""Matched-version vs cross-version comparison (D-035 retained, D-036). Run:  python -m tests.test_cross_version

Offline: scripted model stand-ins, no search provider, and a network guard that fails the test on any non-local
connection. Numbered after the owner's request of 2026-10-05 (1–15), plus the two owner choices:
 R1 codebook-version differences are shown but never bulk-confirmed; R2 separate runs with identical versions = matched.
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

TMP = Path(tempfile.mkdtemp(prefix="wfdxv_"))
os.environ["WFD_DATA_DIR"] = str(TMP / "data")
for k in ("ANTHROPIC_API_KEY", "TAVILY_API_KEY", "BRAVE_API_KEY", "OPENAI_API_KEY", "OPENAI_BASE_URL", "WFD_TEST_FIXTURE",
          "WFD_PASSWORD"):
    os.environ.pop(k, None)
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
PASS, FAIL = [], []
NET = []
_real = socket.socket.connect


def _guard(self, addr):
    host = addr[0] if isinstance(addr, tuple) else str(addr)
    if host not in ("127.0.0.1", "localhost", "::1"):
        NET.append(host)
        raise OSError(f"network blocked in tests: {host}")
    return _real(self, addr)


socket.socket.connect = _guard


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS " if cond else "  FAIL ") + name + (f"  — {detail}" if detail and not cond else ""))


SRC1 = ("Hill Country flash flood, Kerr County, Texas, July 4, 2025. Kerr County did not send a CodeRED alert before "
        "the Guadalupe River rose; the county's local alerting system was not activated in time. ") * 6
SRC2 = ("A state review of the July 4, 2025 Hill Country flash flood found that Wireless Emergency Alerts reached some "
        "phones while the county's own CodeRED system stayed silent. ") * 6
PX = re.compile(r"^\[(S\d+-P\d+)\] \(source[^\n]*\)\n([^\n]+)", re.M)


class Model:
    supports_schema = False
    CALLS: list = []

    def __init__(self, provider, model, policy):
        self.provider, self.model, self.policy = provider, model, policy

    def generation_settings(self):
        return {"stand_in": self.provider}

    def complete(self, system, user, max_tokens=4000):
        Model.CALLS.append(self.provider)
        names = [l.split("### ")[1].split("  (")[0] for l in user.splitlines() if l.startswith("### ")]
        ps = PX.findall(user)
        res = []
        for n in names:
            spec = self.policy.get(n)
            if spec is None or not ps:
                res.append({"variable": n, "value": "", "status": "insufficient_evidence", "evidence_status": "INSUFFICIENT", "evidence": []})
                continue
            spec = spec if isinstance(spec, dict) else {"value": spec}
            pid, text = ps[0]
            q = "this sentence is not in the passage" if spec.get("fake_quote") else text.strip()[:60]
            res.append({"variable": n, "value": spec["value"], "status": "suggested", "evidence_status": "SUPPORTED", "rationale": "r", "unresolved": "",
                        "evidence": [{"id": pid, "quote": q, "stance": "supports"}]})
        return {"text": json.dumps({"results": res}), "input_tokens": 900, "output_tokens": 150, "stop_reason": "end_turn"}


def main():
    from app import agreement, coding, db, export, research, server
    from app.config import DEFAULT_SETTINGS
    db.conn()
    server.bootstrap_schema()
    schema = coding.active_schema()

    class H:
        user = "coder1"

    def new_case(label):
        st = {**DEFAULT_SETTINGS, "max_search_rounds": 0, "budget_usd": 50, "openai_budget_usd": 50}
        cid = db.insert("cases", {"name": "Hill Country flash flood", "location": "Kerr County, Texas", "date_text": "July 4, 2025",
                                  "details": label, "known_links": "", "aliases": "", "schema_version_id": schema["id"],
                                  "status": "new", "identity_json": "{}", "settings_json": json.dumps(st),
                                  "created_at": time.time(), "updated_at": time.time()})
        research.ingest_manual(cid, "text", {"title": "County statement", "text": SRC1})
        return cid, st

    case = lambda cid: db.q1("SELECT * FROM cases WHERE id=?", (cid,))
    VARS = ["SYSTEM_LEVEL", "FAILURE_TYPE", "ALERT_APPROVAL_PROCESS", "POPULATION_SCOPE", "SUMMARY"]
    A = {"SYSTEM_LEVEL": "3", "FAILURE_TYPE": "6", "ALERT_APPROVAL_PROCESS": {"value": "1", "fake_quote": True},
         "SUMMARY": "Kerr County did not send a CodeRED alert."}
    O = {"SYSTEM_LEVEL": "3", "FAILURE_TYPE": "2", "ALERT_APPROVAL_PROCESS": "1",
         "SUMMARY": "Kerr County did not send a CodeRED alert."}

    def run(cid, st, provider, policy, mode):
        m = Model(provider, "claude-sonnet-5-5" if provider == "anthropic" else "gpt-6.1-sol", policy)
        return coding.run_coding_plan(case(cid), st, [(m, "independent")], None, lambda *a: None, None, VARS, mode=mode)

    def ag(cid):
        return agreement.case_assessments(cid)

    print("\n[1] Classification")
    cM, sM = new_case("matched")
    run(cM, sM, "anthropic", A, "anthropic_only")
    run(cM, sM, "openai", O, "openai_only")
    aM = ag(cM)["SYSTEM_LEVEL"]
    check("1 matched-version agreement is classified as such (R2: separate runs, identical versions)",
          aM["status"] == "eligible" and aM["comparison_class"] == "matched_version" and not aM["differences"]
          and aM["label"] == "Independent agreement — matched analysis version", str(aM)[:300])

    cX, sX = new_case("cross")
    run(cX, sX, "anthropic", A, "anthropic_only")
    research.ingest_manual(cX, "text", {"title": "State review", "text": SRC2})
    n0 = len(Model.CALLS)
    run(cX, sX, "openai", {**O, "FAILURE_TYPE": "6"}, "openai_only")
    aX = ag(cX)
    check("2 cross-version agreement is classified as such", aX["SYSTEM_LEVEL"]["status"] == "eligible_cross_version"
          and aX["SYSTEM_LEVEL"]["comparison_class"] == "cross_version"
          and "evidence version" in aX["SYSTEM_LEVEL"]["differences"]
          and aX["SYSTEM_LEVEL"]["label"] == "Cross-version agreement — review version differences", str(aX["SYSTEM_LEVEL"])[:300])
    cY, sY = new_case("cross disagreement")
    run(cY, sY, "anthropic", A, "anthropic_only")
    research.ingest_manual(cY, "text", {"title": "State review", "text": SRC2})
    run(cY, sY, "openai", O, "openai_only")
    aY = ag(cY)["FAILURE_TYPE"]
    check("3 cross-version disagreement is classified as such", aY["status"] == "cross_version_disagreement"
          and not aY["eligible"] and aY["label"] == "Cross-version disagreement — model and input differences may both contribute")
    rowsX = {r["name"]: r for r in export.case_results(cX)["rows"]}
    cmp = rowsX["SYSTEM_LEVEL"]["comparison"]
    check("4 cross-version results remain comparable under D-035 (shown side by side with a comparison)",
          cmp and cmp["kind"] == "cross_version" and cmp["same_value"]
          and rowsX["SYSTEM_LEVEL"]["cells"]["anthropic"]["value"] == "3" and rowsX["SYSTEM_LEVEL"]["cells"]["openai"]["value"] == "3"
          and "Same suggested value, different analysis versions" in cmp.get("note_kind", ""), str(cmp)[:400])
    summ = server.api_bulk_agreements(H(), str(cX))
    itX = {x["variable"]: x for x in summ["eligible"]}
    check("5 cross-version agreement remains eligible for bulk confirmation (listed, marked cross-version)",
          "SYSTEM_LEVEL" in itX and itX["SYSTEM_LEVEL"]["cross_version"] and itX["SYSTEM_LEVEL"]["differences"])
    try:
        server.api_bulk_confirm(H(), str(cX), {"variables": ["SYSTEM_LEVEL"], "confirmed": True})
        check("6 confirming a cross-version result without acknowledging the warning is refused", False)
    except server.ApiError as e:
        check("6 confirming a cross-version result without acknowledging the warning is refused",
              "acknowledged" in str(e) and not db.q1("SELECT 1 x FROM reviews WHERE case_id=? AND variable='SYSTEM_LEVEL'", (cX,)))
    check("6b the dialog data carries the exact warning text", summ["cross_version_warning"].startswith(
        "These model results were generated using different evidence, codebook, prompt, or analysis versions."))
    other_before = json.dumps(db.q("SELECT * FROM suggestions WHERE case_id=? ORDER BY id", (cX,)), default=str)
    server.api_review(H(), str(cX), {"variable": "SUMMARY", "action": "edit", "value": "My own summary", "reason": "AAR"})
    rconf = server.api_bulk_confirm(H(), str(cX), {"variables": ["SYSTEM_LEVEL"], "confirmed": True,
                                                   "acknowledged_cross_version": True})
    au = db.q1("SELECT * FROM bulk_confirmations WHERE case_id=? AND variable='SYSTEM_LEVEL'", (cX,))
    rv = db.q1("SELECT * FROM reviews WHERE case_id=? AND variable='SYSTEM_LEVEL'", (cX,))
    check("7 user acknowledgement is recorded with the warning, class, differences, versions, selection, user and time",
          rconf["confirmed"] and au["acknowledged"] == 1 and au["warning_shown"] and au["comparison_class"] == "cross_version"
          and "evidence version" in json.loads(au["differences_json"]) and json.loads(au["selected_json"]) == ["SYSTEM_LEVEL"]
          and au["reviewer"] == "coder1" and au["at"] and json.loads(au["claude_versions_json"])["evidence_snapshot_id"]
          and au["claude_run_id"] and au["openai_run_id"] and au["method"] == "bulk_separate_run_agreement", str(au)[:400])
    check("7b the Human final reason says CROSS-VERSION and that the warning was acknowledged",
          "CROSS-VERSION" in rv["reason"] and "acknowledged" in rv["reason"])
    vd = server.api_version_diff(H(), str(cX), {"variable": ["SYSTEM_LEVEL"]})
    new_src = db.q1("SELECT MAX(id) m FROM sources WHERE case_id=?", (cX,))["m"]
    new_pass = {r["id"] for r in db.q("SELECT id FROM passages WHERE source_id=?", (new_src,))}
    check("8 version differences are displayed accurately (dimensions, versions, added source and passages)",
          "evidence version" in vd["differences"] and vd["claude"]["evidence_snapshot_id"] != vd["openai"]["evidence_snapshot_id"]
          and vd["sources"]["only_in_openai_version"] == [new_src] and not vd["sources"]["only_in_claude_version"]
          and set(vd["passages"]["only_in_openai_version"]) == new_pass and not vd["passages"]["changed_text"]
          and vd["claude"]["generated_at"] and vd["openai"]["generated_at"], json.dumps(vd)[:400])
    rowsY = {r["name"]: r for r in export.case_results(cY)["rows"]}
    noteY = rowsY["FAILURE_TYPE"]["comparison"].get("note_kind", "")
    check("9 cross-version disagreement is not attributed solely to the provider",
          "Results differ, but the models also used different analysis inputs" in noteY
          and "different analysis inputs" in aY["reason"])
    check("10 cache equivalence is stricter than comparison eligibility: the cross-version pair is comparable, but "
          "OpenAI's request on the new evidence was sent, not taken from cache", len(Model.CALLS) > n0
          and aX["SYSTEM_LEVEL"]["eligible"])
    n1 = len(Model.CALLS)
    run(cX, sX, "anthropic", A, "anthropic_only")
    check("11 different evidence inputs do not produce a cache hit (Claude re-run on the new evidence is sent)",
          len(Model.CALLS) > n1 and Model.CALLS[-1] == "anthropic")
    after = json.dumps([r for r in db.q("SELECT * FROM suggestions WHERE case_id=? ORDER BY id", (cX,))][:len(json.loads(other_before))], default=str)
    check("12 historical results unchanged (new runs only add rows) and Human final unchanged",
          after == other_before and db.q1("SELECT value FROM reviews WHERE case_id=? AND variable='SUMMARY'", (cX,))["value"] == "My own summary"
          and db.q1("SELECT value FROM reviews WHERE case_id=? AND variable='SYSTEM_LEVEL'", (cX,))["value"] == "3")
    aX2 = ag(cX)
    check("13 invalid or insufficient results remain ineligible (cross-version too)",
          not aX2["ALERT_APPROVAL_PROCESS"]["eligible"] and not aX2["POPULATION_SCOPE"]["eligible"]
          and not aX2["SUMMARY"]["eligible"])
    cR, sR = new_case("cross-model")
    coding.ALLOW_CROSS_MODEL_REVIEW = True
    coding.run_coding_plan(case(cR), sR, [(Model("anthropic", "claude-sonnet-5-5", A), "independent"),
                                          (Model("openai", "gpt-6.1-sol", O), "reviewer")], None, lambda *a: None, None,
                           VARS, mode="anthropic_primary_openai_review")
    coding.ALLOW_CROSS_MODEL_REVIEW = False
    check("14 reviewer/cross-model outputs are not treated as independent agreement",
          ag(cR)["SYSTEM_LEVEL"]["status"] == "cross_model_review" and not ag(cR)["SYSTEM_LEVEL"]["eligible"])
    rid = db.q1("SELECT run_id FROM suggestions WHERE case_id=? AND variable='SYSTEM_LEVEL' AND provider='anthropic' "
                "ORDER BY id DESC", (cY,))["run_id"]
    sv = db.q1("SELECT schema_version_id FROM runs WHERE id=?", (rid,))["schema_version_id"]
    db.update("runs", rid, {"schema_version_id": (sv or 0) + 7})
    aC = ag(cY)["SYSTEM_LEVEL"]
    check("R1 codebook versions differ → shown and compared, but not bulk-confirmable (confirm individually)",
          not aC["eligible"] and "codebook versions differ" in aC["reason"] and "codebook version" in aC["differences"], str(aC)[:300])
    db.update("runs", rid, {"schema_version_id": sv})
    xl = __import__("openpyxl").load_workbook(io.BytesIO(export.xlsx(cX)))
    rh = [c.value for c in xl["Results"][1]]
    res = {r[0].value: [c.value for c in r] for r in xl["Results"].iter_rows(min_row=2)}
    check("export labels the cross-version confirmation", res["SYSTEM_LEVEL"][rh.index("Confirmation method")] ==
          "human-approved cross-version agreement (bulk, D-035)")

    print("\n[2] Browser: cross-version item unticked, warning + acknowledgement, version panel")
    cB, sB = new_case("browser cross")
    run(cB, sB, "anthropic", A, "anthropic_only")
    research.ingest_manual(cB, "text", {"title": "State review", "text": SRC2})
    run(cB, sB, "openai", {**O, "FAILURE_TYPE": "6"}, "openai_only")
    port = 19300 + os.getpid() % 300
    env = {**{k: v for k, v in os.environ.items()}, "WFD_PORT": str(port)}
    srv = subprocess.Popen([sys.executable, "-m", "app.server"], cwd=str(ROOT), env=env, stdout=subprocess.DEVNULL,
                           stderr=subprocess.STDOUT)
    ui = {}
    shots = TMP / "shots"
    shots.mkdir(exist_ok=True)
    try:
        for _ in range(80):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=1)
                break
            except Exception:
                time.sleep(0.25)
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            br = pw.chromium.launch()
            pg = br.new_page(viewport={"width": 1500, "height": 1000})
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(f"http://127.0.0.1:{port}/")
            pg.evaluate("localStorage.setItem('wfd_lang','en')")
            pg.goto(f"http://127.0.0.1:{port}/#/case/{cB}/review")
            pg.reload()
            pg.wait_for_timeout(1500)
            pg.click("#bulkBtn")
            pg.wait_for_selector("#bulkTable", timeout=6000)
            box = pg.locator(".bulkChk[value='SYSTEM_LEVEL']")
            ui["cross_version_unticked_by_default"] = not box.is_checked()
            ui["warning_hidden_until_ticked"] = not pg.is_visible("#xvBox")
            box.check()
            pg.wait_for_timeout(200)
            ui["warning_shown_when_ticked"] = pg.is_visible("#xvBox") and "controlled same-input comparison" in pg.inner_text("#xvBox")
            ui["confirm_disabled_until_acknowledged"] = pg.is_disabled("#bulkOk")
            pg.locator(".modal").screenshot(path=str(shots / "bulk_cross_version_warning.png"))
            pg.check("#xvAck")
            ui["confirm_enabled_after_acknowledgement"] = not pg.is_disabled("#bulkOk")
            pg.click("#bulkOk")
            pg.wait_for_timeout(1500)
            a2 = db.q1("SELECT acknowledged FROM bulk_confirmations WHERE case_id=? AND variable='SYSTEM_LEVEL'", (cB,))
            ui["acknowledgement_recorded_from_browser"] = bool(a2 and a2["acknowledged"] == 1)
            pg.goto(f"http://127.0.0.1:{port}/#/case/{cB}/review")
            pg.reload()
            pg.wait_for_timeout(1500)
            pg.click("tr[data-v='FAILURE_TYPE']")
            pg.wait_for_timeout(600)
            pg.click("#vdBox summary")
            pg.wait_for_timeout(1200)
            vtxt = pg.inner_text("#vdOut")
            ui["version_panel_shows_differences"] = "Differs in" in vtxt and "evidence version" in vtxt and "Evidence version" in vtxt
            pg.locator("#vdBox").screenshot(path=str(shots / "version_difference_panel.png"))
            ui["no_js_errors"] = not errs
            br.close()
    finally:
        srv.terminate()
        srv.wait(10)
    for k, v in ui.items():
        check(f"browser: {k}", bool(v))
    print("  screenshots in", shots)
    check("15 no live or paid API call was attempted", not NET, str(NET))
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED:", *FAIL, sep="\n  ")
        sys.exit(1)


if __name__ == "__main__":
    main()
