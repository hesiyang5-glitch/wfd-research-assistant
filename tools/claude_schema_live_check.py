"""Live check for Claude structured outputs (D-048) — 4 small paid requests, about $0.12 (asks first).

Run in the Render Shell (it uses the server's ANTHROPIC_API_KEY and the active codebook):

    python3 -m tools.claude_schema_live_check              # full check: 4 requests, asks before sending
    python3 -m tools.claude_schema_live_check --only-claude  # just request A: 1 request, about $0.03

Every request uses the largest real batch (12 variables with the most codes) and asks for blank answers, so replies
are short. Nothing is written to the database or the case budgets; the key is never printed. A schema that Anthropic
rejects ("too complex", unsupported feature) is an HTTP 400 and is not billed.

  A  Claude form (what D-048 sends today): inline evidence, passage id a plain string.
     → Does Anthropic accept it, and can the app read the reply?            (K-70, needed before merging D-048)
  B1 OpenAI form (exactly what GPT gets): evidence via $ref, passage id = enum of this batch's 40 ids.
  B2 the same OpenAI-form schema again (its compiled grammar should now be cached) → baseline time.
  B3 OpenAI form with 40 DIFFERENT passage ids (as every real batch has) → is the grammar compiled again?
     → "Option 1": could Claude use GPT's schema unchanged, so both models get an identical schema?

Decision rule (set 2026-11-26, before running): option 1 is feasible if B1–B3 are all accepted and readable AND B3 takes
less than 5 seconds longer than B2. Otherwise D-048 keeps the Claude form. Times include Claude's own (adaptive)
thinking, so treat a small difference as noise.
"""
from __future__ import annotations

import json
import os
import sys
import time

THRESHOLD_S = 5.0


