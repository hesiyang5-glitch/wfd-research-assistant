# Methodology decision memo — END_DATE / INCIDENT_DURATION, FAILURE_TYPE vs 7 = Composite, harm attribution

Status: **read-only audit, prepared 2026-11-13 for the project owner and the PI team (Hamilton Bean, Katie Dickinson).**
**Nothing in this memo is a WFD requirement.** It reports what the current materials say, how the software and past
coding behave, and lists possible decision rules. Every "Recommendation" below is the assistant's suggestion for
discussion — it is not codebook text and is not implemented. Application behaviour is unchanged until decisions are
approved.

Related open items: issue A overlaps PI-M5 (END_DATE when undocumented) and PI-M6 (INCIDENT_DURATION history); issue C
overlaps PI-M11 (HARM_LOSS_INDICATORS type and attribution) in `docs/missingness/PI_DECISIONS_missingness.md`.

## Sources used and limits

| Source | What was used |
|---|---|
| Codebook v1.3 (April 14, 2026), full .docx in the claude.ai Project | variable entries, Single Instance Determination, Uncertainty Flag, appendices list |
| `reference/MASTER_WFD_Pilot_Workbook_v1.7.xlsx` (50 cases) | historical coding of all variables discussed |
| Repository code and docs (`main` a3da11b) | current software behaviour |
| Marshall Fire export from the live site (2026-10-02, `Marshall_Fire_reviewed_1.xlsx`) | **Claude** results for B1 (prompt before evidence statuses) |

**Not available to this audit:** the Claude and OpenAI results for the other benchmark cases (B2 Hawaii false missile
alert, B3 Camp Fire, Texas Hill Country flood) and any OpenAI result for these variables in B1. They are stored in the
live database, which this session cannot reach. Where the memo needs them, the cell says **"not available — export
needed"**; nothing has been inferred. Exporting the four cases' Excel files from the live site (Export → Excel) costs
nothing and would let this memo be completed.

Benchmark hand codes below are the team's past codes, **not ground truth** (TEST_PLAN §4).

---

## A. END_DATE and INCIDENT_DURATION — when does a warning-failure event end?

### Current codebook language
- **EVENT_DATE:** "The date on which the warning failure occurred or became publicly identifiable." "When an event
  extends across multiple days, record the start date and use END_DATE to mark completion."
- **END_DATE:** "The final date on which the failure persisted or its effects were observed." Purpose: "Captures duration
  for failures involving system outages, ongoing misinformation, or delayed public correction." Notes: "Required if the
  failure extended over more than one day." "If the failure was momentary (e.g., one false alert transmission),
  END_DATE = EVENT_DATE."
- **INCIDENT_DURATION:** "Total number of days between EVENT_DATE and END_DATE"; (END_DATE – EVENT_DATE) + 1.
- **Single Instance Determination:** an instance is "delimited by temporal continuity — that is, the time period during
  which the failure occurred or persisted without resolution." A failure that is restored and fails again during a later
  hazard event is a separate instance.
- The table of contents lists an "Extended Incident Flag and Resolution Date", but no such variable is defined.

**What this establishes:** the end point is tied to the **failure**, not to the hazard ("the failure persisted"). It does
**not** say which failure milestone ends it, and "or its effects were observed" is open: effects of the *failure*
(misinformation, uncorrected false alert) or effects of the *event* (losses that continued during the hazard)? No rule
covers a nonuse failure (no alert sent): there is no "last failed alert" to date.

### Current software behaviour
- END_DATE is a date variable suggested by the model only with a cited passage; blank when not established (no copy of
  EVENT_DATE, no `-9`). The prompt adds no END_DATE-specific guidance beyond the codebook text.
- INCIDENT_DURATION is derived only from two valid dates with the codebook formula; blank when END_DATE is missing;
  reversed dates are flagged, never derived (D-039).

### Historical workbook behaviour (50 cases)
- END_DATE = EVENT_DATE in 29 cases; 1 day later in 11; 2–7 days in 7; 38, 47 and 124 days in 3.
- The long durations look like **hazard or programme periods**, not single warning failures: 20180503-HI01 (Kīlauea
  eruption, 124 days), 20191005-CA01 (utility de-energization events, 47 days), 20230223-CA01 (winter storm, 38 days).
