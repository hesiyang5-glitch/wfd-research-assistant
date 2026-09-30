"""SQLite persistence. Everything (cases, jobs, searches, sources, passages, suggestions, reviews, usage) lives here,
so refreshing the browser or restarting the server loses nothing."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager

from .config import DB_PATH

_lock = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_versions (
  id INTEGER PRIMARY KEY, label TEXT, codebook_label TEXT, workbook_label TEXT, created_at REAL,
  active INTEGER DEFAULT 0, parent_id INTEGER, change_note TEXT, schema_json TEXT);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS cases (
  id INTEGER PRIMARY KEY, name TEXT, location TEXT, date_text TEXT, date_start TEXT, date_end TEXT,
  details TEXT, known_links TEXT, aliases TEXT, schema_version_id INTEGER, status TEXT, identity_json TEXT,
  settings_json TEXT, created_at REAL, updated_at REAL);
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY, case_id INTEGER, kind TEXT, stage TEXT, status TEXT, progress REAL, message TEXT,
  error TEXT, params_json TEXT, state_json TEXT, created_at REAL, updated_at REAL, cancel_requested INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS job_log (id INTEGER PRIMARY KEY, job_id INTEGER, at REAL, stage TEXT, level TEXT, message TEXT);
CREATE TABLE IF NOT EXISTS search_queries (
  id INTEGER PRIMARY KEY, case_id INTEGER, job_id INTEGER, round INTEGER, purpose TEXT, query TEXT, page INTEGER,
  provider TEXT, status TEXT, result_count INTEGER, error TEXT, target_vars TEXT, created_at REAL);
CREATE TABLE IF NOT EXISTS search_results (
  id INTEGER PRIMARY KEY, query_id INTEGER, case_id INTEGER, url TEXT, title TEXT, snippet TEXT, rank INTEGER,
  published TEXT, identity_score REAL);
CREATE TABLE IF NOT EXISTS sources (
  id INTEGER PRIMARY KEY, case_id INTEGER, url TEXT, final_url TEXT, title TEXT, publisher TEXT, published_date TEXT,
  retrieved_at REAL, source_type TEXT, origin TEXT, found_via TEXT, fetch_status TEXT, fetch_error TEXT,
  content_type TEXT, content_hash TEXT, duplicate_of INTEGER, near_duplicate_of INTEGER, similarity REAL,
  relevance_score REAL, relevance_status TEXT, relevance_reason TEXT, excluded INTEGER DEFAULT 0, exclude_reason TEXT,
  ocr_status TEXT, n_pages INTEGER, n_passages INTEGER, text_chars INTEGER, file_path TEXT, snippet TEXT);
CREATE TABLE IF NOT EXISTS passages (
  id TEXT PRIMARY KEY, case_id INTEGER, source_id INTEGER, seq INTEGER, page INTEGER, para INTEGER, text TEXT);
CREATE INDEX IF NOT EXISTS ix_pass_case ON passages(case_id);
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY, case_id INTEGER, job_id INTEGER, mode TEXT, model TEXT, schema_version_id INTEGER,
  variables_json TEXT, created_at REAL, notes TEXT);
CREATE TABLE IF NOT EXISTS suggestions (
  id INTEGER PRIMARY KEY, case_id INTEGER, run_id INTEGER, variable TEXT, value TEXT, status TEXT,
  rationale TEXT, evidence_json TEXT, counter_json TEXT, unresolved TEXT, validation_json TEXT, raw_json TEXT,
  basis TEXT, created_at REAL, stale INTEGER DEFAULT 0, stale_reason TEXT);
CREATE INDEX IF NOT EXISTS ix_sugg_case ON suggestions(case_id, variable);
CREATE TABLE IF NOT EXISTS reviews (
  case_id INTEGER, variable TEXT, value TEXT, action TEXT, reason TEXT, suggestion_id INTEGER, updated_at REAL,
  PRIMARY KEY (case_id, variable));
CREATE TABLE IF NOT EXISTS review_history (
  id INTEGER PRIMARY KEY, case_id INTEGER, variable TEXT, old_value TEXT, new_value TEXT, action TEXT, reason TEXT,
  suggestion_id INTEGER, at REAL);
CREATE TABLE IF NOT EXISTS usage (
  id INTEGER PRIMARY KEY, case_id INTEGER, job_id INTEGER, kind TEXT, provider TEXT, model TEXT,
  input_tokens INTEGER, output_tokens INTEGER, units INTEGER, cost_usd REAL, estimated INTEGER, at REAL, note TEXT);
CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value TEXT, created_at REAL);
"""


def connect() -> sqlite3.Connection:
    c = sqlite3.connect(str(DB_PATH), timeout=30, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    return c


_conn = None


def conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = connect()
        _conn.executescript(SCHEMA)
        for table, col in (("reviews", "reviewer"), ("review_history", "reviewer"), ("sources", "added_by"), ("jobs", "started_by")):
            cols = {r[1] for r in _conn.execute(f"PRAGMA table_info({table})").fetchall()}
            if col not in cols:  # upgrade older databases in place
                _conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} TEXT")
        _conn.commit()
    return _conn


@contextmanager
def tx():
    with _lock:
        c = conn()
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise


def q(sql: str, args=()) -> list[dict]:
    with _lock:
        return [dict(r) for r in conn().execute(sql, args).fetchall()]


def q1(sql: str, args=()) -> dict | None:
    rows = q(sql, args)
    return rows[0] if rows else None


def ex(sql: str, args=()) -> int:
    with tx() as c:
        cur = c.execute(sql, args)
        return cur.lastrowid


def insert(table: str, row: dict) -> int:
    cols = ",".join(row.keys())
    ph = ",".join("?" for _ in row)
    return ex(f"INSERT INTO {table} ({cols}) VALUES ({ph})", tuple(row.values()))


def update(table: str, id_: int, row: dict, key: str = "id") -> None:
    if not row:
        return
    sets = ",".join(f"{k}=?" for k in row)
    ex(f"UPDATE {table} SET {sets} WHERE {key}=?", tuple(row.values()) + (id_,))


def cache_get(key: str):
    r = q1("SELECT value FROM cache WHERE key=?", (key,))
    return json.loads(r["value"]) if r else None


def cache_put(key: str, value) -> None:
    ex("INSERT OR REPLACE INTO cache (key,value,created_at) VALUES (?,?,?)", (key, json.dumps(value), time.time()))


def get_setting(key: str, default=None):
    r = q1("SELECT value FROM settings WHERE key=?", (key,))
    return json.loads(r["value"]) if r else default


def set_setting(key: str, value) -> None:
    ex("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", (key, json.dumps(value)))