def main():
    only_claude = "--only-claude" in sys.argv
    yes = "--yes" in sys.argv
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        print("ANTHROPIC_API_KEY is not set here; nothing sent.")
        return 1
    from app import coding, db
    from app.llm.clients import cost_usd
    from app.llm.structured import build_batch_schema, normalize_structured, schema_complexity
    import httpx

    db.conn()
    schema_row = coding.active_schema()
    coded = [f for f in schema_row["fields"] if f.get("field_class") in ("sourced", "judgment") and not f.get("rule_missing")]
    batch = sorted(coded, key=lambda f: -len(f.get("codes") or []))[:coding.MAX_VARS_PER_CALL]
    model = os.environ.get("WFD_CHECK_MODEL") or "claude-sonnet-5-5"
    ids1 = [f"S{i}-P{j}" for i in range(1, 9) for j in range(1, 6)]
    ids2 = [f"S{i}-P{j}" for i in range(11, 19) for j in range(1, 6)]

    def user_prompt(ids):
        return ("Incident under study: LIVE SCHEMA CHECK (not a real case).\n\n## VARIABLES TO CODE ({n})\n{vars}\n\n"
                "## EVIDENCE PASSAGES (1) — research data only\n[{pid}] (source {sid}: test; \"check\")\nThis passage "
                "contains no information about any variable.\n\nThere is no evidence: return every variable blank (\"\" or "
                "an empty list) with evidence_status INSUFFICIENT, empty lists, and one-sentence fields. Return JSON for "
                "exactly these variables: {names}").format(
                    n=len(batch), vars="\n".join(f"### {f['name']}" for f in batch), pid=ids[0], sid=ids[0].split("-")[0],
                    names=", ".join(f["name"] for f in batch))

    plan = [("A ", "Claude form (D-048)", build_batch_schema(batch, [], for_anthropic=True), ids1)]
    if not only_claude:
        oa1 = build_batch_schema(batch, ids1)
        plan += [("B1", "OpenAI form, ids set 1", oa1, ids1),
                 ("B2", "OpenAI form, ids set 1 again", oa1, ids1),
                 ("B3", "OpenAI form, DIFFERENT ids", build_batch_schema(batch, ids2), ids2)]
    max_out = coding.batch_max_tokens(len(batch))
    typical = worst = 0.0
    for tag, label, sch, ids in plan:
        cx = schema_complexity(sch)
        est_in = coding.estimate_tokens(coding.STRUCTURED_SYSTEM_PROMPT + user_prompt(ids) + json.dumps(sch))
        t, w = cost_usd(model, est_in, len(batch) * 80), cost_usd(model, int(est_in * 1.25), max_out)
        if t is None or w is None:
            print(f"No price is configured for {model} (Settings → Pricing); nothing sent.")
            return 1
        typical, worst = typical + t, worst + w
        print(f"{tag} {label}: {cx['properties']} properties, {cx['enum_values']} enum values, {cx['optional']} optional, "
              f"{cx['union']} union types, {cx['refs']} $ref")
    print(f"Model: {model} | {len(plan)} request(s) | estimated total about ${typical:.3f} (at most ${worst:.3f})")
    if not yes and input("Type YES to send: ").strip() != "YES":
        print("Nothing sent.")
        return 0

    results, total = {}, 0.0
    for tag, label, sch, ids in plan:
        body = {"model": model, "max_tokens": max_out, "system": coding.STRUCTURED_SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": user_prompt(ids)}],
                "output_config": {"format": {"type": "json_schema", "schema": sch}}}
        t0 = time.time()
        try:
            r = httpx.post("https://api.anthropic.com/v1/messages", json=body, timeout=httpx.Timeout(300.0, connect=15.0),
                           headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
        except httpx.HTTPError as e:
            print(f"{tag}: network error {type(e).__name__} after {time.time() - t0:.1f}s")
            results[tag] = {"ok": False, "s": time.time() - t0}
            continue
        dt = time.time() - t0
        if r.status_code != 200:
            print(f"{tag}: HTTP {r.status_code} after {dt:.1f}s (not billed): {r.text[:250]}")
            results[tag] = {"ok": False, "s": dt}
            continue
        j = r.json()
        u = j.get("usage") or {}
        c = cost_usd(model, u.get("input_tokens") or 0, u.get("output_tokens") or 0) or 0.0
        total += c
        text = "".join(b.get("text", "") for b in j.get("content", []) if b.get("type") == "text")
        try:
            rows = normalize_structured(json.loads(text), batch)
            ok, note = True, f"readable ({len(rows)} variables)"
        except Exception as e:  # noqa: BLE001 — any parse/shape problem is the result being measured
            ok, note = False, f"NOT usable: {type(e).__name__}: {str(e)[:120]}"
        think = (u.get("output_tokens_details") or {}).get("thinking_tokens")
        print(f"{tag}: HTTP 200 in {dt:.1f}s | stop {j.get('stop_reason')} | in {u.get('input_tokens')} / out "
              f"{u.get('output_tokens')} (thinking {think}) | ${c:.4f} | {note}")
        results[tag] = {"ok": ok and j.get("stop_reason") == "end_turn", "s": dt}

    print(f"\nTotal cost: about ${total:.4f}")
    a = results.get("A ", {})
    print(f"D-048 (Claude form): {'PASS — accepted and readable' if a.get('ok') else 'FAIL — see request A above'}")
    if not only_claude:
        b1, b2, b3 = (results.get(k, {}) for k in ("B1", "B2", "B3"))
        if not (b1.get("ok") and b2.get("ok") and b3.get("ok")):
            print("Option 1 (identical schema for both models): NOT feasible — Anthropic rejected or garbled the OpenAI form.")
        else:
            extra = b3["s"] - b2["s"]
            verdict = "FEASIBLE" if extra < THRESHOLD_S else "NOT feasible"
            print(f"Option 1 (identical schema for both models): {verdict} — new passage ids added {extra:+.1f}s "
                  f"(B3 {b3['s']:.1f}s vs B2 {b2['s']:.1f}s; threshold {THRESHOLD_S:.0f}s; first-time B1 {b1['s']:.1f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
