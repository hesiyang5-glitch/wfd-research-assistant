"""Schema loader: codebook (authority for definitions/codes) + workbook (authority for field names/order).

Nothing here is specific to one codebook version: variables are discovered from "Variable:" headings,
codes from "X = label" lines, and workbook fields from the header row. Anything that cannot be
resolved confidently is kept and flagged, never guessed.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

LABEL_RE = re.compile(r"^\s*\**\s*(Definition|Values?|Format|Coding Options|Coding Notes|Notes|Purpose|Example|Examples|"
                      r"Subfields|Calculation|Content Guidelines|Distinction from [A-Z_]+|Values \(.*?\))\s*\**\s*:?\s*\**\s*(.*)$",
                      re.I)
VAR_RE = re.compile(r"^\s*(?:#+\s*)?\**\s*Variable:\s*\**\s*(.+?)\s*\**\s*$", re.I)
SECTION_RE = re.compile(r"^\s*(?:#+\s*)?\**\s*([IVX]{1,4})\.\s+\**\s*([A-Z][A-Z /&]+?)\s*\**\s*$")
CODE_RE = re.compile(r"^\s*(?:[-•*]\s+)?(-?[A-Za-z0-9][A-Za-z0-9\-]*)\s*=\s*(.+)$")
BAND_RE = re.compile(r"^\s*[-•*]?\s*(\d+)\s*[–-]\s*(\d+)\s*%\s*=\s*(.+)$")
BULLET_RE = re.compile(r"^\s*[-•*]\s*(.+)$")
SUBFIELD_RE = re.compile(r"^\s*[-•*]?\s*([A-Z][A-Z_]+)\s*\((.*)\)\s*$")

ADMIN_PATTERNS = [r"added or last modified", r"lifecycle status", r"how the information was obtained",
                  r"chronological record of edits", r"unique alphanumeric identifier"]
NOTE_PATTERNS = [r"free-text field for coder", r"coder observations", r"coder notes"]
DERIVED_PATTERNS = [r"^calculation", r"number of primary sources", r"number of secondary",
                    r"coded overview of the types of documentation", r"list of hyperlinks, dois"]


def norm(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def tokens(s: str) -> list[str]:
    return [t for t in re.split(r"[^A-Z0-9]+", (s or "").upper()) if t]


# --------------------------------------------------------------------------- codebook text
def docx_to_text(path: str | Path) -> str:
    import docx  # python-docx
    d = docx.Document(str(path))
    lines: list[str] = []
    # Paragraphs and tables in document order
    body = d.element.body
    for child in body.iterchildren():
        tag = child.tag.split("}")[-1]
        if tag == "p":
            txt = "".join(n.text or "" for n in child.iter() if n.tag.endswith("}t"))
            lines.append(txt)
        elif tag == "tbl":
            for row in child.iter():
                if row.tag.endswith("}tr"):
                    cells = []
                    for cell in row.iter():
                        if cell.tag.endswith("}tc"):
                            cells.append("".join(n.text or "" for n in cell.iter() if n.tag.endswith("}t")))
                    lines.append(" | ".join(cells))
    return "\n".join(lines)


def load_codebook_text(path: str | Path) -> str:
    p = Path(path)
    if p.suffix.lower() == ".docx":
        return docx_to_text(p)
    return p.read_text(encoding="utf-8", errors="replace")


def _split_blocks(text: str):
    """Yield (section, raw_name, lines, start_line) for each 'Variable:' block."""
    section = ""
    cur = None
    lines = text.splitlines()
    in_vars = False
    for i, line in enumerate(lines):
        m_sec = SECTION_RE.match(line)
        if m_sec:
            section = f"{m_sec.group(1)}. {m_sec.group(2).strip().title()}"
        m = VAR_RE.match(line)
        if m:
            in_vars = True
            if cur:
                yield cur
            cur = [section, m.group(1).strip().strip("*").strip(), [], i + 1]
            continue
        if cur is not None:
            # stop a block at a new section heading or appendix
            if re.match(r"^\s*\**\s*APPENDICES", line) or (m_sec and in_vars):
                yield cur
                cur = None
                continue
            if re.match(r"^\s*(#+\s*)?\**\s*(Analytical Relevance|Summary Notes)\b", line, re.I):
                yield cur
                cur = None
                continue
            cur[2].append(line)
    if cur:
        yield cur


def _parse_block(section: str, raw_name: str, lines: list[str], line_no: int) -> list[dict]:
    fields: dict[str, list[str]] = {}
    label = "Preamble"
    headers: dict[str, str] = {}
    for line in lines:
        m = LABEL_RE.match(line)
        if m and len(line) < 200:
            label = m.group(1).strip()
            key = label.split("(")[0].strip().title()
            headers[key] = line.strip()
            fields.setdefault(key, [])
            rest = m.group(2).strip().strip("*").strip()
            if rest:
                fields[key].append(rest)
            label = key
            continue
        if line.strip():
            fields.setdefault(label, []).append(line.strip())

    definition = " ".join(fields.get("Definition", [])).strip()
    values_lines = fields.get("Values", []) + fields.get("Value", [])
    values_header = headers.get("Values", "") or headers.get("Value", "")
    notes = " ".join(fields.get("Coding Notes", []) + fields.get("Notes", [])).strip()
    fmt = " ".join(fields.get("Format", [])).strip()
    options_lines = fields.get("Coding Options", [])
    examples_lines = fields.get("Examples", []) if not values_lines else []

    issues: list[str] = []
    codes: list[dict] = []
    bands: list[dict] = []
    open_options: list[str] = []
    numeric = False
    missing_codes: list[str] = []
    missing_labels: dict[str, str] = {}

    src_lines = values_lines or examples_lines
    for vl in src_lines:
        b = BAND_RE.match(vl)
        if b:
            bands.append({"min": int(b.group(1)), "max": int(b.group(2)), "label": b.group(3).strip()})
            continue
        c = CODE_RE.match(vl)
        if c and not re.match(r"^\s*[-•*]?\s*(Natural|Technological|Human-caused|Other)\s+hazards?", vl, re.I):
            code, lab = c.group(1).strip(), c.group(2).strip()
            if code.startswith("-") and re.fullmatch(r"-\d+", code):
                missing_codes.append(code)   # variable-specific special missing value
                missing_labels[code] = lab
                continue
            codes.append({"code": code, "label": lab})
            continue
        if re.search(r"\bnumeric\b", vl, re.I):
            numeric = True
            if re.search(r"-9", vl):
                missing_codes.append("-9")
            continue
        if re.search(r"use\s+-9", vl, re.I):
            missing_codes.append("-9")
            continue
        bm = BULLET_RE.match(vl)
        opt = (bm.group(1) if bm else vl).strip()
        if re.fullmatch(r"\(.*\)\s*:?", opt):   # e.g. "(multi-select):" left after the Values label
            continue
        if opt:
            open_options.append(opt)

    blob = " ".join([values_header, definition, raw_name]).lower()
    is_multi = bool(re.search(r"multi-select|multiple values permitted|multiple codes are permitted|multiple values", blob))
    is_single = "single-select" in blob
    open_list = bool(re.search(r"\(examples?\)", values_header.lower())) or bool(examples_lines) or \
        (open_options and not codes)
    if is_multi and is_single:
        issues.append("Codebook text says both single-select and multiple values permitted — confirm selection rule.")
    if "multiple secondary codes may be noted" in blob:
        issues.append("Single-select primary code, but text allows secondary codes to be 'noted' — confirm whether the cell may hold several codes.")

    # Missing-value rules are variable-specific only.
    missing_codes = sorted(set(missing_codes))

    # Type inference
    name_up = raw_name.upper()
    date_fmt = bool(re.search(r"YYYY-MM-DD\b", (fmt + " " + " ".join(options_lines)).upper())) and \
        not re.search(r"YYYYMMDD-", fmt.upper())
    name_tokens = re.findall(r"[A-Z]+", name_up.split("(")[0])
    if (date_fmt or (name_tokens and name_tokens[-1] == "DATE")) and not codes:
        vtype = "date"
    elif bands:
        vtype = "numeric"
        issues.append("Values are given as percentage bands but the definition also asks for an exact figure when available — "
                      "confirm whether to record a band label, a band midpoint, or the exact number.")
    elif codes and not open_list:
        vtype = "categorical"
    elif codes or open_options:
        vtype = "open_list"
    elif numeric:
        vtype = "numeric"
    elif re.search(r"calculation", " ".join(fields.keys()).lower()):
        vtype = "numeric"
    else:
        vtype = "text"

    if vtype == "categorical" and codes:
        nums = [int(c["code"]) for c in codes if re.fullmatch(r"-?\d+", c["code"])]
        pos = sorted(n for n in nums if n >= 0)
        if pos and pos[0] > 1:
            issues.append(f"Code list starts at {pos[0]} (codes 0–{pos[0]-1} undefined) — confirm whether a code is missing.")
        elif pos and any(b - a > 1 for a, b in zip(pos, pos[1:])):
            issues.append("Gap in numeric code sequence — confirm whether a code is missing.")
    if "[" in notes and "]" in notes:
        issues.append(f"Editorial note left in codebook text: {notes[notes.find('['):notes.find(']')+1]}")

    dlow = definition.lower()
    all_text = (definition + " " + " ".join(fields.get("Calculation", [])) + " " + " ".join(fields.keys())).lower()
    if any(re.search(p, dlow) for p in NOTE_PATTERNS):
        field_class = "analyst_note"
    elif any(re.search(p, dlow) for p in ADMIN_PATTERNS):
        field_class = "admin"
    elif "Calculation" in fields or any(re.search(p, dlow) for p in DERIVED_PATTERNS):
        field_class = "derived"
    elif re.search(r"analyst-coded|coder judgment|assessed|assessment of", dlow):
        field_class = "judgment"
    else:
        field_class = "sourced"

    base = {
        "codebook_name": raw_name,
        "section": section,
        "definition": definition,
        "type": vtype,
        "multi": bool(is_multi and not (is_single and not is_multi)),
        "open_list": bool(open_list),
        "codes": codes,
        "bands": bands,
        "open_options": open_options,
        "missing_codes": missing_codes,
        "missing_labels": missing_labels,
        "format": fmt or " ".join(options_lines),
        "notes": notes,
        "calculation": " ".join(fields.get("Calculation", [])),
        "field_class": field_class,
        "codebook_ref": f"{section} › Variable: {raw_name} (line {line_no})",
        "issues": issues,
    }
    out = [base]
    # Subfields become their own variables (e.g., MESSAGE_CHARACTERISTICS_LENGTH)
    for sl in fields.get("Subfields", []):
        sm = SUBFIELD_RE.match(sl)
        if not sm:
            continue
        sub, inner = sm.group(1), sm.group(2)
        sub_codes = [{"code": a.strip(), "label": b.strip()} for a, b in re.findall(r"(-?\w+)\s*=\s*([^,]+)", inner)]
        sub_opts = [] if sub_codes else [o.strip() for o in inner.split(",") if o.strip() and not o.strip().lower().startswith("etc")]
        if sub_codes:
            st = "categorical"
        elif re.search(r"number of", inner, re.I):
            st = "numeric"
        elif sub_opts and len(sub_opts) > 1:
            st = "open_list"
        else:
            st = "text"
        out.append({**base, "codebook_name": f"{raw_name}_{sub}", "parent": raw_name, "definition": f"{definition} Subfield {sub}: {inner}",
                    "type": st, "multi": False, "open_list": st == "open_list", "codes": sub_codes, "bands": [],
                    "open_options": sub_opts, "missing_codes": [], "missing_labels": {}, "issues": list(i for i in base["issues"]),
                    "codebook_ref": base["codebook_ref"] + f" › Subfield {sub}"})
    return out


def parse_codebook(text: str) -> list[dict]:
    variables: list[dict] = []
    for section, raw, lines, ln in _split_blocks(text):
        variables.extend(_parse_block(section, raw, lines, ln))
    # Duplicate definitions
    counts = Counter(norm(v["codebook_name"]) for v in variables)
    for v in variables:
        if counts[norm(v["codebook_name"])] > 1:
            v["issues"].append("Variable defined more than once in the codebook — definitions may conflict.")
    return variables


# --------------------------------------------------------------------------- workbook
def read_workbook(path: str | Path, sheet_hint: str = "WFD_Cases"):
    import openpyxl
    wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    ws = None
    for s in wb.worksheets:
        if s.title.strip().lower() == sheet_hint.lower():
            ws = s
            break
    ws = ws or wb.worksheets[0]
    rows = ws.iter_rows(values_only=True)
    header = list(next(rows))
    # Drop trailing empty header cells only; interior blanks keep their position.
    while header and (header[-1] is None or str(header[-1]).strip() == ""):
        header.pop()
    data_rows = []
    for r in rows:
        r = list(r)[: len(header)]
        if any(c not in (None, "") for c in r):
            data_rows.append(r)
    sheets = [s.title for s in wb.worksheets]
    wb.close()
    return ws.title, header, data_rows, sheets


def clean_header(h) -> tuple[str, str | None]:
    """Return (canonical header, issue)."""
    if h is None or str(h).strip() == "":
        return "", "Blank header cell inside the field list — position preserved in exports; confirm its purpose."
    raw = str(h)
    s = raw.strip()
    parts = re.split(r"\s{3,}", s)
    if len(parts) > 1:
        return parts[0].strip(), f"Header contains extra text after the field name: '{raw.strip()}' — kept field name '{parts[0].strip()}'."
    if s != raw:
        return s, "Header has leading/trailing spaces."
    return s, None


def _approx_match(header: str, var_name: str) -> bool:
    ht, vt = tokens(header), tokens(var_name)
    if not ht or len(ht) != len(vt):
        return False
    return all(v.startswith(h) and len(h) >= 3 for h, v in zip(ht, vt)) and ht != vt


def build_schema(codebook_vars: list[dict], header: list, data_rows: list, workbook_label: str) -> dict:
    by_norm: dict[str, list[dict]] = {}
    by_variant: dict[str, list[dict]] = {}
    for v in codebook_vars:
        by_norm.setdefault(norm(v["codebook_name"]), []).append(v)
        variant = re.sub(r"\s*\((Primary)\)\s*$", "", v["codebook_name"], flags=re.I)
        variant2 = re.sub(r"\s*\(.*?\)\s*", "", v["codebook_name"])
        for vv in {variant, variant2}:
            by_variant.setdefault(norm(vv), []).append(v)

    fields: list[dict] = []
    used = set()
    for pos, h in enumerate(header):
        name, h_issue = clean_header(h)
        f = {"position": pos + 1, "name": name or f"(blank column {pos+1})", "raw_header": "" if h is None else str(h),
             "blank_header": not name, "issues": [h_issue] if h_issue else [], "mapping": "none", "codebook_name": None}
        cand = None
        if name:
            n = norm(name)
            if n in by_norm and len(by_norm[n]) == 1:
                cand, f["mapping"] = by_norm[n][0], "exact"
            elif n in by_variant and len({id(x) for x in by_variant[n]}) == 1:
                cand, f["mapping"] = by_variant[n][0], "variant"
            elif n in by_variant:
                f["issues"].append("Header matches several codebook variables — mapping ambiguous.")
                f["mapping"] = "ambiguous"
            else:
                # header = codebook name + qualifier, e.g. "X_LENGTH (Char. No Space)"
                stripped = norm(re.sub(r"\s*\(.*?\)\s*", "", name))
                if stripped in by_norm and len(by_norm[stripped]) == 1:
                    cand, f["mapping"] = by_norm[stripped][0], "qualified"
                    f["issues"].append(f"Workbook header adds a qualifier not in the codebook ('{name}') — confirm the qualifier "
                                       f"matches the codebook definition.")
                else:
                    approx = [v for v in codebook_vars if _approx_match(name, v["codebook_name"])]
                    if len(approx) == 1:
                        cand, f["mapping"] = approx[0], "approximate"
                        f["issues"].append(f"Approximate name match to codebook variable '{approx[0]['codebook_name']}' — confirm.")
        if cand:
            used.add(id(cand))
            f["codebook_name"] = cand["codebook_name"]
            for k in ("section", "definition", "type", "multi", "open_list", "codes", "bands", "open_options", "missing_codes", "missing_labels",
                      "format", "notes", "calculation", "field_class", "codebook_ref"):
                f[k] = cand[k]
            f["issues"] += cand["issues"]
            f["rule_missing"] = False
        else:
            f.update({"section": "", "definition": "", "type": "text", "multi": False, "open_list": False, "codes": [], "bands": [],
                      "open_options": [], "missing_codes": [], "missing_labels": {}, "format": "", "notes": "", "calculation": "",
                      "field_class": "unmapped", "codebook_ref": "", "rule_missing": True})
            if name:
                f["issues"].append("No codebook definition found for this workbook field — kept, marked 'rule missing'; "
                                   "no codes will be suggested until a rule is added.")
        fields.append(f)

    # Check existing workbook data against the codebook (generic conflict detector)
    for f in fields:
        if f["type"] != "categorical" or not f["codes"]:
            continue
        col = f["position"] - 1
        allowed = {c["code"].upper() for c in f["codes"]} | {m.upper() for m in f["missing_codes"]}
        multi_rows, bad = 0, Counter()
        for r in data_rows:
            val = r[col] if col < len(r) else None
            if val in (None, ""):
                continue
            s = str(val).strip()
            if re.fullmatch(r"-?\d+\.0", s):
                s = s[:-2]
            parts = [p.strip() for p in re.split(r"[;,]", s) if p.strip()]
            if len(parts) > 1:
                multi_rows += 1
            for p in parts:
                p2 = p[:-2] if re.fullmatch(r"-?\d+\.0", p) else p
                if p2.upper() not in allowed:
                    bad[p2] += 1
        if multi_rows and not f["multi"]:
            f["issues"].append(f"Workbook data has {multi_rows} row(s) with several codes in this single-select field.")
        dates = {k: v for k, v in bad.items() if re.fullmatch(r"\d{4}-\d{2}-\d{2} 00:00:00", k)}
        others = Counter({k: v for k, v in bad.items() if k not in dates})
        if others:
            ex = ", ".join(f"'{k}'×{v}" for k, v in others.most_common(4))
            f["issues"].append(f"Workbook data contains values not defined in the codebook: {ex}.")
        if dates:
            f["issues"].append(f"{sum(dates.values())} workbook cell(s) hold dates (e.g., '{next(iter(dates))}') — likely a multi-code "
                               f"entry such as '1, 3' that Excel auto-converted to a date; check the original entry.")

    unmapped_cb = [v["codebook_name"] for v in codebook_vars if id(v) not in used and not v.get("parent_only")]
    # Parent variables whose subfields are mapped are not "missing"
    mapped_names = {f["codebook_name"] for f in fields if f["codebook_name"]}
    parents_ok = {v.get("parent") for v in codebook_vars if v["codebook_name"] in mapped_names and v.get("parent")}
    unmapped_cb = [n for n in unmapped_cb if n not in parents_ok]

    return {
        "workbook_label": workbook_label,
        "fields": fields,
        "codebook_only": unmapped_cb,
        "stats": {
            "n_fields": len(fields),
            "n_mapped": sum(1 for f in fields if not f["rule_missing"]),
            "n_rule_missing": sum(1 for f in fields if f["rule_missing"]),
            "n_with_issues": sum(1 for f in fields if f["issues"]),
            "n_codebook_vars": len(codebook_vars),
        },
    }


def build_from_files(codebook_path, workbook_path) -> dict:
    text = load_codebook_text(codebook_path)
    cb = parse_codebook(text)
    if not cb:
        raise ValueError("No 'Variable:' headings were found in the codebook — cannot build a schema.")
    sheet, header, rows, sheets = read_workbook(workbook_path)
    schema = build_schema(cb, header, rows, f"{Path(workbook_path).name} [{sheet}]")
    schema["codebook_label"] = Path(codebook_path).name
    id_col = next((i for i, h in enumerate(header) if clean_header(h)[0].upper() == "WFD_ID"), None)
    schema["existing_ids"] = sorted({str(r[id_col]).strip() for r in rows if id_col is not None and id_col < len(r) and r[id_col]})
    schema["workbook_sheets"] = sheets
    return schema
