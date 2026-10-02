"""Additive, repeatable database migrations.

Rules: never drop or rewrite existing rows; only add tables/columns. Every step checks what exists first, so running
it twice (or on every start) is safe. Old code keeps working on a migrated database because it only reads the columns
it knows.

Rollback (see DEPLOY.md, "Rolling back the OpenAI provider"): `python3 -m app.migrations rollback` moves suggestion rows
that old code would misread (OpenAI results and reviewer-mode results) into `suggestions_provider_archive`, so that the
previous version again sees only Claude/primary suggestions. Human reviews, cases, sources, passages and the usage
ledger are untouched. `python3 -m app.migrations restore` moves the archived rows back.
"""
from __future__ import annotations

import sqlite3
import sys
import time

MIGRATION_ID = "2026-10-01-openai-provider"

ADD_COLUMNS = {
    "runs": [("provider", "TEXT"), ("role", "TEXT"), ("group_id", "TEXT"), ("coding_mode", "TEXT"),
             ("independent", "INTEGER")],
    "suggestions": [("provider", "TEXT"), ("model", "TEXT"), ("role", "TEXT"), ("group_id", "TEXT"),
                    ("call_id", "INTEGER"), ("cache_status", "TEXT")],
    "usage": [("call_id", "INTEGER"), ("reasoning_tokens", "INTEGER"), ("cached_input_tokens", "INTEGER"),
              ("request_id", "TEXT")],
    "reviews": [("source_provider", "TEXT")],
    "review_history": [("source_provider", "TEXT")],
}

NEW_TABLES = """
CREATE TABLE IF NOT EXISTS schema_migrations (id TEXT PRIMARY KEY, applied_at REAL, status TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS model_calls (
  id INTEGER PRIMARY KEY, case_id INTEGER, job_id INTEGER, run_id INTEGER, group_id TEXT, provider TEXT, model TEXT,
  role TEXT, batch_no INTEGER, n_batches INTEGER, variables_json TEXT, evidence_ids_json TEXT, evidence_hash TEXT,
  status TEXT, incomplete_reason TEXT, error TEXT, http_attempts INTEGER DEFAULT 0, request_id TEXT, response_id TEXT,
  input_tokens INTEGER, cached_input_tokens INTEGER, output_tokens INTEGER, reasoning_tokens INTEGER,
  max_output_tokens INTEGER, cost_usd REAL, cost_estimated INTEGER, cache_key TEXT, cache_status TEXT,
  settings_json TEXT, duration_s REAL, at REAL);
CREATE INDEX IF NOT EXISTS ix_calls_case ON model_calls(case_id, provider);
CREATE TABLE IF NOT EXISTS suggestions_provider_archive (
  id INTEGER PRIMARY KEY, archived_at REAL, row_json TEXT);
CREATE TABLE IF NOT EXISTS provider_controls (
  job_id INTEGER, provider TEXT, stop_requested INTEGER DEFAULT 0, requested_by TEXT, requested_at REAL,
  PRIMARY KEY (job_id, provider));
CREATE TABLE IF NOT EXISTS limit_changes (
  id INTEGER PRIMARY KEY, case_id INTEGER, job_id INTEGER, key TEXT, old_value TEXT, new_value TEXT,
  changed_by TEXT, reason TEXT, at REAL);
"""


def _cols(c: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in c.execute(f"PRAGMA table_info({table})").fetchall()}


def migrate(c: sqlite3.Connection) -> list[str]:
    """Apply the additive migration. Returns the list of changes made (empty when already applied)."""
    done = []
    c.executescript(NEW_TABLES)
    for table, cols in ADD_COLUMNS.items():
        have = _cols(c, table)
        for name, typ in cols:
            if name not in have:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {name} {typ}")
                done.append(f"{table}.{name}")
    c.execute("CREATE INDEX IF NOT EXISTS ix_sugg_provider ON suggestions(case_id, variable, provider)")
    row = c.execute("SELECT status FROM schema_migrations WHERE id=?", (MIGRATION_ID,)).fetchone()
    if not row:
        c.execute("INSERT INTO schema_migrations (id, applied_at, status, note) VALUES (?,?,?,?)",
                  (MIGRATION_ID, time.time(), "applied", f"added {len(done)} column(s)"))
    elif row[0] != "applied":
        c.execute("UPDATE schema_migrations SET status='applied', applied_at=? WHERE id=?", (time.time(), MIGRATION_ID))
    c.commit()
    return done


def _old_code_would_misread(row: dict) -> bool:
    """Rows the pre-OpenAI version must not see: it treats the newest suggestion per variable as THE suggestion."""
    prov, role = row.get("provider"), row.get("role")
    if role == "reviewer":
        return True
    return prov is not None and prov not in ("anthropic", "system")


def rollback(c: sqlite3.Connection) -> int:
    """Archive (not delete) suggestion rows the previous version would misread. Returns rows archived."""
    import json
    c.row_factory = sqlite3.Row
    if "provider" not in _cols(c, "suggestions"):
        return 0
    rows = [dict(r) for r in c.execute("SELECT * FROM suggestions").fetchall()]
    moved = 0
    for r in rows:
        if _old_code_would_misread(r):
            c.execute("INSERT INTO suggestions_provider_archive (id, archived_at, row_json) VALUES (?,?,?)",
                      (r["id"], time.time(), json.dumps(r)))
            c.execute("DELETE FROM suggestions WHERE id=?", (r["id"],))
            moved += 1
    c.execute("INSERT OR REPLACE INTO schema_migrations (id, applied_at, status, note) VALUES (?,?,?,?)",
              (MIGRATION_ID, time.time(), "rolled_back", f"archived {moved} suggestion row(s)"))
    c.commit()
    return moved


def restore(c: sqlite3.Connection) -> int:
    """Move archived rows back into `suggestions` (after re-deploying the OpenAI-capable version)."""
    import json
    migrate(c)
    n = 0
    for rid, js in c.execute("SELECT id, row_json FROM suggestions_provider_archive").fetchall():
        r = json.loads(js)
        cols = [k for k in r if k in _cols(c, "suggestions")]
        c.execute(f"INSERT OR IGNORE INTO suggestions ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})",
                  tuple(r[k] for k in cols))
        c.execute("DELETE FROM suggestions_provider_archive WHERE id=?", (rid,))
        n += 1
    c.commit()
    return n


if __name__ == "__main__":
    from .config import DB_PATH
    cmd = sys.argv[1] if len(sys.argv) > 1 else "migrate"
    con = sqlite3.connect(str(DB_PATH))
    if cmd == "migrate":
        print("changes:", migrate(con) or "none (already applied)")
    elif cmd == "rollback":
        print("archived suggestion rows:", rollback(con))
    elif cmd == "restore":
        print("restored suggestion rows:", restore(con))
    else:
        sys.exit("usage: python3 -m app.migrations [migrate|rollback|restore]")
