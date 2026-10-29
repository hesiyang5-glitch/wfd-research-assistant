# Visual polish and "research instrument" theme — 2026-10-29 (branch `ui/visual-polish`)

Owner request 2026-10-29: optimise the look only — button text on one line, buttons that respond to the mouse, the
22 presentation items and the 10 tech-style elements proposed in chat. **No functional change**: features, API
routes, request payloads, settings keys and values, database, cache, costs, exports, prompts and coding rules are
unchanged. Wording is unchanged except where noted (readable status names, empty-progress sentence, group headings).

## Visual polish (owner items 1–22)

| # | Where | Change |
|---|---|---|
| 1 | All buttons, chips, tabs, status tags | `white-space: nowrap`; a full button moves to the next line instead of splitting its words |
| 2 | Review table, Comparison column | short badges ("仅 Claude", "Claude only") on one line; only long agreement texts (> 16 characters) may wrap |
| 3 | Schema page | "Edit rule" column sized to the button; long workbook headers break at "_" so the table fits; rows are normal height |
| 4 | Variable names (review table, detail panel, schema) | may break only after "_" (`<wbr>`), never mid-word; visible text unchanged |
| 5 | Model identifiers | never split (gpt-6.1-sol, claude-sonnet-5-5) |
| 6 | Case tabs on phones | one row that scrolls sideways |
| 7–12 | Buttons | hover: lift + shadow + accent colour; primary: brighter with cyan halo; danger: light red; press: sinks back; keyboard focus: cyan outline; disabled: no hover, not-allowed cursor; 0.12 s, off under "reduce motion" |
| 13 | Research page provider cards | model line(s) kept whole; chosen card marked with ✓ |
| 14 | Cost estimate / coverage / usage lists | label column sized to its content (max 320 px), figures in tabular digits |
| 15 | Review table | "No supported value" tags quieter; every result state still has its own look |
| 16 | Review detail panel | actions grouped: Accept / Defer / Clear (/ Undo) — then Edit → Save and Re-analyze this variable |
| 17 | Progress page | "Variables still weak on evidence" collapsible with a count; empty state is a sentence + Re-run button |
| 18 | Settings | fields grouped under Web research / Coding / Limits (per case) / OpenAI request settings (same keys, values, options) |
| 19 | Sources page | the three "Add" buttons aligned on one line |
| 20 | Header | language switch highlights the active language; active page underlined in cyan |
| 21 | Phones | header nav scrolls sideways; review table scrolls with the variable column fixed on the left |
| 22 | Status tags | readable names (`needs_input` → "Needs your input", `review` → "In review"…); raw id kept as tooltip |

## Tech-style elements (owner items 1–10)

| # | Element |
|---|---|
| 1 | Signal-wave brand mark (inline SVG), monospace product name, cyan glow line under the header |
| 2 | Faint dot-grid page background |
| 3 | Soft panel shadows; short cyan accent bar on top-level panels |
| 4 | Monospace "instrument" labels for small English section labels (Services groups, Settings groups) and IDs/codes |
| 5 | Status dots glow like indicator LEDs |
| 6 | Pipeline: current step glows cyan and pulses while running; progress bar blue → cyan |
| 7 | Run log as a terminal (dark background, amber warnings, coral errors) |
| 8 | Primary button gradient + cyan halo on hover; cyan focus ring on inputs |
| 9 | Selected review row marked with a cyan bar; active filter chip with a cyan underline |
| 10 | Opt-in dark theme (header ◐ button; light is the default; stored in this browser only; nothing sent to the server) |

Not done on purpose: neon everywhere, scan-line or typing animations, changes to the colours that distinguish result
states. Fonts are not downloaded (CSP `default-src 'self'`); see KNOWN_ISSUES K-55.
