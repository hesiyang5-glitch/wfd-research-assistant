"""HTTP server + JSON API. Standard library only (ThreadingHTTPServer), so it runs with a plain Python install.
Serves the single-page web app from /web. Binds to 127.0.0.1 by default (local, single researcher)."""
from __future__ import annotations

import base64
import json
import math
import mimetypes
import os
import re
import sys
import time
import traceback
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import auth, db, jobs
from .config import DATA_DIR, DEFAULT_SETTINGS, REFERENCE_DIR, ROOT, load_pricing, secret_status
from .schema_loader import build_from_files

WEB = ROOT / "web"
ROUTES = []


def route(method, pattern):
    rx = re.compile("^" + re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", pattern) + "$")

    def deco(fn):
        ROUTES.append((method, rx, fn))
        return fn
    return deco


class ApiError(Exception):
    def __init__(self, status, msg):
        super().__init__(msg)
        self.status, self.msg = status, msg


# ----------------------------------------------------------------------------- bootstrap
def bootstrap_schema():
    if db.q1("SELECT id FROM schema_versions LIMIT 1"):
        return
    cb = REFERENCE_DIR / "CODEBOOK_v1.3_variables.txt"
    wbs = sorted(REFERENCE_DIR.glob("*.xlsx"))
    docx = sorted(REFERENCE_DIR.glob("*.docx"))
    if (docx or cb.exists()) and wbs:
        s = build_from_files(docx[0] if docx else cb, wbs[-1])
        save_schema(s, f"{s['codebook_label']} + {s['workbook_label']}", activate=True, note="initial load from reference files")


def save_schema(s: dict, label: str, activate=False, parent_id=None, note="") -> int:
    sid = db.insert("schema_versions", {"label": label, "codebook_label": s.get("codebook_label"), "workbook_label": s.get("workbook_label"),
                                        "created_at": time.time(), "active": 0, "parent_id": parent_id, "change_note": note,
                                        "schema_json": json.dumps(s)})
    if activate:
        db.ex("UPDATE schema_versions SET active=CASE WHEN id=? THEN 1 ELSE 0 END", (sid,))
    return sid


def global_settings() -> dict:
    return {**DEFAULT_SETTINGS, **(db.get_setting("defaults", {}) or {})}


def ocr_ok() -> bool:
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


# ----------------------------------------------------------------------------- status & settings
@route("GET", "/api/status")
def api_status(h, **_):
    from .llm.clients import get_client
    from .search.providers import get_provider
    s = global_settings()
    prov = get_provider(s["search_provider"])
    cli = None if s["model_provider"] == "none" else get_client(s["model_provider"], s["model_name"])
    act = db.q1("SELECT id,label,created_at FROM schema_versions WHERE active=1")
    return {"secrets": secret_status(), "search_provider": prov.name if prov else None,
            "search_is_test": bool(prov and prov.is_test),
            "model": {"provider": cli.provider, "name": cli.model} if cli else None,
            "providers": provider_status(), "modes": available_modes(s),
            "ocr_available": ocr_ok(), "embeddings": bool(os.environ.get("EMBEDDING_MODEL")),
            "active_schema": act, "settings": s, "pricing": load_pricing(), "data_dir": str(DATA_DIR)}


def provider_status() -> dict:
    from .llm.clients import provider_status as ps
    return ps()


PROVIDER_PLAIN = {"anthropic": "Claude", "openai": "OpenAI"}


def available_modes(settings: dict) -> list[dict]:
    """The ONE list of coding-provider choices, shared by the first research form, Re-analyze and Settings (D-036):
    Claude only, OpenAI only, Claude + OpenAI — independent comparison. Equal providers; no primary or reviewer.
    A mode is unavailable when a provider it needs has no key configured (the reason is plain text, never a key)."""
    from .coding import MODES, PUBLIC_MODES
    ps = provider_status()
    ok = {"anthropic": ps["anthropic"]["configured"], "openai": ps["openai"]["configured"]}
    out = []
    for m in PUBLIC_MODES:
        need = [p for p, _ in MODES[m]]
        missing = [p for p in need if not ok[p]]
        out.append({"mode": m, "available": not missing, "providers": need, "missing": missing,
                    "reason": "" if not missing else
                    "; ".join(f"{PROVIDER_PLAIN[p]} is not configured on the server "
                              f"({'ANTHROPIC_API_KEY' if p == 'anthropic' else 'OPENAI_API_KEY'} is not set)"
                              for p in missing)})
    return out


def check_mode(mode: str | None, settings: dict) -> str | None:
    from .coding import CROSS_MODEL_MODES
    if mode in (None, ""):
        return None
    if mode == "single":  # legacy default of existing cases: one provider chosen by model_provider
        return mode
    if mode in CROSS_MODEL_MODES:
        raise ApiError(400, "cross-model review (one model sees the other's answer) is outside the current scope; "
                            "choose Claude only, OpenAI only, or Claude + OpenAI — independent comparison")
    m = next((x for x in available_modes(settings) if x["mode"] == mode), None)
    if not m:
        raise ApiError(400, f"unknown coding mode '{mode}'")
    if not m["available"]:
        raise ApiError(400, f"coding mode '{mode}' cannot run: {m['reason']}")
    return mode


def provider_checks(mode: str, settings: dict) -> dict:
    """Free availability checks for the providers a mode needs (no paid request). Returns per-provider
    {ok, verified, reason}. A provider whose key is rejected or whose model is unknown is not ok; a provider that
    cannot be reached right now is ok but unverified (it is checked again before the first paid request)."""
    from .coding import MODES
    from .llm.clients import LLMError, make_client
    out = {}
    for prov, _ in MODES.get(mode) or []:
        c = make_client(prov, settings.get("model_name", "claude-sonnet-5-5"), settings)
        if c is None:
            out[prov] = {"ok": False, "verified": False, "reason": f"{PROVIDER_PLAIN[prov]} is not configured on the server"}
            continue
        check = getattr(c, "check_available", None) or getattr(c, "preflight", None)
        try:
            if check:
                check()
            out[prov] = {"ok": True, "verified": bool(check), "reason": ""}
        except LLMError as e:
            msg = str(e)[:300]
            out[prov] = {"ok": not e.config_error, "verified": False,
                         "reason": msg if e.config_error else f"{msg} It will be checked again before any paid request."}
    return out


def check_limit_value(k: str, v):
    from .config import RAISABLE_LIMITS
    if k not in RAISABLE_LIMITS:
        return v
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise ApiError(400, f"{k} must be a number")
    if not math.isfinite(x) or x < 0:
        raise ApiError(400, f"{k} must be a finite number ≥ 0 (limits can be raised, never removed)")
    if k.endswith("_usd") and x > 1000:
        raise ApiError(400, f"{k} must be at most $1,000 per case")
    if k.startswith("max_") and x > 10000:
        raise ApiError(400, f"{k} must be at most 10,000 per case")
    return round(x, 2) if k.endswith("_usd") else int(x)


@route("PUT", "/api/settings")
def api_put_settings(h, body, **_):
    from .llm.openai_responses import REASONING_EFFORTS
    cur = db.get_setting("defaults", {}) or {}
    for k, v in body.items():
        if k not in DEFAULT_SETTINGS:
            continue
        if k == "coding_mode":
            v = check_mode(v, {**DEFAULT_SETTINGS, **cur}) or "single"
        elif k == "pause_before_coding":
            v = bool(v)
        elif k == "openai_reasoning_effort" and v not in REASONING_EFFORTS:
            raise ApiError(400, f"openai_reasoning_effort must be one of {', '.join(REASONING_EFFORTS)}")
        elif k in ("openai_reasoning_reserve_tokens", "openai_max_output_tokens"):
            try:
                v = int(v)
            except (TypeError, ValueError):
                raise ApiError(400, f"{k} must be a whole number")
            if not (1000 <= v <= 128000):
                raise ApiError(400, f"{k} must be between 1,000 and 128,000 tokens")
        else:
            v = check_limit_value(k, v)
        cur[k] = v
    db.set_setting("defaults", cur)
    return global_settings()


@route("PUT", "/api/pricing")
def api_put_pricing(h, body, **_):
    (DATA_DIR / "pricing.json").write_text(json.dumps(body, indent=2), encoding="utf-8")
    return load_pricing()


# ----------------------------------------------------------------------------- schema
@route("GET", "/api/schemas")
def api_schemas(h, **_):
    return db.q("SELECT id,label,codebook_label,workbook_label,created_at,active,parent_id,change_note FROM schema_versions ORDER BY id DESC")


@route("GET", "/api/schemas/{sid}")
def api_schema(h, sid, **_):
    r = db.q1("SELECT * FROM schema_versions WHERE id=?", (int(sid),))
    if not r:
        raise ApiError(404, "schema not found")
    s = json.loads(r.pop("schema_json"))
    return {**r, **s}


@route("POST", "/api/schemas")
def api_upload_schema(h, body, **_):
    up = DATA_DIR / "schemas"
    stamp = int(time.time())
    paths = {}
    for key in ("codebook", "workbook"):
        f = body.get(key)
        if not f:
            raise ApiError(400, f"{key} file required")
        name = re.sub(r"[^\w.\- ]", "_", f["filename"])
        p = up / f"{stamp}_{name}"
        p.write_bytes(base64.b64decode(f["data"]))
        paths[key] = p
    try:
        s = build_from_files(paths["codebook"], paths["workbook"])
    except Exception as e:
        raise ApiError(400, f"could not build schema: {e}")
    s["codebook_label"] = body["codebook"]["filename"]
    s["workbook_label"] = body["workbook"]["filename"] + s["workbook_label"][s["workbook_label"].find(" ["):]
    sid = save_schema(s, body.get("label") or f"{s['codebook_label']} + {s['workbook_label']}", activate=bool(body.get("activate")),
                      note="uploaded")
    return {"id": sid, "stats": s["stats"]}


@route("POST", "/api/schemas/{sid}/activate")
def api_activate(h, sid, **_):
    db.ex("UPDATE schema_versions SET active=CASE WHEN id=? THEN 1 ELSE 0 END", (int(sid),))
    return {"ok": True}


@route("PUT", "/api/schemas/{sid}/fields/{name}")
def api_edit_field(h, sid, name, body, **_):
    """Editing a rule never changes an existing version: it creates a new version (with a note) and activates it."""
    r = db.q1("SELECT * FROM schema_versions WHERE id=?", (int(sid),))
    s = json.loads(r["schema_json"])
    name = name.replace("%20", " ")
    f = next((x for x in s["fields"] if x["name"] == name), None)
    if not f:
        raise ApiError(404, "field not found")
    note = body.pop("change_note", "") or "edited in app"
    for k in ("definition", "type", "multi", "open_list", "codes", "missing_codes", "notes", "field_class", "open_options"):
        if k in body:
            f[k] = body[k]
    if body.get("resolve_issues"):
        f["issues"] = [i for i in f["issues"] if i not in body["resolve_issues"]]
        f.setdefault("resolved_issues", []).extend(body["resolve_issues"])
    if f.get("rule_missing") and (f.get("definition") or f.get("codes")):
        f["rule_missing"] = False
        f["issues"] = [i for i in f["issues"] if "No codebook definition" not in i]
    new_id = save_schema(s, f"{r['label']} (edited {time.strftime('%Y-%m-%d %H:%M')})", activate=True, parent_id=r["id"],
                         note=f"{name}: {note}")
    return {"id": new_id}


# ----------------------------------------------------------------------------- cases
@route("GET", "/api/cases")
def api_cases(h, **_):
    rows = db.q("SELECT * FROM cases ORDER BY id DESC")
    for c in rows:
        j = db.q1("SELECT id,status,stage,progress,message FROM jobs WHERE case_id=? ORDER BY id DESC LIMIT 1", (c["id"],))
        c["job"] = j
        c["n_sources"] = db.q1("SELECT COUNT(*) n FROM sources WHERE case_id=? AND fetch_status='ok'", (c["id"],))["n"]
        c["n_confirmed"] = db.q1("SELECT COUNT(*) n FROM reviews WHERE case_id=? AND action IN ('accepted','edited','cleared')", (c["id"],))["n"]
    return rows


@route("POST", "/api/providers/check")
def api_providers_check(h, body, **_):
    """Free, non-billable availability check for the providers of one mode (used before a case starts)."""
    s = global_settings()
    mode = check_mode(body.get("mode"), s)
    return {"mode": mode, "providers": provider_checks(mode, s) if mode and mode != "single" else {}}


@route("POST", "/api/cases")
def api_new_case(h, body, **_):
    if not body.get("name", "").strip():
        raise ApiError(400, "incident name is required")
    act = db.q1("SELECT id FROM schema_versions WHERE active=1")
    overrides = {k: v for k, v in (body.get("settings") or {}).items() if k in DEFAULT_SETTINGS}
    for k in list(overrides):
        overrides[k] = check_limit_value(k, overrides[k])
    # Coding provider chosen on the first form (D-036). Validated BEFORE anything is created or searched: the mode must
    # exist, its keys must be configured, the free availability check must pass, and the hard limits must cover at
    # least one worst-case request per selected provider. Without "mode" (older clients) the global default applies.
    mode = check_mode(body.get("mode"), {**global_settings(), **overrides})
    if mode and mode != "single":
        overrides["coding_mode"] = mode
        checks = provider_checks(mode, {**global_settings(), **overrides})
        bad = [v["reason"] for v in checks.values() if not v["ok"]]
        if bad:
            raise ApiError(400, "; ".join(bad) + ". Nothing was created or searched.")
        from .coding import minimum_request_check
        short = minimum_request_check(mode, {**global_settings(), **overrides}, spent=0.0, spent_openai=0.0)
        if short:
            raise ApiError(400, short + " Raise the limit or choose another mode. Nothing was created or searched.")
    if "pause_before_coding" in body:
        overrides["pause_before_coding"] = bool(body["pause_before_coding"])
    cid = db.insert("cases", {"name": body["name"].strip(), "location": body.get("location", "").strip(),
                              "date_text": body.get("date_text", "").strip(), "date_start": body.get("date_start", ""),
                              "date_end": body.get("date_end", ""), "details": body.get("details", ""),
                              "known_links": body.get("known_links", ""), "aliases": body.get("aliases", ""),
                              "schema_version_id": act["id"] if act else None, "status": "new", "identity_json": "{}",
                              "settings_json": json.dumps({**global_settings(), **overrides}), "created_at": time.time(),
                              "updated_at": time.time()})
    jid = jobs.enqueue(cid, "research", {"mode": mode} if mode else None) if body.get("start", True) else None
    return {"id": cid, "job_id": jid, "mode": mode}


@route("GET", "/api/cases/{cid}")
def api_case(h, cid, **_):
    c = db.q1("SELECT * FROM cases WHERE id=?", (int(cid),))
    if not c:
        raise ApiError(404, "case not found")
    c["identity"] = json.loads(c.pop("identity_json") or "{}")
    c["settings"] = json.loads(c.pop("settings_json") or "{}")
    return c


@route("PUT", "/api/cases/{cid}")
def api_edit_case(h, cid, body, **_):
    c = db.q1("SELECT * FROM cases WHERE id=?", (int(cid),))
    upd = {k: body[k] for k in ("name", "location", "date_text", "date_start", "date_end", "details", "known_links", "aliases") if k in body}
    if "settings" in body:
        st = json.loads(c["settings_json"] or "{}")
        st.update({k: v for k, v in body["settings"].items() if k in DEFAULT_SETTINGS})
        upd["settings_json"] = json.dumps(st)
    upd["updated_at"] = time.time()
    db.update("cases", int(cid), upd)
    return {"ok": True}


@route("POST", "/api/cases/{cid}/research")
def api_research(h, cid, body, **_):
    return {"job_id": jobs.enqueue(int(cid), "research", {"identity_confirmed": bool(body.get("identity_confirmed"))})}


@route("POST", "/api/cases/{cid}/recode")
def api_recode(h, cid, body, **_):
    c = db.q1("SELECT * FROM cases WHERE id=?", (int(cid),))
    st = {**DEFAULT_SETTINGS, **json.loads(c["settings_json"] or "{}")}
    params = {"variables": body.get("variables") or None, "approve_over_budget": bool(body.get("approve_over_budget")),
              "mode": check_mode(body.get("mode"), st)}
    return {"job_id": jobs.enqueue(int(cid), "recode", params)}


@route("GET", "/api/cases/{cid}/job")
def api_job(h, cid, **_):
    # The running job comes first, so its Stop buttons stay visible while a Resume job waits behind it.
    j = db.q1("SELECT * FROM jobs WHERE case_id=? ORDER BY (status='running') DESC, id DESC LIMIT 1", (int(cid),))
    if not j:
        return None
    j["state"] = json.loads(j.pop("state_json") or "{}")
    j["params"] = json.loads(j.pop("params_json") or "{}")
    j["provider_controls"] = {r["provider"]: r for r in db.q("SELECT * FROM provider_controls WHERE job_id=?", (j["id"],))}
    j["queued_after"] = db.q("SELECT id, kind, params_json FROM jobs WHERE case_id=? AND status='queued' AND id<>? ORDER BY id",
                             (int(cid), j["id"]))
    j["log"] = db.q("SELECT * FROM job_log WHERE job_id=? ORDER BY id DESC LIMIT 200", (j["id"],))[::-1]
    return j


@route("POST", "/api/jobs/{jid}/cancel")
def api_cancel(h, jid, **_):
    jobs.cancel(int(jid))
    return {"ok": True}


PROVIDER_NAMES = {"anthropic": "Claude", "openai": "OpenAI", "openai_compatible": "OpenAI-compatible"}
STOP_WARNING = ("A request already sent to the provider cannot be recalled: it may still finish and may still be billed; "
                "its result will be kept. Batches not yet sent will not be sent. The other provider is not affected.")


@route("POST", "/api/jobs/{jid}/providers/{prov}/stop")
def api_stop_provider(h, jid, prov, **_):
    """Stop ONE provider in a job: future batches of that provider are not sent; completed results are kept; the other
    provider keeps running. Checked by the job before every batch."""
    j = db.q1("SELECT * FROM jobs WHERE id=?", (int(jid),))
    if not j:
        raise ApiError(404, "no such job")
    if prov not in PROVIDER_NAMES:
        raise ApiError(400, "unknown provider")
    who = getattr(h, "user", None) or "user"
    db.ex("INSERT OR REPLACE INTO provider_controls (job_id, provider, stop_requested, requested_by, requested_at) "
          "VALUES (?,?,?,?,?)", (int(jid), prov, 1, who, time.time()))
    db.insert("job_log", {"job_id": int(jid), "at": time.time(), "stage": "coding", "level": "warn",
                          "message": f"Stop {PROVIDER_NAMES[prov]} requested by {who}. {STOP_WARNING}"})
    return {"ok": True, "warning": STOP_WARNING}


@route("POST", "/api/jobs/{jid}/providers/{prov}/resume")
def api_resume_provider(h, jid, prov, **_):
    """Resume ONE provider. If the job has not finished that provider yet, the stop flag is simply cleared. If the
    provider already stopped, a follow-up job codes only its stopped variables, in the same comparison group."""
    j = db.q1("SELECT * FROM jobs WHERE id=?", (int(jid),))
    if not j:
        raise ApiError(404, "no such job")
    if prov not in PROVIDER_NAMES:
        raise ApiError(400, "unknown provider")
    who = getattr(h, "user", None) or "user"
    db.ex("UPDATE provider_controls SET stop_requested=0, requested_by=?, requested_at=? WHERE job_id=? AND provider=?",
          (who, time.time(), int(jid), prov))
    st = json.loads(j["state_json"] or "{}")
    pr = (st.get("provider_runs") or {}).get(prov) or {}
    if j["status"] in ("queued", "running") and pr.get("status") in (None, "pending", "running"):
        db.insert("job_log", {"job_id": int(jid), "at": time.time(), "stage": "coding", "level": "info",
                              "message": f"Resume {PROVIDER_NAMES[prov]} by {who}: stop request withdrawn before it took effect"})
        return {"ok": True, "resumed_in_place": True}
    gid = st.get("group_id") or ((st.get("coding_report") or {}).get("group_id"))
    if not gid:
        raise ApiError(400, "this job has no coding run to resume")
    latest = {}
    for r in db.q("SELECT variable, status FROM suggestions WHERE case_id=? AND group_id=? AND provider=? ORDER BY id",
                  (j["case_id"], gid, prov)):
        latest[r["variable"]] = r["status"]
    todo = sorted(v for v, stt in latest.items() if stt == "stopped")
    if not todo:
        raise ApiError(400, f"{PROVIDER_NAMES[prov]} has no stopped variables in this run")
    params = {"resume": {"provider": prov, "role": "reviewer" if pr.get("role") == "reviewer" else "independent",
                         "group_id": gid, "variables": todo,
                         "mode": st.get("coding_mode") or "single", "from_job": int(jid)}}
    new_id = jobs.enqueue(j["case_id"], "recode", params, behind_active=True)
    db.insert("job_log", {"job_id": int(jid), "at": time.time(), "stage": "coding", "level": "info",
                          "message": f"Resume {PROVIDER_NAMES[prov]} by {who}: job {new_id} will code {len(todo)} stopped "
                                     f"variable(s); completed results are not re-sent"})
    return {"ok": True, "job_id": new_id, "variables": todo}


@route("POST", "/api/cases/{cid}/limits")
def api_case_limits(h, cid, body, **_):
    """Set this case's limits to explicit values (raise or lower); every change is recorded in limit_changes."""
    from .config import RAISABLE_LIMITS
    c = db.q1("SELECT * FROM cases WHERE id=?", (int(cid),))
    if not c:
        raise ApiError(404, "no such case")
    st = json.loads(c["settings_json"] or "{}")
    who = getattr(h, "user", None) or "user"
    changed = {}
    for k, v in (body.get("limits") or {}).items():
        if k not in RAISABLE_LIMITS:
            raise ApiError(400, f"{k} is not a case limit")
        nv = check_limit_value(k, v)
        old = st.get(k, DEFAULT_SETTINGS[k])
        if nv != old:
            st[k] = nv
            changed[k] = nv
            db.insert("limit_changes", {"case_id": int(cid), "job_id": None, "key": k, "old_value": str(old),
                                        "new_value": str(nv), "changed_by": who, "reason": body.get("reason") or "set on case",
                                        "at": time.time()})
    db.update("cases", int(cid), {"settings_json": json.dumps(st)})
    return {"ok": True, "changed": changed, "limits": {k: st.get(k, DEFAULT_SETTINGS[k]) for k in RAISABLE_LIMITS}}


@route("POST", "/api/jobs/{jid}/resume")
def api_resume(h, jid, body, **_):
    j = db.q1("SELECT * FROM jobs WHERE id=?", (int(jid),))
    upd = {}
    if body.get("identity_year"):
        c = db.q1("SELECT * FROM cases WHERE id=?", (j["case_id"],))
        if body["identity_year"] not in (c["date_text"] or ""):
            db.update("cases", c["id"], {"date_text": f"{c['date_text']} {body['identity_year']}".strip()})
        upd["identity_confirmed"] = True
    if body.get("identity_confirmed"):
        upd["identity_confirmed"] = True
    if body.get("coding_approved") or body.get("approve_over_budget"):
        upd["coding_approved"] = True  # the owner saw the post-research estimate and chose to start paid coding
    def set_case_limit(key: str, new_value, why: str):
        c = db.q1("SELECT * FROM cases WHERE id=?", (j["case_id"],))
        st = json.loads(c["settings_json"])
        new_value = check_limit_value(key, new_value)
        old = st.get(key, DEFAULT_SETTINGS[key])
        st[key] = new_value
        db.update("cases", c["id"], {"settings_json": json.dumps(st)})
        who = getattr(h, "user", None) or "user"
        msg = (f"case budget changed from ${float(old):.2f} to ${float(new_value):.2f} by {who} ({why})" if key == "budget_usd"
               else f"case limit {key} changed from {old} to {new_value} by {who} ({why})")
        db.insert("job_log", {"job_id": j["id"], "at": time.time(), "stage": "coding", "level": "warn", "message": msg})
        db.insert("limit_changes", {"case_id": c["id"], "job_id": j["id"], "key": key, "old_value": str(old),
                                    "new_value": str(new_value), "changed_by": who, "reason": why, "at": time.time()})

    def set_case_budget(new_budget: float, why: str):
        set_case_limit("budget_usd", new_budget, why)

    if body.get("approve_over_budget"):
        # Approval raises the case budget to exactly what is needed (spent so far + worst-case estimate).
        # It never removes the limit.
        from .coding import case_spent
        est = (json.loads(j["state_json"] or "{}").get("estimate") or {})
        if est.get("cost_high") is None:
            raise ApiError(400, "no cost estimate is available to approve; resume the job to re-estimate")
        st_job = json.loads(j["state_json"] or "{}")
        needs = st_job.get("limit_needs") or {}
        if "budget_usd" in needs or not needs:
            needed = math.ceil((case_spent(j["case_id"]) + float(est["cost_high"])) * 100) / 100
            set_case_budget(needed, "approved the worst-case estimate")
        for key, nd in needs.items():
            if key != "budget_usd":
                set_case_limit(key, nd["needed"], "approved the estimate for this run")
    if body.get("budget_usd") is not None and body.get("budget_usd") != "":
        try:
            b = float(body["budget_usd"])
        except (TypeError, ValueError):
            raise ApiError(400, "budget must be a number")
        if not (0 <= b <= 1000):
            raise ApiError(400, "budget must be between $0 and $1,000 per case")
        set_case_budget(b, "set manually")
    for key, val in (body.get("limits") or {}).items():
        from .config import RAISABLE_LIMITS
        if key in RAISABLE_LIMITS and key != "budget_usd":
            set_case_limit(key, val, "set manually")
    if body.get("manual_only"):
        c = db.q1("SELECT * FROM cases WHERE id=?", (j["case_id"],))
        st = json.loads(c["settings_json"])
        st["model_provider"] = "none"
        db.update("cases", c["id"], {"settings_json": json.dumps(st)})
    jobs.resume(int(jid), upd)
    return {"ok": True}


@route("GET", "/api/cases/{cid}/estimate")
def api_estimate(h, cid, query=None, **_):
    from .coding import case_ledger, estimate, limit_needs, resolve_plan
    query = query or {}
    c = db.q1("SELECT * FROM cases WHERE id=?", (int(cid),))
    st = {**DEFAULT_SETTINGS, **json.loads(c["settings_json"] or "{}")}
    mode = check_mode((query.get("mode") or [None])[0], st)
    variables = [v for v in (query.get("variables") or [""])[0].split(",") if v] or None
    try:
        plan, mode, err = resolve_plan(st, mode)
        if err:
            raise ApiError(400, err)
        est = estimate(c, st, variables, plan=plan or None)
        led = case_ledger(int(cid))
        est.update({"mode": mode, "limit_needs": limit_needs(int(cid), st, est) if plan else {},
                    "ledger": {"spent_total": round(led["spent_total"], 4),
                               "spent_by": {k: round(v, 4) for k, v in led["spent_by"].items()},
                               "attempts_by": led["attempts_by"], "attempts_total": led["attempts_total"]},
                    "limits": {k: st.get(k) for k in ("budget_usd", "openai_budget_usd", "max_openai_attempts_per_case",
                                                      "max_model_attempts_per_case")},
                    "manual": not plan})
        return est
    except ApiError:
        raise
    except Exception as e:
        traceback.print_exc()
        raise ApiError(500, f"cost estimate failed: {type(e).__name__}: {e}")


@route("GET", "/api/estimate_preview")
def api_estimate_preview(h, query, **_):
    """Stage-1 (before research) estimate for the first form, per coding mode (D-036). It cannot know the sources yet,
    so the provider lines are a PRELIMINARY RANGE whose high end is the WORST-CASE RESERVE used by the budget check.
    One shared search line, counted once whatever the mode. Optional query overrides: budget_usd, openai_budget_usd,
    max_queries (the values typed in the form; they are validated, never trusted as cost totals)."""
    from .coding import preliminary_estimate
    s = global_settings()
    query = query or {}
    for k in ("budget_usd", "openai_budget_usd", "max_queries"):
        v = (query.get(k) or [None])[0]
        if v not in (None, ""):
            try:
                s[k] = check_limit_value(k, float(v)) if k != "max_queries" else max(1, int(float(v)))
            except (TypeError, ValueError):
                raise ApiError(400, f"{k} must be a number")
    mode = check_mode((query.get("mode") or [None])[0], s) or s.get("coding_mode") or "single"
    return preliminary_estimate(s, mode)


# ----------------------------------------------------------------------------- sources
@route("GET", "/api/cases/{cid}/sources")
def api_sources(h, cid, **_):
    return db.q("SELECT * FROM sources WHERE case_id=? ORDER BY id", (int(cid),))


@route("POST", "/api/cases/{cid}/sources")
def api_add_source(h, cid, body, **_):
    from .research import ingest_manual
    kind = body.get("kind")
    payload = dict(body)
    if kind == "file":
        name = re.sub(r"[^\w.\- ]", "_", body["filename"])
        p = DATA_DIR / "files" / f"upload_{int(time.time()*1000)}_{name}"
        p.write_bytes(base64.b64decode(body["data"]))
        payload = {"filename": body["filename"], "path": str(p), "title": body.get("title"), "url": body.get("url", "")}
    sid = ingest_manual(int(cid), kind, payload)
    db.update("sources", sid, {"added_by": getattr(h, "user", None)})
    return db.q1("SELECT * FROM sources WHERE id=?", (sid,))


@route("PATCH", "/api/sources/{sid}")
def api_patch_source(h, sid, body, **_):
    s = db.q1("SELECT * FROM sources WHERE id=?", (int(sid),))
    upd = {}
    if "excluded" in body:
        upd["excluded"] = 1 if body["excluded"] else 0
        upd["exclude_reason"] = body.get("reason", "")
    if body.get("relevance_status") in ("relevant", "uncertain", "irrelevant"):
        upd["relevance_status"] = body["relevance_status"]
        upd["relevance_reason"] = f"set by reviewer: {body.get('reason','')}".strip()
    if body.get("source_type"):
        upd["source_type"] = body["source_type"]
    db.update("sources", int(sid), upd)
    affected = []
    if upd.get("excluded") == 1 or upd.get("relevance_status") == "irrelevant":
        for sg in db.q("SELECT id, variable, evidence_json FROM suggestions WHERE case_id=? AND stale=0", (s["case_id"],)):
            ev = json.loads(sg["evidence_json"] or "[]")
            if any(e.get("source_id") == int(sid) for e in ev):
                db.update("suggestions", sg["id"], {"stale": 1, "stale_reason": f"cites excluded source S{sid}"})
                affected.append(sg["variable"])
    return {"ok": True, "affected_variables": sorted(set(affected))}


@route("GET", "/api/sources/{sid}/passages")
def api_passages(h, sid, **_):
    src = db.q1("SELECT * FROM sources WHERE id=?", (int(sid),))
    return {"source": src, "passages": db.q("SELECT id,seq,page,para,text FROM passages WHERE source_id=? ORDER BY seq", (int(sid),))}


@route("GET", "/api/cases/{cid}/searches")
def api_searches(h, cid, **_):
    qs = db.q("SELECT * FROM search_queries WHERE case_id=? ORDER BY id", (int(cid),))
    fetched = {r["url"] for r in db.q("SELECT url FROM sources WHERE case_id=?", (int(cid),))}
    for q in qs:
        q["results"] = db.q("SELECT url,title,snippet,rank,published,identity_score FROM search_results WHERE query_id=? ORDER BY rank", (q["id"],))
        for r in q["results"]:
            r["fetched"] = r["url"] in fetched
    return qs


@route("GET", "/api/cases/{cid}/evidence_search")
def api_evidence_search(h, cid, query, **_):
    from .retrieval import CorpusIndex, load_case_passages
    qtext = (query.get("q") or [""])[0]
    from .retrieval import get_index
    idx = get_index(int(cid))
    return {"method": f"BM25 + {idx.semantic_method}", "hits": idx.search(qtext, k=int((query.get("k") or ["15"])[0]))}


# ----------------------------------------------------------------------------- results & review
@route("GET", "/api/cases/{cid}/results")
def api_results(h, cid, **_):
    from .export import case_results
    r = case_results(int(cid))
    r["sources"] = list(r["sources"].values())
    return r


@route("POST", "/api/cases/{cid}/review")
def api_review(h, cid, body, **_):
    from .coding import schema_for_case
    from .validator import split_values
    cid = int(cid)
    var, action = body["variable"], body["action"]
    case = db.q1("SELECT * FROM cases WHERE id=?", (cid,))
    f = next((x for x in schema_for_case(case)["fields"] if x["name"] == var), None)
    if not f:
        raise ApiError(404, "unknown variable")
    from .coding import provider_of, suggestion_sets
    sets = suggestion_sets(cid).get(var)
    sugg = sets["display"] if sets else None
    old = db.q1("SELECT * FROM reviews WHERE case_id=? AND variable=?", (cid, var))
    reason = (body.get("reason") or "").strip()
    if body.get("suggestion_id"):
        pick = db.q1("SELECT s.*, r.model AS run_model FROM suggestions s LEFT JOIN runs r ON r.id=s.run_id "
                     "WHERE s.id=? AND s.case_id=? AND s.variable=?", (int(body["suggestion_id"]), cid, var))
        if not pick:
            raise ApiError(400, "that suggestion does not belong to this case and variable")
        sugg = pick
    if action == "accept":
        if not sugg:
            raise ApiError(400, "nothing to accept")
        comp = sets.get("comparison") if sets else None
        if comp and comp["status"] != "model_agreement" and not body.get("suggestion_id"):
            raise ApiError(400, "the providers' suggestions differ — choose which suggestion to accept, or edit the value")
        if sugg["status"] in ("model_error", "validation_failed"):
            raise ApiError(400, "an invalid provider output cannot be accepted — edit the value instead")
        value = sugg["value"] or ""
        action_name = "accepted"
    elif action == "edit":
        value = str(body.get("value", "")).strip()
        if not reason:
            raise ApiError(400, "a reason is required when editing a value")
        if f["type"] == "categorical" and value:
            allowed = {c["code"].upper(): c["code"] for c in f["codes"]} | {m.upper(): m for m in f.get("missing_codes", [])}
            parts = split_values(value)
            bad = [p for p in parts if p.upper() not in allowed]
            if bad:
                raise ApiError(400, f"not a codebook code for {var}: {', '.join(bad)}")
            if not f.get("multi") and len(parts) > 1:
                raise ApiError(400, f"{var} is single-select in the active codebook")
            value = ", ".join(allowed[p.upper()] for p in parts)
        action_name = "edited"
    elif action == "clear":
        value, action_name = "", "cleared"
        if not reason:
            raise ApiError(400, "a reason is required when clearing")
    elif action == "defer":
        value, action_name = (old["value"] if old else ""), "deferred"
    elif action == "reset":
        db.ex("DELETE FROM reviews WHERE case_id=? AND variable=?", (cid, var))
        db.insert("review_history", {"case_id": cid, "variable": var, "old_value": old["value"] if old else None, "new_value": None,
                                     "action": "reset", "reason": reason, "suggestion_id": sugg["id"] if sugg else None, "at": time.time(),
                                     "reviewer": getattr(h, "user", None)})
        return {"ok": True}
    else:
        raise ApiError(400, "unknown action")
    who = getattr(h, "user", None)
    if sugg and action_name == "accepted" and sugg.get("display_kind") == "two_providers":
        sp = "anthropic+openai"  # both providers independently gave this value; the human accepted it
    else:
        sp = provider_of(dict(sugg)) if (sugg and action_name == "accepted") else None
    db.ex("INSERT OR REPLACE INTO reviews (case_id,variable,value,action,reason,suggestion_id,updated_at,reviewer,source_provider) "
          "VALUES (?,?,?,?,?,?,?,?,?)",
          (cid, var, value, action_name, reason, sugg["id"] if sugg else None, time.time(), who, sp))
    db.insert("review_history", {"case_id": cid, "variable": var, "old_value": old["value"] if old else None, "new_value": value,
                                 "action": action_name, "reason": reason, "suggestion_id": sugg["id"] if sugg else None, "at": time.time(),
                                 "reviewer": who, "source_provider": sp})
    return {"ok": True}


@route("GET", "/api/cases/{cid}/bulk_agreements")
def api_bulk_agreements(h, cid, **_):
    """Variables eligible for bulk confirmation of independent model agreement. Read-only."""
    from .agreement import eligible_summary
    return eligible_summary(int(cid))


@route("POST", "/api/cases/{cid}/bulk_confirm")
def api_bulk_confirm(h, cid, body, **_):
    """Write Human final for the variables the reviewer left checked — only those still eligible at this moment."""
    from .agreement import AcknowledgementRequired, bulk_confirm
    variables = body.get("variables")
    if not isinstance(variables, list) or not variables:
        raise ApiError(400, "choose at least one variable to confirm")
    if not body.get("confirmed"):
        raise ApiError(400, "explicit confirmation is required")
    try:
        return bulk_confirm(int(cid), [str(v) for v in variables], getattr(h, "user", None),
                            acknowledged_cross_version=bool(body.get("acknowledged_cross_version")))
    except AcknowledgementRequired as e:
        raise ApiError(400, str(e))


@route("GET", "/api/cases/{cid}/version_diff")
def api_version_diff(h, cid, query, **_):
    """Version-difference panel (D-035 retained, D-036): for one variable, the Claude and OpenAI results' evidence,
    codebook, prompt/analysis and model versions, run dates, cache status, which dimensions differ, and the sources
    and passages added / removed / changed between the two evidence versions. Read-only."""
    from .coding import suggestion_sets, version_differences
    var = (query.get("variable") or [None])[0]
    cells = ((suggestion_sets(int(cid)).get(var) or {}).get("cells") or {})
    rows = {k: (cells.get(k) or {}).get("row") for k in ("anthropic", "openai")}
    if not all(rows.values()):
        raise ApiError(400, "both providers need a result for this variable")

    def run(r):
        return db.q1("SELECT * FROM runs WHERE id=?", (r.get("run_id"),)) or {}

    def snap(sid):
        return db.q1("SELECT * FROM evidence_snapshots WHERE id=?", (sid,)) if sid else None

    def spec(pid):
        return db.q1("SELECT * FROM analysis_specs WHERE id=?", (pid,)) if pid else None
    side = {}
    for k, r in rows.items():
        ru = run(r)
        side[k] = {"provider": k, "model": r.get("model") or ru.get("model"), "run_id": ru.get("id"),
                   "original_run_id": r.get("cache_source_run_id") or ru.get("id"),
                   "generated_at": r.get("generated_at") or r.get("created_at"), "cache_status": r.get("cache_status") or "new",
                   "evidence_snapshot_id": r.get("evidence_snapshot_id"), "analysis_spec_id": r.get("analysis_spec_id"),
                   "codebook_version": ru.get("schema_version_id"), "prompt_version": ru.get("prompt_version"),
                   "value": r.get("value"), "status": r.get("status")}
    a, b = rows["anthropic"], rows["openai"]
    out = {"variable": var, "claude": side["anthropic"], "openai": side["openai"],
           "differences": version_differences(a, b, run(a), run(b))}
    sa, sb = snap(a.get("evidence_snapshot_id")), snap(b.get("evidence_snapshot_id"))
    if sa and sb and sa["id"] != sb["id"]:
        s1, s2 = set(json.loads(sa["sources_json"] or "[]")), set(json.loads(sb["sources_json"] or "[]"))
        out["sources"] = {"only_in_claude_version": sorted(s1 - s2), "only_in_openai_version": sorted(s2 - s1)}
        if sa.get("passages_json") and sb.get("passages_json"):
            p1, p2 = json.loads(sa["passages_json"]), json.loads(sb["passages_json"])
            out["passages"] = {"only_in_claude_version": sorted(set(p1) - set(p2)),
                               "only_in_openai_version": sorted(set(p2) - set(p1)),
                               "changed_text": sorted(x for x in set(p1) & set(p2) if p1[x] != p2[x])}
        else:
            out["passages"] = None  # one snapshot predates the passage list
    elif not (sa and sb):
        out["sources"] = None  # at least one result predates evidence versioning ("version not recorded")
    qa, qb = spec(a.get("analysis_spec_id")), spec(b.get("analysis_spec_id"))
    if qa and qb and qa["id"] != qb["id"]:
        out["analysis"] = {k: [qa.get(k), qb.get(k)] for k in ("prompt_version", "rules_sha", "response_schema_version",
                                                               "batching_json", "codebook_version") if qa.get(k) != qb.get(k)}
    return out


@route("GET", "/api/cases/{cid}/history")
def api_history(h, cid, query, **_):
    var = (query.get("variable") or [None])[0]
    sugg = db.q("SELECT id,run_id,variable,value,status,created_at,stale,stale_reason FROM suggestions WHERE case_id=? AND variable=? ORDER BY id",
                (int(cid), var))
    rev = db.q("SELECT * FROM review_history WHERE case_id=? AND variable=? ORDER BY id", (int(cid), var))
    return {"suggestions": sugg, "reviews": rev}


@route("GET", "/api/cases/{cid}/usage")
def api_usage(h, cid, **_):
    rows = db.q("SELECT * FROM usage WHERE case_id=? ORDER BY id", (int(cid),))
    tot = {"model_usd": sum(r["cost_usd"] or 0 for r in rows if r["kind"] == "model"),
           "anthropic_usd": sum(r["cost_usd"] or 0 for r in rows if r["kind"] == "model" and r["provider"] == "anthropic"),
           "openai_usd": sum(r["cost_usd"] or 0 for r in rows if r["kind"] == "model" and r["provider"] == "openai"),
           "combined_usd": sum(r["cost_usd"] or 0 for r in rows),
           "reasoning_tokens": sum(r.get("reasoning_tokens") or 0 for r in rows),
           "search_usd": sum(r["cost_usd"] or 0 for r in rows if r["kind"] == "search"),
           "search_queries_billed": sum(1 for r in rows if r["kind"] == "search"),
           "search_price_unknown": any(r["kind"] == "search" and r["cost_usd"] is None for r in rows),
           "input_tokens": sum(r["input_tokens"] or 0 for r in rows), "output_tokens": sum(r["output_tokens"] or 0 for r in rows)}
    calls = db.q("SELECT id, run_id, group_id, provider, model, role, batch_no, n_batches, status, incomplete_reason, error, "
                 "http_attempts, request_id, input_tokens, cached_input_tokens, output_tokens, reasoning_tokens, "
                 "max_output_tokens, cost_usd, cost_estimated, cache_status, duration_s, at FROM model_calls "
                 "WHERE case_id=? ORDER BY id", (int(cid),))
    from .coding import case_ledger
    led = case_ledger(int(cid))
    return {"rows": rows, "totals": tot, "runs": db.q("SELECT * FROM runs WHERE case_id=? ORDER BY id", (int(cid),)),
            "model_calls": calls, "attempts": {"by_provider": led["attempts_by"], "total": led["attempts_total"]}}


# ----------------------------------------------------------------------------- export (binary)
def export_response(h, cid, query):
    from . import export
    fmt = (query.get("format") or ["xlsx"])[0]
    unrev = (query.get("unreviewed") or ["0"])[0] == "1"
    c = db.q1("SELECT * FROM cases WHERE id=?", (int(cid),))
    base = re.sub(r"[^\w\-]+", "_", c["name"])[:40] + ("_UNREVIEWED" if unrev else "_reviewed")
    if fmt == "tsv":
        return h.send_bytes(export.tsv(int(cid), unrev).encode("utf-8"), "text/tab-separated-values; charset=utf-8", f"{base}.tsv")
    if fmt == "json":
        return h.send_bytes(json.dumps(export.json_export(int(cid), unrev), indent=2, default=str).encode(), "application/json",
                            f"{base}.json")
    if fmt == "caserow":
        import io
        import openpyxl
        from .export import _cell_value, case_results, export_value
        res = case_results(int(cid))
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "WFD_Cases"
        ws.append([r["raw_header"] for r in res["rows"]])
        ws.append([_cell_value(export_value(r, unrev)[0], r["type"]) for r in res["rows"]])
        buf = io.BytesIO()
        wb.save(buf)
        return h.send_bytes(buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", f"{base}_case_row.xlsx")
    return h.send_bytes(export.xlsx(int(cid), unrev), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", f"{base}.xlsx")


# ----------------------------------------------------------------------------- handler
class Handler(BaseHTTPRequestHandler):
    server_version = "WFDCodingAssistant/0.1"

    def log_message(self, fmt, *args):
        if os.environ.get("WFD_VERBOSE"):
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                                                    "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        for h in getattr(self, "_extra_headers", []):
            self.send_header(*h)
        super().end_headers()

    def client_ip(self) -> str:
        # Render sits behind Cloudflare, which sets CF-Connecting-IP / True-Client-IP and overwrites any value a client
        # sends. The first X-Forwarded-For entry is client-controlled, so it is never trusted.
        if os.environ.get("WFD_TRUST_PROXY"):
            for hdr in ("CF-Connecting-IP", "True-Client-IP"):
                v = (self.headers.get(hdr) or "").strip()
                if v:
                    return v[:64]
        return self.client_address[0]

    def is_https(self) -> bool:
        return self.headers.get("X-Forwarded-Proto", "").lower() == "https" or bool(os.environ.get("WFD_SECURE_COOKIE"))

    def send_json(self, obj, status=200):
        data = json.dumps(obj, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def send_bytes(self, data: bytes, ctype: str, filename: str | None = None):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(data)

    def _dispatch(self, method):
        u = urlparse(self.path)
        path, query = u.path, parse_qs(u.query)
        self._extra_headers = []
        try:
            if path == "/healthz":
                return self.send_json({"ok": True})
            if path.startswith("/api/") and method in ("POST", "PUT", "PATCH") and \
                    not (self.headers.get("Content-Type") or "").startswith("application/json"):
                raise ApiError(415, "requests must be sent as JSON")
            if path == "/api/login" and method == "POST":
                n = int(self.headers.get("Content-Length") or 0)
                b = json.loads(self.rfile.read(min(n, 10000)) or b"{}") if n else {}
                if not auth.enabled():
                    return self.send_json({"ok": True, "user": "local"})
                ok, msg = auth.check_login(self.client_ip(), str(b.get("name", ""))[:80], str(b.get("password", "")))
                if not ok:
                    raise ApiError(401, msg)
                name = str(b["name"]).strip()[:80]
                self._extra_headers.append(("Set-Cookie", auth.set_cookie_header(auth.make_token(name), self.is_https())))
                return self.send_json({"ok": True, "user": name})
            if path == "/api/logout" and method == "POST":
                self._extra_headers.append(("Set-Cookie", auth.set_cookie_header("", self.is_https(), clear=True)))
                return self.send_json({"ok": True})
            self.user = auth.current_user(self.headers)
            if path == "/api/me":
                return self.send_json({"user": self.user, "login_required": auth.enabled()})
            if path.startswith("/api/") and not self.user:
                raise ApiError(401, "login required")
            if path.startswith("/api/"):
                m = re.match(r"^/api/cases/(\d+)/export$", path)
                if m and method == "GET":
                    return export_response(self, m.group(1), query)
                body = {}
                if method in ("POST", "PUT", "PATCH"):
                    n = int(self.headers.get("Content-Length") or 0)
                    if n > 120 * 1024 * 1024:
                        raise ApiError(413, "upload too large (max ~80 MB file)")
                    raw = self.rfile.read(n) if n else b"{}"
                    body = json.loads(raw or b"{}")
                for mth, rx, fn in ROUTES:
                    if mth == method:
                        mm = rx.match(path)
                        if mm:
                            return self.send_json(fn(self, body=body, query=query, **mm.groupdict()))
                raise ApiError(404, f"no route {method} {path}")
            if method != "GET":
                raise ApiError(405, "method not allowed")
            fp = (WEB / (path.lstrip("/") or "index.html")).resolve()
            if not str(fp).startswith(str(WEB.resolve())) or not fp.is_file():
                fp = WEB / "index.html"
            ctype = mimetypes.guess_type(str(fp))[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype in ("application/javascript",):
                ctype += "; charset=utf-8"
            return self.send_bytes(fp.read_bytes(), ctype)
        except ApiError as e:
            return self.send_json({"error": e.msg}, e.status)
        except Exception as e:
            traceback.print_exc()
            return self.send_json({"error": f"{type(e).__name__}: {e}"}, 500)

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PUT(self):
        self._dispatch("PUT")

    def do_PATCH(self):
        self._dispatch("PATCH")


def main():
    host = os.environ.get("WFD_HOST", "127.0.0.1")
    port = int(os.environ.get("WFD_PORT") or os.environ.get("PORT") or "8765")
    if host not in ("127.0.0.1", "localhost", "::1") and not auth.enabled():
        print("Refusing to start: WFD_HOST makes the app reachable from other computers, but no WFD_PASSWORD is set.\n"
              "Set WFD_PASSWORD (a long team password) in the environment or .env, or use WFD_HOST=127.0.0.1.")
        sys.exit(2)
    db.conn()
    bootstrap_schema()
    jobs.start_worker()
    srv = ThreadingHTTPServer((host, port), Handler)
    print(f"WFD Coding Assistant running at http://{host}:{port}  (data: {DATA_DIR}; login {'ON' if auth.enabled() else 'off — local only'})")
    print("Press Ctrl+C to stop.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
