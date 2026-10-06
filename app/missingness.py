"""Missing-value rules that the WFD codebook v1.3 states explicitly (D-039).

Only rules written in the codebook are implemented here; everything ambiguous is listed for a PI decision in
docs/missingness/PI_DECISIONS_missingness.md and is NOT decided by this code. These checks never change a value:
they produce review flags on HUMAN-FINAL values (accepted / edited / cleared reviews), shown in the review workbench and
the export, so the researcher can correct the record.

Implemented (codebook wording quoted):
- UNCERTAINTY_TYPE — "When UNCERTAINTY_FLAG = 1, the case must also specify UNCERTAINTY_TYPE."
- LATITUDE / LONGITUDE — "When unavailable, leave blank and flag GEOCODE_SPECIFICITY = 0."
- INCIDENT_DURATION — "Total number of days between EVENT_DATE and END_DATE"; calculation (END_DATE – EVENT_DATE) + 1.
  An END_DATE before EVENT_DATE cannot give a number of days; flagged (and never derived, see coding.derive_fields).
- END_DATE — "If the failure was momentary ... END_DATE = EVENT_DATE": not machine-checkable (needs a judgement that
  the failure was momentary), so it is NOT implemented as a rule.
- -9 entered by a researcher where the variable's entry defines none: kept (the researcher decides) but flagged until
  the PI decision PI-M3.
Elsewhere (app/validator.py): model suggestions may use -9 only where the variable's own entry defines it; dash / "N/A"
placeholders are blank.
"""
from __future__ import annotations

import datetime as dt

FINAL_ACTIONS = ("accepted", "edited", "cleared")
LATLONG_NAMES = ("LAT/LONG", "LATITUDE / LONGITUDE", "LATITUDE/LONGITUDE")


def _norm(v) -> str:
    s = "" if v is None else str(v).strip()
    return s[:-2] if s.endswith(".0") and s[:-2].lstrip("-").isdigit() else s


def _date(v):
    try:
        return dt.date.fromisoformat(_norm(v)[:10])
    except ValueError:
        return None


def consistency_flags(final: dict, fields: dict | None = None) -> dict[str, list[str]]:
    """final: variable -> human-final value (only variables that have one); fields: variable -> schema field (optional).
    Returns variable -> [flag messages]."""
    from .validator import special_missing_form, split_values
    out: dict[str, list[str]] = {}

    def flag(var, msg):
        out.setdefault(var, []).append(msg)

    for var, val in final.items():
        f = (fields or {}).get(var)
        if not f or not _norm(val):
            continue
        parts = split_values(_norm(val)) if f.get("type") in ("categorical", "open_list") else [_norm(val)]
        if any(special_missing_form(p) for p in parts) and "-9" not in (f.get("missing_codes") or []):
            # a researcher may still enter it (historical practice); it is reported, not blocked — PI decision PI-M3
            flag(var, "-9 is not defined by the codebook for this variable (see PI decision PI-M3); blank is the "
                      "codebook-consistent entry when the value is not established.")

    if _norm(final.get("UNCERTAINTY_FLAG")) == "1" and "UNCERTAINTY_TYPE" in final and not _norm(final["UNCERTAINTY_TYPE"]):
        flag("UNCERTAINTY_TYPE", "Codebook: when UNCERTAINTY_FLAG = 1, the case must also specify UNCERTAINTY_TYPE "
                                 "(currently blank).")
    ll = next((n for n in LATLONG_NAMES if n in final), None)
    if ll and not _norm(final[ll]) and "GEOCODE_SPECIFICITY" in final and _norm(final["GEOCODE_SPECIFICITY"]) != "0":
        flag("GEOCODE_SPECIFICITY", f"Codebook: when coordinates are unavailable, leave {ll} blank and flag "
                                    f"GEOCODE_SPECIFICITY = 0 ({ll} is blank; GEOCODE_SPECIFICITY is "
                                    f"'{_norm(final['GEOCODE_SPECIFICITY']) or 'blank'}').")
    a, b = _date(final.get("EVENT_DATE")), _date(final.get("END_DATE"))
    if a and b and b < a:
        for v in ("END_DATE", "EVENT_DATE"):
            if v in final:
                flag(v, "END_DATE is earlier than EVENT_DATE — INCIDENT_DURATION cannot be calculated; check both dates.")
    if a and b and b >= a and "INCIDENT_DURATION" in final and _norm(final["INCIDENT_DURATION"]) \
            and _norm(final["INCIDENT_DURATION"]) != str((b - a).days + 1):
        flag("INCIDENT_DURATION", f"Codebook calculation (END_DATE – EVENT_DATE) + 1 gives {(b - a).days + 1}, not "
                                  f"{_norm(final['INCIDENT_DURATION'])}.")
    return out


def duration_days(event_date: str, end_date: str) -> int | None:
    """INCIDENT_DURATION per codebook, or None when it cannot be calculated (missing or reversed dates)."""
    a, b = _date(event_date), _date(end_date)
    if not a or not b or b < a:
        return None
    return (b - a).days + 1
