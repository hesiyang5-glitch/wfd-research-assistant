"""Missing-value audit (D-039): blank vs -9 vs N/A vs unknown vs insufficient evidence, per WFD variable.

Run:  python3 -m tools.missingness_audit            (writes docs/missingness/missingness_audit.{csv,json})

Facts are computed from the authoritative inputs (codebook v1.3 variable text and workbook v1.7 data) and from the
current code (schema loader, validator, prompt rules). Hand-written notes below QUOTE the codebook and record what the
current materials leave open; they never decide an open rule. Open items carry a PI decision id (PI-M1 ...) that is
explained in docs/missingness/PI_DECISIONS_missingness.md. Historical workbook entries are evidence of past practice,
not authority where they conflict with the codebook.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CODEBOOK = ROOT / "reference" / "CODEBOOK_v1.3_variables.txt"
WORKBOOK = ROOT / "reference" / "MASTER_WFD_Pilot_Workbook_v1.7.xlsx"
OUT_DIR = ROOT / "docs" / "missingness"
COLUMNS = ["variable", "minus9_allowed", "explicit_meaning", "blank_meaning", "na_rule", "current_implementation",
           "conflict_ambiguity", "proposed_implementation", "pi_decision_required", "pi_decision_ids",
           "type", "field_class", "workbook_rows", "workbook_minus9_rows", "workbook_blank_rows",
           "workbook_placeholder_rows", "workbook_unknown_code_rows", "codebook_ref"]

ABSENCE_RE = re.compile(r"unknown|not applicable|not available|not discussed|not mentioned|none documented|none reported|"
                        r"no documentation|indeterminate|insufficient evidence|no data|no documented|no observable|"
                        r"single agency|single system|alert never issued|minimal or no", re.I)
NA_RE = re.compile(r"not applicable|inapplicable", re.I)

# Variable-specific notes. Quotes are from CODEBOOK v1.3 (reference/ excerpt, identical wording in the .docx).
NOTES: dict[str, dict] = {
    "END_DATE": {
        "explicit": "No -9. 'Required if the failure extended over more than one day.' 'If the failure was momentary (e.g., "
                    "one false alert transmission), END_DATE = EVENT_DATE.'",
        "blank": "Not defined. The codebook does not say what to record when the end of a multi-day failure is not documented.",
        "conflict": "All 50 workbook rows are filled; 29 have END_DATE = EVENT_DATE. Whether coders set END_DATE = EVENT_DATE "
                    "when the end was simply not documented (rather than known to be momentary) cannot be told from the data.",
        "proposed": "No automatic rule. END_DATE = EVENT_DATE needs a judgement that the failure was momentary, so it stays "
                    "a model suggestion with cited evidence; blank when not established. Reversed dates are flagged (implemented).",
        "pi": ["PI-M5"]},
    "INCIDENT_DURATION": {
        "explicit": "No -9. 'Total number of days between EVENT_DATE and END_DATE.' Calculation: (END_DATE – EVENT_DATE) + 1.",
        "blank": "Not defined. Follows from the calculation: it cannot be computed without both dates.",
        "conflict": "3 workbook rows (20170212-CA01, 20250107-CA02, 20250109-CA01) equal END_DATE – EVENT_DATE without the "
                    "'+ 1' of the codebook calculation.",
        "proposed": "Implemented: derived only from both dates; blank (never -9) when a date is missing; blank + flag when "
                    "END_DATE is before EVENT_DATE; human-final value that differs from the calculation is flagged. "
                    "Correcting the 3 historical rows is a PI/data-manager decision.",
        "pi": ["PI-M6"]},
    "TRANSMISSION_LATENCY": {
        "explicit": "'Use -9 if unknown or inapplicable' — one code for two different situations.",
        "na": "-9 also covers 'inapplicable' (codebook wording). The codebook does not say when latency is inapplicable "
              "(e.g. nonuse cases where no alert was authorized).",
        "conflict": "42 of 50 workbook rows are -9; several rows hold text instead of minutes ('~ 2 Minutes', '< 1 Minute', "
                    "'Near real-time automated alert', '2 minutes 47 seconds cancellation; ...'). -9 cannot be read as "
                    "'unknown' vs 'not applicable' afterwards.",
        "proposed": "Keep -9 as defined. The tool accepts -9 only with a cited passage indicating the information is unknown "
                    "or inapplicable; when nothing is found it leaves the value blank (PI-M1). Prompt now quotes "
                    "'unknown or inapplicable' (was a generic 'unknown') for schemas loaded after this change.",
        "pi": ["PI-M1", "PI-M2"]},
    "DELIVERY_COVERAGE": {
        "explicit": "'-9 = Unknown'. Values given as percentage bands (0–25 / 26–75 / 76–100) plus 'If exact figure is "
                    "provided ... add the specific number.'",
        "na": "Not defined (e.g. nonuse cases where no alert was sent).",
        "conflict": "35 of 50 workbook rows are -9; others mix band labels ('76-100', '0 - 25'), exact numbers (19, 13.5) and "
                    "text ('Low / 0–25% for BUFFALERT; WEA = 0'). Band-vs-number already open (K schema list).",
        "proposed": "Keep -9 = Unknown as defined; blank when not established (PI-M1). Not-applicable handling and the "
                    "band/number question need a PI decision.",
        "pi": ["PI-M1", "PI-M2", "PI-M9"]},
    "POPULATION_AFFECTED_ESTIMATE": {
        "explicit": "'Numeric (integer) or range if uncertain (e.g., 500–700).' 'Use -9 if unknown.'",
        "conflict": "29 of 50 workbook rows are -9; others include approximations ('~ 100,000') and annotated text. One "
                    "coder note reads '... use -9 if requiring directly exposed count' and another '... / -9' — the team "
                    "itself is unsure whether a broad population figure or -9 applies when the directly impacted count "
                    "is unknown.",
        "proposed": "Keep -9 = unknown as defined; blank when not established (PI-M1). Whether a jurisdiction population may "
                    "stand in for 'individuals directly impacted' is a PI decision.",
        "pi": ["PI-M1", "PI-M10"]},
    "HARM_LOSS_INDICATORS": {
        "explicit": "'-9 = Unknown / not applicable.' 'Numeric estimates (e.g., fatalities, injuries, property losses in USD).' "
                    "Definition says 'Quantitative or qualitative evidence'; example '3 fatalities'. 'Record only when failure "
                    "plausibly contributed to the outcome, as confirmed by official investigations or credible sources.'",
        "na": "-9 covers both unknown and not applicable.",
        "conflict": "Workbook: -9 ×17, 'N/A' ×9, '-' ×1, '0' ×1, and many text entries listing hazard-wide totals (fatalities, "
                    "damage). The codebook asks for harm linked to the failure, while most entries are hazard totals; 'N/A' "
                    "is used although the codebook folds N/A into -9. The tool types this variable as numeric, so text "
                    "such as '3 fatalities' (the codebook's own example) fails validation.",
        "proposed": "Keep -9 as defined (one code for unknown / not applicable). Do not convert 'N/A' to -9 automatically. "
                    "Type (numeric vs text) and hazard-total vs attributable harm need a PI decision.",
        "pi": ["PI-M1", "PI-M2", "PI-M11"]},
    "MESSAGE_DISSEMINATION_TIME": {
        "explicit": "'-9 = Unknown or not documented.' 'Where precise timing is unavailable, use best-supported estimates "
                    "from delivery logs, carrier reports, or after-action documentation.'",
        "conflict": "49 of 50 workbook rows are -9. 'Not documented' is the codebook's own wording, which suggests the team "
                    "codes -9 when the sources are silent — but the tool cannot know that all sources were searched.",
        "proposed": "Keep -9 as defined. Whether the assistant may suggest -9 = 'not documented' from silence in the "
                    "retrieved passages is PI-M1 (currently: blank unless a passage indicates it).",
        "pi": ["PI-M1"]},
    "SOURCE_COUNT_PRIMARY": {
        "explicit": "'Numeric (integer)' and '-9 = Unknown'.",
        "conflict": "Workbook cells hold a count plus source names ('2 - AAR and Everbridge Press Release'), and one '.'.",
        "proposed": "No change: the tool derives the count from the included sources, so -9 is never needed. Cell format "
                    "(count only vs count + names) is outside this audit.",
        "pi": []},
    "SOURCE_COUNT_SECONDARY": {
        "explicit": "'Numeric (integer)' and '-9 = Unknown'.",
        "conflict": "Workbook cells hold a count plus source names.",
        "proposed": "No change (derived count; -9 never needed).", "pi": []},
    "GEOCODE_SPECIFICITY": {
        "explicit": "'0 = Unknown' is a codebook code (no -9). LATITUDE / LONGITUDE: 'When unavailable, leave blank and flag "
                    "GEOCODE_SPECIFICITY = 0.'",
        "conflict": "Workbook: one row -9 (20210817-NC01, which has coordinates); 6 rows with blank or '-' coordinates are "
                    "coded 3, 1, 1, 1, 0, 3 — only one follows the codebook's '= 0' rule.",
        "proposed": "Implemented: -9 rejected; human-final blank LAT/LONG with GEOCODE_SPECIFICITY ≠ 0 is flagged for review "
                    "(not changed). Recoding historical rows: PI-M3.",
        "pi": ["PI-M3"]},
    "LAT/LONG": {
        "explicit": "No -9. 'When unavailable, leave blank and flag GEOCODE_SPECIFICITY = 0.'",
        "blank": "Explicit: blank = coordinates unavailable.",
        "conflict": "Workbook uses '-' in 4 rows and blank in 2.",
        "proposed": "Implemented: a '-' placeholder is treated as blank; cross-check with GEOCODE_SPECIFICITY on human-final "
                    "values.", "pi": ["PI-M3"]},
    "CITY_OR_TOWN": {
        "explicit": "No -9. 'If the failure affected a broad rural area, list the nearest identifiable locality or leave blank "
                    "and include descriptive information under VICINITY.'",
        "blank": "Explicit: blank allowed for broad rural areas (with VICINITY filled).",
        "conflict": "Workbook uses '-' in 6 rows and 'Statewide' in 2.",
        "proposed": "Implemented: '-' treated as blank. Whether 'Statewide' is an acceptable entry: PI-M3.", "pi": ["PI-M3"]},
    "COUNTY_OR_PARISH": {
        "explicit": "No -9. 'For multi-county events, list up to three primary counties ...; if more, record \"Multi-county\" "
                    "and specify in LOCATION_DETAILS.'",
        "conflict": "Workbook uses '-' in 4 rows (statewide/national events); no codebook rule for events with no county.",
        "proposed": "'-' treated as blank (implemented). Rule for statewide/national events: PI-M3.", "pi": ["PI-M3"]},
    "STATE_OR_TERRITORY": {
        "conflict": "One workbook row uses a placeholder; no codebook rule for national events (e.g. 'US').",
        "proposed": "'-' treated as blank (implemented); national-event rule: PI-M3.", "pi": ["PI-M3"]},
    "UNCERTAINTY_TYPE": {
        "explicit": "'When UNCERTAINTY_FLAG = 1, the case must also specify UNCERTAINTY_TYPE.' Codes include UF-D = Data "
                    "Insufficient.",
        "blank": "Implied (not stated) for UNCERTAINTY_FLAG = 0.",
        "na": "Implied: not applicable when UNCERTAINTY_FLAG = 0 (not stated explicitly).",
        "conflict": "3 workbook rows have UNCERTAINTY_FLAG = 1 with UNCERTAINTY_TYPE blank (20210817-NC01, 20260123-MS01, "
                    "20160623-WV01) — contrary to the codebook.",
        "proposed": "Implemented: human-final UNCERTAINTY_FLAG = 1 with a blank UNCERTAINTY_TYPE is flagged for review. "
                    "Blank for FLAG = 0 is the natural reading but not written: PI-M7.",
        "pi": ["PI-M7"]},
    "RELATED_ID": {
        "blank": "Implied by RELATED_EVENT_FLAG = 0 ('No known related event'); not stated.", "pi": []},
    "ACCESSIBILITY_ATTRIBUTES": {
        "explicit": "Two absence codes: '0 = Not mentioned' and '3 = Unknown / no data'. No -9.",
        "conflict": "The difference between 'not mentioned' and 'unknown / no data' is not defined. Workbook: 0 ×24, 3 ×7, "
                    "-9 ×1.",
        "proposed": "No automatic choice. -9 rejected (implemented). Distinguishing 0 vs 3: PI-M4.", "pi": ["PI-M3", "PI-M4"]},
    "ALERT_CORRECTION_OR_UPDATE": {
        "explicit": "'4 = Not applicable (alert never issued)'. No -9.",
        "na": "Explicit: code 4 when no alert was issued.",
        "conflict": "Workbook: -9 ×3; code 4 also appears with SUCCESS_NONUSE_PARTIALUSE = 2 (an alert WAS issued) ×2; one "
                    "nonuse row uses 0. Whether 4 applies when one system was not used but another alert was issued is "
                    "not defined.",
        "proposed": "-9 rejected (implemented). Cross-check with SUCCESS_NONUSE_PARTIALUSE is NOT implemented (ambiguous "
                    "for partial/multi-system cases): PI-M8.", "pi": ["PI-M3", "PI-M8"]},
    "REDUNDANCY_AND_CHANNEL_BEHAVIOR": {
        "explicit": "'3 = Not applicable (single system jurisdiction)'. No -9.", "na": "Explicit: code 3.",
        "proposed": "-9 rejected (implemented); code 3 suggested only with evidence that the jurisdiction has a single system.",
        "pi": ["PI-M3"]},
    "INTERAGENCY_COORDINATION": {
        "explicit": "'0 = Not applicable (single agency)'. No -9.", "na": "Explicit: code 0.",
        "conflict": "0 means 'single agency', not 'unknown'; the workbook's 15 zeros cannot be checked for that meaning.",
        "proposed": "No change: 0 needs evidence that a single agency was involved; blank when coordination is "
                    "undocumented (PI-M4).", "pi": ["PI-M4"]},
    "PERCEIVED_TIMELINESS": {
        "explicit": "'3 = Indeterminate / insufficient evidence' — the codebook's own code for insufficient evidence.",
        "conflict": "Conflicts with the tool's 'blank by default' rule: for a human coder, 'insufficient evidence' is code 3; "
                    "for the assistant, insufficient evidence in the retrieved passages leaves the value blank. Workbook: "
                    "3 ×18.",
        "proposed": "Not changed: whether the assistant should suggest 3 when its passages are silent: PI-M4.",
        "pi": ["PI-M4"]},
    "PERCEIVED_MESSAGE_CLARITY": {
        "explicit": "'3 = Indeterminate / insufficient evidence'.",
        "conflict": "Same as PERCEIVED_TIMELINESS.", "proposed": "Not changed: PI-M4.", "pi": ["PI-M4"]},
    "TRAINING_AND_PROCEDURAL_CONTEXT": {
        "explicit": "'0 = Not discussed in available sources'.",
        "conflict": "Code 0 records absence of discussion. The assistant only sees retrieved passages, not all available "
                    "sources, and cannot cite a passage for absence, so it currently leaves the value blank. Workbook 0 ×23.",
        "proposed": "Not changed: PI-M4.", "pi": ["PI-M4"]},
    "MESSAGE_RECEPTION_DOCUMENTATION": {
        "explicit": "'5 = No documentation available' (codes start at 2; code 1 undefined — existing schema issue).",
        "proposed": "Not changed: PI-M4.", "pi": ["PI-M4"]},
    "MESSAGE_ARCHIVAL_STATUS": {"explicit": "'0 = Not available'.", "proposed": "Not changed: PI-M4.", "pi": ["PI-M4"]},
    "COMMUNITY_FEEDBACK_MECHANISM": {"explicit": "'0 = None documented'.", "proposed": "Not changed: PI-M4.", "pi": ["PI-M4"]},
    "REPORTED_OUTCOMES": {"explicit": "'7 = None reported / unclear' — one code for 'none' and 'unclear'.",
                          "proposed": "Not changed: PI-M4.", "pi": ["PI-M4"]},
    "POLICY_OR_ADMINISTRATIVE_ACTIONS": {"explicit": "'7 = None documented'.", "proposed": "Not changed: PI-M4.",
                                         "pi": ["PI-M4"]},
    "EQUITY_IMPACT": {"explicit": "'0 = No documented disproportionate impact'.", "proposed": "Not changed: PI-M4.",
                      "pi": ["PI-M4"]},
    "TRUST_AND_LEGITIMACY_IMPACT": {"explicit": "'0 = No documented impact'. No -9.", "proposed": "-9 rejected "
                                    "(implemented); 0 vs blank: PI-M4.", "pi": ["PI-M3", "PI-M4"]},
    "FAILURE_SEVERITY (Material Impact)": {"explicit": "'0 = No material impact documented'.",
                                           "proposed": "Not changed: PI-M4.", "pi": ["PI-M4"]},
    "FAILURE_SEVERITY (Public Perception)": {
        "explicit": "'0 = Minimal attention or concern' (an observed level, not a missing value). Codes 0–3.",
        "conflict": "Workbook has one value 4, which the codebook does not define for this variable (existing schema issue).",
        "proposed": "No missing-value change.", "pi": []},
    "MEDIA_FRAMING_AND_PUBLIC_RESPONSE": {"explicit": "'5 = Minimal or no media coverage'.", "proposed": "Not changed: "
                                          "PI-M4.", "pi": ["PI-M4"]},
    "POPULATION_RESPONSE_OBSERVED": {"explicit": "'6 = No observable response'.", "proposed": "Not changed: PI-M4.",
                                     "pi": ["PI-M4"]},
    "COMMUNICATION_ACCESS_MODE": {"explicit": "'6 = None / limited access documented'.", "proposed": "Not changed: PI-M4.",
                                  "pi": ["PI-M4"]},
}
MSG_CHAR = {
    "explicit": "No -9 or N/A defined for MESSAGE_CHARACTERISTICS subfields.",
    "conflict": "Workbook uses -9 (and 'N/A' / 'None' in some rows) for these subfields, mostly where the message text "
                "was not available or no alert was sent (LENGTH: -9 ×35). Nonuse cases have no message to describe.",
    "proposed": "Implemented: -9 rejected (it was previously accepted as the number -9 for LENGTH and as text for the open "
                "lists). Whether nonuse cases should be blank or a defined N/A value: PI-M8; recoding history: PI-M3.",
    "pi": ["PI-M3", "PI-M8"]}


def block_text() -> dict[str, str]:
    from app.schema_loader import _split_blocks, norm
    out = {}
    for _sec, raw, lines, _ln in _split_blocks(CODEBOOK.read_text()):
        out[norm(raw)] = "\n".join(lines)
    return out


def main(write=True) -> list[dict]:
    from app.schema_loader import build_from_files, norm, read_workbook
    s = build_from_files(str(CODEBOOK), str(WORKBOOK))
    _t, _h, rows, _sheets = read_workbook(str(WORKBOOK))
    blocks = block_text()
    out = []
    for f in s["fields"]:
        name = f["name"]
        col = f["position"] - 1
        vals = [(str(r[col]).strip() if col < len(r) and r[col] not in (None, "") else "") for r in rows]
        minus9 = sum(1 for v in vals for p in re.split(r"[;,]", v) if re.fullmatch(r"\s*-9(\.0+)?\s*", p))
        blank = sum(1 for v in vals if not v)
        placeholder = sum(1 for v in vals if v.upper() in ("N/A", "NA", "-", "–", "—", "NONE"))
        absence_codes = [c for c in f.get("codes", []) if ABSENCE_RE.search(c["label"])]
        unknown_rows = sum(1 for v in vals for p in re.split(r"[;,]", v)
                           if p.strip().removesuffix(".0") in {c["code"] for c in absence_codes})
        allowed = "-9" in f.get("missing_codes", [])
        cls = f.get("field_class")
        blk = blocks.get(norm(f.get("codebook_name") or ""), "") or ""
        note = dict(NOTES.get(name) or (MSG_CHAR if name.startswith("MESSAGE_CHARACTERISTICS_") else {}))

        # --- explicit meaning
        parts = []
        if allowed:
            parts.append(f"-9 = {f['missing_labels'].get('-9', 'unknown')} (codebook)")
        parts += [f"code {c['code']} = {c['label']}" for c in absence_codes]
        explicit = note.get("explicit") or ("; ".join(parts) if parts else "None defined (no -9, N/A or unknown code).")
        # --- blank
        lb = re.search(r"[^.\n]*leave blank[^.\n]*\.?", blk, re.I)
        blank_meaning = note.get("blank") or (f"Explicit: \"{lb.group(0).strip()}\"" if lb else
                                              "Not defined by the codebook. Tool: blank = not established from the "
                                              "supplied evidence, or not yet coded/reviewed (default).")
        # --- N/A
        na_codes = [c for c in f.get("codes", []) if NA_RE.search(c["label"])]
        na = note.get("na") or (
            "; ".join(f"code {c['code']} = {c['label']}" for c in na_codes) if na_codes else
            (f"-9 covers it: '{f['missing_labels'].get('-9')}'" if allowed and NA_RE.search(f["missing_labels"].get("-9", ""))
             else "Not defined."))
        # --- current implementation
        if f.get("rule_missing"):
            cur = "No codebook rule: never suggested; kept blank."
        elif cls in ("admin",):
            cur = "Generated administrative metadata (not a model suggestion)."
        elif cls == "derived":
            cur = ("Derived by the tool from other values/sources; blank (never -9) when it cannot be derived."
                   + (" -9 defined by the codebook but never needed for a derived count." if allowed else ""))
        elif cls == "analyst_note":
            cur = "Analyst note: written by the researcher, not suggested by a model."
        else:
            cur = ("Blank when not established (default). " +
                   ("-9 accepted only as defined here, with a cited passage, a 'confirm' warning, and never mixed with "
                    "other values. " if allowed else
                    "-9 rejected for model suggestions as 'missing_code_not_defined' (also as a number or text, since "
                    "D-039); a researcher's -9 is kept but flagged (PI-M3). ") +
                   ("'N/A' / '-' / 'unknown' written by a model become blank. ") +
                   (f"Absence codes ({', '.join(c['code'] for c in absence_codes)}) need a cited supporting passage like any "
                    f"other code, so silence in the passages yields blank." if absence_codes else ""))
        # --- conflicts
        con = []
        if minus9 and not allowed:
            con.append(f"Workbook uses -9 in {minus9} row(s) but the codebook defines no -9 for this variable.")
        if placeholder:
            con.append(f"Workbook uses 'N/A'/'-'/'None' placeholders in {placeholder} row(s); not defined by the codebook.")
        if note.get("conflict"):
            con.append(note["conflict"])
        pis = list(note.get("pi", []))
        if minus9 and not allowed and "PI-M3" not in pis:
            pis.append("PI-M3")
        if placeholder and not allowed and "PI-M3" not in pis and not note:
            pis.append("PI-M3")
        if absence_codes and not note and cls in ("sourced", "judgment") and "PI-M4" not in pis:
            pis.append("PI-M4")
        proposed = note.get("proposed") or (
            "Implemented: -9 rejected for new suggestions. Historical workbook -9 entries are flagged, not adopted (PI-M3)."
            if minus9 and not allowed else "No change needed.")
        out.append({
            "variable": name, "minus9_allowed": "yes" if allowed else "no", "explicit_meaning": explicit,
            "blank_meaning": blank_meaning, "na_rule": na, "current_implementation": cur,
            "conflict_ambiguity": " ".join(con) or "None found.", "proposed_implementation": proposed,
            "pi_decision_required": "yes" if pis else "no", "pi_decision_ids": ", ".join(pis),
            "type": f["type"], "field_class": cls, "workbook_rows": len(rows), "workbook_minus9_rows": minus9,
            "workbook_blank_rows": blank, "workbook_placeholder_rows": placeholder, "workbook_unknown_code_rows": unknown_rows,
            "codebook_ref": f.get("codebook_ref") or "(no codebook entry)"})
    if write:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        with open(OUT_DIR / "missingness_audit.csv", "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=COLUMNS)
            w.writeheader()
            w.writerows(out)
        meta = {"generated_from": {
            "codebook": CODEBOOK.name, "codebook_sha256": hashlib.sha256(CODEBOOK.read_bytes()).hexdigest()[:16],
            "workbook": WORKBOOK.name, "workbook_sha256": hashlib.sha256(WORKBOOK.read_bytes()).hexdigest()[:16]},
            "columns": COLUMNS, "summary": summary(out), "rows": out}
        (OUT_DIR / "missingness_audit.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False) + "\n")
    return out


def summary(out: list[dict]) -> dict:
    return {"variables": len(out),
            "minus9_defined": [r["variable"] for r in out if r["minus9_allowed"] == "yes"],
            "minus9_in_workbook_not_defined": {r["variable"]: r["workbook_minus9_rows"] for r in out
                                               if r["minus9_allowed"] == "no" and r["workbook_minus9_rows"]},
            "pi_decision_required": sum(1 for r in out if r["pi_decision_required"] == "yes"),
            "pi_decision_ids": dict(Counter(i.strip() for r in out for i in r["pi_decision_ids"].split(",") if i.strip()))}


if __name__ == "__main__":
    rows = main()
    print(json.dumps(summary(rows), indent=1))
