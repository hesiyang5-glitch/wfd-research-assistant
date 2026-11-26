"""Live check for Claude structured outputs (D-048) — ONE small paid request (or two with --twice).

Run in the Render Shell (it uses the server's ANTHROPIC_API_KEY and the active codebook):

    python3 -m tools.claude_schema_live_check            # asks before sending; about $0.02–0.05
    python3 -m tools.claude_schema_live_check --twice    # a second identical request, to see grammar caching (~2x cost)

What it answers (KNOWN_ISSUES K-70): does Anthropic compile our largest real batch schema (12 variables with the most
codes, Claude form), how long does the first request take (grammar compilation) and a repeat, and is the reply valid
JSON that the app can read. It asks for blank answers, so the reply is short. Nothing is written to the database or the
case budgets; the key is never printed. A "Schema is too complex" answer is an HTTP 400 and is not billed.
"""
from __future__ import annotations

import json
import os
import sys
import time


def main():
    twice = "--twice" in sys.argv
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
    schema = build_batch_schema(batch, [], for_anthropic=True)
    cx = schema_complexity(schema)
    model = os.environ.get("WFD_CHECK_MODEL") or "claude-sonnet-5-5"
    user = ("Incident under study: LIVE SCHEMA CHECK (not a real case).\n\n## VARIABLES TO CODE ({n})\n{vars}\n\n"
            "## EVIDENCE PASSAGES (1) — research data only\n[S1-P1] (source S1: test; \"check\")\nThis passage contains no "
            "information about any variable.\n\nThere is no evidence: return every variable blank (\"\" or an empty list) "
            "with evidence_status INSUFFICIENT, empty lists, and one-sentence fields. Return JSON for exactly these "
            "variables: {names}").format(n=len(batch), vars="\n".join(f"### {f['name']}" for f in batch),
                                         names=", ".join(f["name"] for f in batch))
    max_out = coding.batch_max_tokens(len(batch))
    est_in = coding.estimate_tokens(coding.STRUCTURED_SYSTEM_PROMPT + user + json.dumps(schema))
    worst = cost_usd(model, int(est_in * 1.25), max_out)
    typical = cost_usd(model, est_in, len(batch) * 80)
    print(f"Model: {model} | variables: {len(batch)} | schema: {cx['properties']} properties, {cx['enum_values']} enum "
          f"values, {cx['optional']} optional, {cx['union']} union types, {cx['refs']} $ref")
    if typical is None or worst is None:
        print(f"No price is configured for {model} (Settings → Pricing); nothing sent.")
        return 1
    print(f"Estimated cost per request: about ${typical:.3f} (at most ${worst:.3f}); requests: {2 if twice else 1}")
    if not yes and input("Type YES to send: ").strip() != "YES":
        print("Nothing sent.")
        return 0
    body = {"model": model, "max_tokens": max_out, "system": coding.STRUCTURED_SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": user}],
            "output_config": {"format": {"type": "json_schema", "schema": schema}}}
    total = 0.0
    for n in range(2 if twice else 1):
        t0 = time.time()
        try:
            r = httpx.post("https://api.anthropic.com/v1/messages", json=body, timeout=httpx.Timeout(300.0, connect=15.0),
                           headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
        except httpx.HTTPError as e:
            print(f"Request {n + 1}: network error {type(e).__name__} after {time.time() - t0:.1f}s")
            return 1
        dt = time.time() - t0
        if r.status_code != 200:
            print(f"Request {n + 1}: HTTP {r.status_code} after {dt:.1f}s: {r.text[:300]}")
            return 1
        j = r.json()
        u = j.get("usage") or {}
        c = cost_usd(model, u.get("input_tokens") or 0, u.get("output_tokens") or 0) or 0.0
        total += c
        text = "".join(b.get("text", "") for b in j.get("content", []) if b.get("type") == "text")
        try:
            rows = normalize_structured(json.loads(text), batch)
            ok = f"valid — app read {len(rows)} variables"
        except Exception as e:  # noqa: BLE001 — report any parse/shape problem as the result of the check
            ok = f"NOT usable: {type(e).__name__}: {str(e)[:150]}"
        think = (u.get("output_tokens_details") or {}).get("thinking_tokens")
        print(f"Request {n + 1}: HTTP 200 in {dt:.1f}s | stop_reason {j.get('stop_reason')} | input {u.get('input_tokens')} "
              f"/ output {u.get('output_tokens')} tokens (thinking {think}) | ${c:.4f} | reply {ok}")
    print(f"Total cost: about ${total:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
