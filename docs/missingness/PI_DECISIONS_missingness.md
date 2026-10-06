# Proposed PI decisions — missing values (blank, `-9`, N/A, unknown, insufficient evidence)

Status: **proposal for the research team (Hamilton Bean, Katie Dickinson)**, prepared 2026-10-06 for D-039.
Nothing in this document has been decided. The WFD Coding Assistant keeps its current behaviour on every item below
until the team decides; it does not guess.

Source of facts: `CODEBOOK v1.3` (April 14, 2026; variable text in `reference/CODEBOOK_v1.3_variables.txt`, same wording as
the .docx), `MASTER_WFD_Pilot_Workbook_v1.7.xlsx` (50 cases), and the variable-level table
`docs/missingness/missingness_audit.csv` / `.json` (82 workbook columns; regenerate with `python3 -m tools.missingness_audit`).
Workbook entries are past practice; where they conflict with the codebook they are reported, not treated as authority.

## What the current materials establish (already implemented)

- **`-9` exists only where a variable's own entry defines it.** Codebook v1.3 defines `-9` for exactly 7 variables:
  TRANSMISSION_LATENCY ("unknown or inapplicable"), DELIVERY_COVERAGE ("Unknown"), POPULATION_AFFECTED_ESTIMATE
  ("unknown"), HARM_LOSS_INDICATORS ("Unknown / not applicable"), MESSAGE_DISSEMINATION_TIME ("Unknown or not
  documented"), SOURCE_COUNT_PRIMARY and SOURCE_COUNT_SECONDARY ("Unknown"). The tool now rejects `-9` everywhere else,
  including as the number −9 or as text (before D-039 a numeric field such as MESSAGE_CHARACTERISTICS_LENGTH accepted
  `-9` as a number).
- **Explicit "leave blank" rules:** LATITUDE / LONGITUDE ("When unavailable, leave blank and flag GEOCODE_SPECIFICITY =
  0") and CITY_OR_TOWN ("... or leave blank and include descriptive information under VICINITY"). A `-` or `N/A`
  placeholder written by a model is treated as blank.
- **Explicit consistency rules,** checked on human-final values and shown as review flags (values are never changed):
  UNCERTAINTY_FLAG = 1 requires UNCERTAINTY_TYPE; blank LAT/LONG requires GEOCODE_SPECIFICITY = 0;
  INCIDENT_DURATION = (END_DATE – EVENT_DATE) + 1 (reversed dates are flagged and never derived).

## The general gap

The codebook has **no general missing-data policy**. Appendix II lists "Guidance on handling conflicting reports, missing
data, or evolving investigations" among its planned contents, but that guidance is not written yet. Each decision below
would ideally become part of that appendix.

---

## PI-M1 — What does `-9 = Unknown` mean: "the sources say it is unknown" or "the sources we read do not document it"?

- **Codebook:** "Unknown" (DELIVERY_COVERAGE, SOURCE_COUNT_*), "unknown" (POPULATION_AFFECTED_ESTIMATE), "unknown or
  inapplicable" (TRANSMISSION_LATENCY), "Unknown / not applicable" (HARM_LOSS_INDICATORS), and "Unknown **or not
  documented**" (MESSAGE_DISSEMINATION_TIME).
- **Workbook practice:** `-9` is the usual entry when nothing was found: TRANSMISSION_LATENCY 42/50, DELIVERY_COVERAGE
  35/50, POPULATION_AFFECTED_ESTIMATE 29/50, MESSAGE_DISSEMINATION_TIME 49/50.
- **Current tool:** blank when the retrieved passages do not establish a value. `-9` is accepted only with a cited passage
  that indicates the information is unknown (shown with a "confirm" warning). Reason: the assistant sees a sample of
  passages, not every available source, so silence in its passages is weaker than a coder's full reading.
- **Decision needed:** (a) keep the current rule (blank from the assistant; the researcher enters `-9` after their own
  review), or (b) allow the assistant to suggest `-9` when its passages are silent, always as INSUFFICIENT/needs review,
  or (c) a per-variable rule (e.g. only MESSAGE_DISSEMINATION_TIME, whose wording includes "not documented").

## PI-M2 — Should "unknown" and "not applicable" be separated where one `-9` covers both?

- **Codebook:** TRANSMISSION_LATENCY "unknown or inapplicable"; HARM_LOSS_INDICATORS "Unknown / not applicable". The
  codebook does not say when latency or harm is "not applicable" (for example, nonuse cases where no alert was authorized).
- **Workbook:** HARM_LOSS_INDICATORS uses `N/A` ×9 *and* `-9` ×17, so coders already distinguish them in practice, against
  the codebook. DELIVERY_COVERAGE defines only "Unknown"; nonuse cases have no defined value.
- **Current tool:** follows the codebook literally (one `-9`); a model's "N/A" becomes blank, never `-9`.
- **Decision needed:** keep one code, or define a separate not-applicable value (and for which variables), and whether
  historical `N/A` entries become `-9`, the new value, or blank.

## PI-M3 — Historical `-9` and placeholders where the codebook defines none

`-9` appears in **21** workbook columns whose codebook entry defines no special missing value (rows):
MESSAGE_CHARACTERISTICS_LENGTH 35, ALERT_APPROVAL_PROCESS 9, ALERT_INITIATION_AUTHORITY 7, POLICY_CHANGE_LEVEL 7,
MESSAGE_CHARACTERISTICS_CLARITY_ASSESSED 6, MESSAGE_CHARACTERISTICS_PROTECTIVE_ACTION_PRESENT 5,
MESSAGE_CHARACTERISTICS_EMOTIONAL_TONE 5, MESSAGE_CHARACTERISTICS_LANGUAGE 4, ALERT_CORRECTION_OR_UPDATE 3,
REGULATORY_OR_POLICY_FRAMEWORK 3, ALERT_ORIGINATOR_PLATFORM 2, TRANSMISSION_PATHWAY 2, and 1 each in
GEOCODE_SPECIFICITY, FAILURE_TYPE, FAILURE_SUBTYPE, SUCCESS_NONUSE_PARTIALUSE, REDUNDANCY_AND_CHANNEL_BEHAVIOR,
POPULATION_SCOPE, ACCESSIBILITY_ATTRIBUTES, TRUST_AND_LEGITIMACY_IMPACT, REMEDIAL_ACTION_COMPLETION_STATUS.
Placeholders (`-`, `N/A`, `None`) appear in STATE_OR_TERRITORY, COUNTY_OR_PARISH (4), CITY_OR_TOWN (6), LAT/LONG (4),
MESSAGE_CHARACTERISTICS_* and HARM_LOSS_INDICATORS.

- Two of these variables already have a codebook "unknown" code: GEOCODE_SPECIFICITY "0 = Unknown" and
  ACCESSIBILITY_ATTRIBUTES "3 = Unknown / no data".
- **Current tool:** rejects `-9` for these variables; flags the historical entries on the Schema page; never adds `-9` to
  the allowed values.
- **Decision needed, per variable:** (a) amend the codebook to define `-9` (with its meaning), or (b) recode historical
  entries (to blank, or to an existing code such as GEOCODE_SPECIFICITY 0) — the team decides; the tool will not
  recode workbook data.

## PI-M4 — Codes that record absence of evidence: should the assistant ever suggest them?

Several variables have a code whose meaning is "not documented / not discussed / indeterminate / none":
PERCEIVED_TIMELINESS and PERCEIVED_MESSAGE_CLARITY "3 = Indeterminate / insufficient evidence";
TRAINING_AND_PROCEDURAL_CONTEXT "0 = Not discussed in available sources"; ACCESSIBILITY_ATTRIBUTES "0 = Not mentioned"
and "3 = Unknown / no data"; MESSAGE_RECEPTION_DOCUMENTATION "5 = No documentation available"; MESSAGE_ARCHIVAL_STATUS
"0 = Not available"; COMMUNITY_FEEDBACK_MECHANISM "0 = None documented"; REPORTED_OUTCOMES "7 = None reported / unclear";
POLICY_OR_ADMINISTRATIVE_ACTIONS "7 = None documented"; EQUITY_IMPACT "0 = No documented disproportionate impact";
TRUST_AND_LEGITIMACY_IMPACT "0 = No documented impact"; FAILURE_SEVERITY (Material Impact) "0 = No material impact
documented"; MEDIA_FRAMING_AND_PUBLIC_RESPONSE "5 = Minimal or no media coverage"; POPULATION_RESPONSE_OBSERVED
"6 = No observable response"; COMMUNICATION_ACCESS_MODE "6 = None / limited access documented";
INTERAGENCY_COORDINATION "0 = Not applicable (single agency)".

- For a human coder these codes *are* the answer when the sources are silent (e.g. PERCEIVED_TIMELINESS 3 ×18,
  TRAINING_AND_PROCEDURAL_CONTEXT 0 ×23 in the workbook).
- **Current tool:** every code, including these, needs a cited supporting passage; silence cannot be cited, so the
  assistant leaves the value blank and the researcher chooses the code.
- **Decision needed:** keep (blank + human choice), or let the assistant propose the absence code from silence in its
  passages (always marked INSUFFICIENT / needs review), per variable. Also: ACCESSIBILITY_ATTRIBUTES 0 vs 3 and
  REPORTED_OUTCOMES 7 ("none" and "unclear" in one code) need definitions.

## PI-M5 — END_DATE when the end of the failure is not documented

- **Codebook:** "Required if the failure extended over more than one day." "If the failure was momentary ..., END_DATE =
  EVENT_DATE." Nothing on an undocumented end; no `-9`.
- **Workbook:** all 50 filled; 29 equal EVENT_DATE.
- **Current tool:** model suggestion with cited evidence; blank when not established (no automatic copy of EVENT_DATE).
- **Decision needed:** blank, copy EVENT_DATE with DATE_APPROX = 1, or another rule.

## PI-M6 — INCIDENT_DURATION historical rows and missing END_DATE

- **Codebook:** (END_DATE – EVENT_DATE) + 1.
- **Workbook:** 3 rows (20170212-CA01, 20250107-CA02, 20250109-CA01) equal END_DATE – EVENT_DATE without the "+ 1".
- **Current tool:** derives only from two valid dates; blank when END_DATE is missing; reversed dates flagged; a
  human-final value that differs from the calculation is flagged.
- **Decision needed:** correct the 3 historical rows; confirm blank (not `-9`) when END_DATE is unknown.

## PI-M7 — UNCERTAINTY_TYPE when UNCERTAINTY_FLAG = 0, and the 3 flagged rows without a type

- **Codebook:** "When UNCERTAINTY_FLAG = 1, the case must also specify UNCERTAINTY_TYPE." Blank for flag 0 is implied but
  not written.
- **Workbook:** 20210817-NC01, 20260123-MS01, 20160623-WV01 have flag 1 and no type.
- **Current tool:** flags human-final flag 1 + blank type.
- **Decision needed:** confirm "blank when flag = 0" in the codebook; assign types to the 3 rows.

## PI-M8 — Message and correction variables for nonuse cases (no alert was sent)

- **Codebook:** only ALERT_CORRECTION_OR_UPDATE defines it: "4 = Not applicable (alert never issued)". The
  MESSAGE_CHARACTERISTICS subfields (LENGTH, LANGUAGE, PROTECTIVE_ACTION_PRESENT, EMOTIONAL_TONE, CLARITY_ASSESSED)
  define no value for a message that does not exist.
- **Workbook:** `-9` / `N/A` / `None` in those subfields, including most nonuse rows; ALERT_CORRECTION_OR_UPDATE = 4 also
  appears in 2 rows coded "partial use" (an alert was issued), and one nonuse row uses 0.
- **Current tool:** blank (no `-9`); no cross-check between SUCCESS_NONUSE_PARTIALUSE and ALERT_CORRECTION_OR_UPDATE,
  because "nonuse" may concern one system while another alert was sent.
- **Decision needed:** a defined not-applicable value (or blank) for message subfields in nonuse cases; when code 4
  applies in multi-system cases.

## PI-M9 — DELIVERY_COVERAGE: band or number (affects how "unknown" is read)

- **Codebook:** bands 0–25 / 26–75 / 76–100 and "If exact figure is provided ... add the specific number"; "-9 = Unknown".
- **Workbook:** band labels, exact numbers and text mixed.
- **Decision needed:** one recording format. (Already listed among the schema issues.)

## PI-M10 — POPULATION_AFFECTED_ESTIMATE: jurisdiction population vs directly impacted count

- **Codebook:** "Estimated number of individuals directly impacted by the failure (missed, misinformed, or confused)";
  "Use -9 if unknown."
- **Workbook:** some entries are whole-jurisdiction populations ("30,000,000 (Texas population estimate 2024)"), and two
  coder notes show uncertainty ("use -9 if requiring directly exposed count"; "... / -9").
- **Decision needed:** whether a jurisdiction population may stand in, or `-9` applies when the directly impacted count is
  unknown.

## PI-M11 — HARM_LOSS_INDICATORS: hazard totals vs harm linked to the failure, and its type

- **Codebook:** "Quantitative or qualitative evidence of harm or loss linked to the failure"; "Record only when failure
  plausibly contributed to the outcome"; example "3 fatalities"; "-9 = Unknown / not applicable."
- **Workbook:** mostly hazard-wide totals (fatalities, damage in USD); `N/A` ×9; `-9` ×17.
- **Current tool:** treats the variable as numeric, so text such as "3 fatalities" (the codebook's own example) fails
  validation; `-9` accepted as defined.
- **Decision needed:** text vs number; hazard totals vs attributable harm; when "not applicable" applies.

---

### How to record a decision

For each item: write the decision in the codebook (new version) or in `DECISIONS.md` with the date and who decided. The
tool is then changed in a small, tested step and the audit table is regenerated. Until then the current behaviour stays.