- Benchmark cases: B3 Camp Fire END_DATE = EVENT_DATE (1 day) although the workbook summary itself records "full
  containment on November 25, 2018" — i.e. coders did **not** use the hazard end here. B1 Marshall Fire 2 days
  (12-30 → 12-31). B2 Hawaii 1 day. Texas flood 1 day.
- So past practice mixes at least two endpoints (warning-failure day vs hazard/programme period).

### Benchmark behaviour
| Case | Claude | OpenAI |
|---|---|---|
| B1 Marshall Fire | END_DATE **blank** (insufficient evidence). Rationale: evacuation orders and emergency information stopped 2022-01-01, but "the passages do not say that is when a warning failure ended"; notes a reviewer could use 2022-01-01 "if the codebook treats the end of the warning messaging as the end of the event". INCIDENT_DURATION therefore blank. | not available — export needed |
| B2, B3, Texas | not available — export needed | not available — export needed |

### Methodological ambiguity
Candidate endpoints, all defensible from the wording: (1) hazard end (containment, flood recession); (2) end of the
warning failure itself (last day an alert was omitted, wrong or unreachable while still needed); (3) last failed or
erroneous alert; (4) communication-system recovery (outages); (5) last day the failure's *effects* were observed
(misinformation, delayed correction). For nonuse cases (1)–(3) can coincide or diverge widely.

### Possible decision rules
| Rule | END_DATE means | Consequences |
|---|---|---|
| A1 — Failure persistence | The last date on which the documented warning failure was still ongoing (alert still omitted, wrong, unreachable, or uncorrected while the threat or the false alarm was live). | Matches the definition and the Single Instance rule; durations measure failures, not disasters. Needs a source that dates the failure; often only the first day is documented → many blanks (PI-M5). The three long historical rows would need review. |
| A2 — Hazard end | Containment / end of the hazard period. | Easiest to source; but INCIDENT_DURATION then measures the disaster, not the failure, and contradicts "the failure persisted" and the false-alert example. Camp Fire would become 18 days. |
| A3 — Type-specific anchors | Outage → service restored; false/erroneous alert → correction issued; nonuse/partial use → last date protective alerts were needed for the affected population; misinformation → last documented correction. | Most operational and closest to the stated purposes (outages, misinformation, delayed correction). Needs a table in the codebook; coders must classify the failure first. |
| A4 — Effects window | Last date any effect of the failure was observed (incl. public confusion, corrections, hearings?). | Broadest; risks very long, hard-to-compare durations unless "effects" is limited. |

Also to settle (PI-M5): when the end is not documented — blank, or END_DATE = EVENT_DATE with DATE_APPROX = 1.

**Recommendation (assistant's suggestion, not a WFD requirement):** A3, i.e. A1 made operational with type-specific
anchors, with "effects" limited to the failure's own communication effects (misinformation, uncorrected false alert),
never hazard losses; when the anchor date is not documented, leave END_DATE blank with a review flag rather than copying
EVENT_DATE.

### Exact decision needed
1. Which endpoint END_DATE records (A1, A2, A3, A4 or another).
2. If A3: approve an anchor per failure situation (outage, false/erroneous alert, nonuse/partial use, misinformation).
3. What "or its effects were observed" includes (communication effects only, or also hazard effects).
4. Undocumented end: blank or EVENT_DATE + DATE_APPROX = 1 (PI-M5).
5. Whether the 3 long historical rows and the 3 rows missing "+1" (PI-M6) are re-reviewed.

---

## B. FAILURE_TYPE — a specific category or 7 = Other/Composite?

### Current codebook language
- "Primary classification of the warning failure according to its **dominant causal mechanism**."
- "Values (single-select, though multiple secondary codes may be noted)": 1 Technical, 2 Organizational/Process,
  3 Message Design/Content, 4 Geotargeting ("failure to reach affected population"), 5 Timing, 6 Channel
  Selection/Redundancy ("insufficient use of multiple alerting modalities when primary system failed"),
  **7 = "Other/Composite Failure — multi-causal or atypical breakdown not captured above."**
- FAILURE_SUBTYPE: "Optional secondary classification … Multiple values permitted"; code families T (technical),
  O (organizational), M (message), G (geotargeting), C (channel). No family for 5 Timing or 7.
- Single Instance table: "Failure of both WEA and EAS in the same jurisdiction for the same event → Single instance with
  multiple channel failures noted in variable field."
- UNCERTAINTY_TYPE UF-A covers conflicting accounts "whether failure occurred"; "Attribution Ambiguity" covers whether the
  failure "originated in the alerting system, the message design, or audience interpretation."

**What this establishes:** one primary code; secondary mechanisms "may be noted" (the codebook does not say where);
7 covers "multi-causal" cases. **It gives no operational test for "dominant"**, and the categories mix *causes*
(1, 2) with *manifestations* (4, 5, 6), so many cases legitimately fit two or more categories — and "multi-causal"
would then describe most large incidents.

### Current software behaviour
- Single-select categorical; one code required.
- FAILURE_TYPE is treated as a **CAUSAL** variable (its definition says "causal mechanism"): the prompt tells the model
  that when sources give competing explanations it should use CONFLICTING or AMBIGUOUS, cite both sides and "code only
  what the evidence actually establishes (often blank)". Nothing in the prompt defines when 7 applies.

### Historical workbook behaviour
- Codes: 1 ×13, 2 ×10, 6 ×8, 4 ×5, **7 ×5**, 3 ×4, 5 ×1; two cells hold two codes ("1, 2"; "2, 5") despite single-select;
  one `-9`; one cell auto-converted by Excel to a date.
- The five 7s are cases whose subtypes span three to five families (e.g. "M2; G1; T1; O2; C1") or that analysts called
  "composite multi-causal".
- In 14 rows the subtype family differs from the type — e.g. **B3 Camp Fire 6 with subtype G2** (under-alerting,
  geotargeting family); coders appear to use the type for the overall failure and subtypes for mechanisms.
- B1 Marshall 6/C1; B2 Hawaii 2/O2; Texas flood 6/C1, G2.

### The Camp Fire test case
Mechanisms documented in the workbook's own summary and technical notes: heavy reliance on an opt-in CodeRED system with
low enrollment ("of ~52,000 evacuees only ~7,000 received an emergency notification") → reach (4) or insufficient use of
other modalities (6); "only one trained mass-notification staff" → organizational (2); "county network outage and loss
of internet connectivity" → technical (1); "CodeRED and IPAWS systems were not interoperable … WEA messages required
manual workarounds" → technical (1) and channel (6). Hand code: 6 / G2.

| Provider | Camp Fire FAILURE_TYPE |
|---|---|
| Claude | not available — export needed |
| OpenAI | not available — export needed |

The same pattern is visible in the available B1 result: **Claude chose 7** for Marshall ("opt-in registration, WEA not
used, cell-network overload, and a delayed WEA integration … No single dominant mechanism is established, so 7
(multi-causal) is the closest code"), marked disputed; the hand code is 6.

How each rule below would code the Camp Fire (illustration only):
B1 → depends on whether an official review names a principal cause (not established from the workbook); B2 → 6 or 4
(the public-facing breakdown is under-reach / insufficient use of other channels); B3 → 7 (four families documented);
B4 → e.g. "6; 1; 2" (not single-select).

### Methodological ambiguity
"Dominant" is undefined (by whose judgment? the official review's? the largest effect? the earliest link in the
chain?); "multi-causal" is undefined (two mechanisms? co-equal mechanisms?); the type list mixes causes and
manifestations; where "secondary codes may be noted" is not specified. Using 7 when the coder cannot rank mechanisms
turns 7 into an "undecided" bin.

### Possible decision rules
| Rule | When a specific type vs 7 | Consequences |
|---|---|---|
| B1 — Source-identified dominance | Specific type when the highest-priority source (AAR / official investigation) names a primary or principal cause; otherwise the type best supported across sources; 7 only when sources present mechanisms as co-equal. | Ties the code to evidence; reproducible. Undated / unofficial cases may stay unresolved; needs a source hierarchy (already exists in project priorities). |
| B2 — Manifestation first | Code the observable public-facing breakdown (what failed for the public: no alert, wrong area, late, unreachable, unclear); upstream causes go to FAILURE_SUBTYPE / notes. 7 only for atypical breakdowns. | High inter-coder agreement; matches past practice (Camp Fire 6/G2, Marshall 6/C1). Departs from the word "causal" in the definition. |
| B3 — Composite whenever ≥2 categories are documented | 7 for any multi-mechanism case. | Simple, but 7 would absorb most large disasters and lose analytic value; contradicts past practice. |
| B4 — Primary + noted secondary codes in the cell | "6; 2" etc. | Captures complexity but breaks single-select analyses and comparability. |

**Recommendation (assistant's suggestion, not a WFD requirement):** B1 with B2 as the tie-breaker — use the primary
mechanism named by the highest-priority source; if none is named, code the observable public-facing breakdown; record
all other documented mechanisms in FAILURE_SUBTYPE (and COMMENT_ANALYST), which is where "secondary codes may be noted";
reserve 7 for breakdowns that fit no category or where an authoritative source explicitly presents co-equal mechanisms,
with the reason stated. When sources conflict about the cause, the assistant would mark AMBIGUOUS/CONFLICTING with the
competing types as alternatives for the researcher, rather than choosing 7.

### Exact decision needed
1. The operational meaning of "dominant" (B1, B2, a combination, or another test).
2. When 7 is allowed (atypical only; explicitly co-equal mechanisms; any multi-mechanism case).
3. Where secondary mechanisms are "noted" (FAILURE_SUBTYPE, COMMENT_ANALYST, or a new field) and whether the cell may
   ever hold more than one code (2 historical rows do).
4. Whether the assistant may suggest 7 when sources do not rank mechanisms, or must return AMBIGUOUS with alternatives.
5. Optional: whether "causal mechanism" in the definition should be revised if B2 is chosen.

---

## C. HARM_LOSS_INDICATORS and material-impact attribution

### Current codebook language
- **HARM_LOSS_INDICATORS:** "Quantitative or qualitative evidence of harm or loss **linked to the failure**." Values:
  numeric estimates (fatalities, injuries, property losses in USD); -9 = Unknown / not applicable. Example "3 fatalities
  (delayed flash flood warning)". Coding note: "**Record only when failure plausibly contributed to the outcome, as
  confirmed by official investigations or credible sources.**" Section heading: "Harm/Loss Indicators (where
  attributable)".
- **FAILURE_SEVERITY (Material Impact):** consequences "**attributable (in whole or part) to the failure**"; "Attribution
  should be cautious and clearly supported"; example "3 — delayed alert contributed to multiple flood-related
  fatalities".
- **REPORTED_OUTCOMES:** "effects directly attributed to the warning failure"; 3 = "Injury or loss of life (partially
  attributable)"; 4 = "Property or environmental damage exacerbated by delay"; purpose "distinguishing communication
  effects from hazard outcomes".

**What this establishes:** the codebook consistently asks for harm **attributable to the failure**, not total disaster
loss. It leaves open how strong the link must be ("plausibly contributed" vs "confirmed"), whether a source's general
statement that people were not warned is enough to link a death toll, and what to record when the disaster loss is known
but the failure's share is not.

### Current software behaviour
- HARM_LOSS_INDICATORS is typed numeric, so text such as "85 fatalities" fails validation (K-51); `-9` allowed with
  "Unknown:" / "Not applicable:" (D-039). FAILURE_SEVERITY (Material Impact) is a judgment variable; its "0 = No material
  impact documented" may not be suggested from silence (PI-M4 c). No attribution rule beyond the codebook text and
  prompt rule 4 (separate failure from cause).

### Historical workbook behaviour
- HARM_LOSS_INDICATORS mostly records **overall disaster losses**: B3 Camp Fire "85 fatalities; 18,804 structures
  destroyed; 153,336 acres burned"; Texas flood "> 135 Fatalities"; Helene "108 Fatalities … > $59.6 Billion"; 2021
  Texas winter storm "246 Fatalities … ~195 Billion damages". One row states the limit explicitly (20230223-CA01: "13
  deaths recorded during the event … communication-attributable share not isolated").
- FAILURE_SEVERITY (Material Impact): 4 ×15, 3 ×7, 2 ×3, 1 ×3, 0 ×22. The 4s are the large disasters, i.e. severity
  appears to have been coded on total disaster impact.
- Inconsistencies: B1 Marshall HARM `-9` but severity 4; B2 Hawaii HARM `-9`, severity 1.
- **Past practice therefore conflicts with the codebook wording**; changing to strict attribution would change many
  historical values.

### Benchmark behaviour
| Case | Claude | OpenAI |
|---|---|---|
| B1 Marshall HARM_LOSS_INDICATORS | **blank** (insufficient): "no quantified harm that an official investigation or credible source links to the warning failure. The coding note requires that link"; flags the numeric type problem. | not available — export needed |
| B1 Marshall FAILURE_SEVERITY (Material) | **blank** (insufficient): "overall fire damage is large (over 1,000 homes, about $500 million). The codebook limits this variable to consequences attributable … no passage separates warning-related harm from fire damage"; notes 4 "if overall incident damage were coded". | not available — export needed |
| B2, B3, Texas | not available — export needed | not available — export needed |

### Methodological ambiguity
(1) Threshold: "plausibly contributed" (low) vs "confirmed by official investigations" (high) in the same sentence.
(2) Unit: may a total be recorded when a source links the failure to *some* of the losses without a number? (3) What to
record when the loss is established but attribution is not: `-9` (Unknown), blank, the total with a qualifier, or the
total in another field. (4) Severity: does 0 ("no material impact documented") or blank apply when large losses occurred
but attribution is unknown — 0 would misread as "no impact".

### Possible decision rules
| Rule | What is coded | Consequences |
|---|---|---|
| C1 — Strict attribution | Only losses a credible source attributes, wholly or partly, to the warning failure (quantified if the source quantifies; otherwise qualitative). Disaster totals go to SUMMARY / COMMENT_ANALYST. Severity rates only attributable impact. | Faithful to the codebook; protects the database from overstating warning-failure harm. Many cases become -9/blank; ~15 historical severity-4 codes would need review. |
| C2 — Plausible-contribution threshold | Disaster totals may be recorded when a credible source states the failure contributed to the losses (e.g. victims did not receive warnings), even without a share; the record states that the share is not isolated. | Keeps more information and is close to past practice; mixes hazard and failure effects, weakening comparative analysis. |
| C3 — Two quantities | Attributable harm in HARM_LOSS_INDICATORS / severity (C1), and the hazard total in a separate new field (e.g. a "hazard context loss" field) or a fixed note format. | Clearest for analysts; requires a codebook change and a workbook column. |
| C4 — Past practice | Code totals in HARM and severity on total impact. | Continuity with v1.7; contradicts the codebook text and the purpose stated for REPORTED_OUTCOMES. |

Related to the existing decisions: under PI-M1/M2 a `-9` would read "Unknown: loss documented but attribution to the
failure not established" — the rule must say whether that is the intended use of `-9`.

**Recommendation (assistant's suggestion, not a WFD requirement):** C3 if the team is willing to add a field; otherwise
C1 — record only attributable harm, use `-9` "Unknown:" when losses are documented but attribution is not, put the
disaster total in COMMENT_ANALYST, and leave FAILURE_SEVERITY (Material Impact) blank (never 0) when attribution is not
established. Decide separately whether historical rows are re-coded or kept (as with PI-M3).

### Exact decision needed
1. Attribution threshold: "plausibly contributed" per a credible source, or "confirmed" by an official investigation.
2. Whether hazard totals may be recorded in HARM_LOSS_INDICATORS (C2/C4) or must go elsewhere (C1/C3).
3. If C3: the new field's name and definition (a codebook change).
4. The value when losses are documented but attribution is not: `-9` Unknown, blank, or the total with a qualifier.
5. FAILURE_SEVERITY (Material Impact) when attribution is unknown: blank, or rate total impact.
6. HARM_LOSS_INDICATORS type: numeric only, or numeric + unit text (PI-M11 / K-51).
7. Historical rows: keep as recorded or re-review (15 severity-4 rows; Marshall/Hawaii inconsistencies).

---

## Summary of what the team needs to decide

| Issue | Core question | Open IDs |
|---|---|---|
| A | Which endpoint END_DATE records; undocumented end | A1–A5 (+ PI-M5, PI-M6) |
| B | Operational meaning of "dominant"; when 7 applies; where secondary codes go | B1–B5 |
| C | Attribution threshold; where disaster totals go; severity when attribution is unknown | C1–C7 (+ PI-M11) |

Until the team decides, the software keeps its current behaviour for all three issues. After approval, the decisions
would be recorded in DECISIONS.md and implemented on a branch with tests, as for D-039.
