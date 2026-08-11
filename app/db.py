import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterable

from .config import DATA_DIR, DB_PATH, DEFAULT_SETTINGS, UPLOAD_DIR

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS profile (
 id INTEGER PRIMARY KEY CHECK(id=1), resume_path TEXT, raw_text TEXT DEFAULT '', redacted_text TEXT DEFAULT '',
 profile_json TEXT DEFAULT '{}', approved INTEGER DEFAULT 0, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS companies (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL, ats_type TEXT NOT NULL, token TEXT NOT NULL,
 careers_url TEXT DEFAULT '', sector TEXT DEFAULT 'Technology', enabled INTEGER DEFAULT 1,
 last_success_at TEXT, last_error TEXT, created_at TEXT NOT NULL, shortlisted INTEGER DEFAULT 1,
 shortlist_reason TEXT DEFAULT '',
 UNIQUE(ats_type, token)
);
CREATE TABLE IF NOT EXISTS jobs (
 id INTEGER PRIMARY KEY, company_id INTEGER, company_name TEXT NOT NULL, external_id TEXT NOT NULL,
 source_type TEXT NOT NULL, source_url TEXT NOT NULL, canonical_url TEXT NOT NULL,
 title TEXT NOT NULL, location TEXT DEFAULT '', work_arrangement TEXT DEFAULT '', description TEXT DEFAULT '',
 raw_json TEXT DEFAULT '{}', salary_min REAL, salary_max REAL, currency TEXT DEFAULT 'USD',
 posted_at TEXT, first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL, content_hash TEXT NOT NULL,
 active INTEGER DEFAULT 1, review_status TEXT DEFAULT 'inbox', dismiss_reason TEXT DEFAULT '',
 rule_score REAL DEFAULT 0, ai_score REAL, combined_score REAL DEFAULT 0, ai_status TEXT DEFAULT 'pending',
 eligible INTEGER DEFAULT 1, eligibility_reason TEXT DEFAULT '',
 match_tier TEXT DEFAULT 'low', rule_result TEXT DEFAULT '{}',
 ai_result TEXT DEFAULT '{}', ai_cache_key TEXT DEFAULT '', updated_at TEXT NOT NULL,
 FOREIGN KEY(company_id) REFERENCES companies(id), UNIQUE(source_type, external_id, company_name)
);
CREATE INDEX IF NOT EXISTS idx_jobs_inbox ON jobs(active, review_status, combined_score DESC);
CREATE TABLE IF NOT EXISTS applications (
 id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL UNIQUE, stage TEXT NOT NULL DEFAULT 'Preparing',
 notes TEXT DEFAULT '', next_follow_up TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 FOREIGN KEY(job_id) REFERENCES jobs(id)
);
CREATE TABLE IF NOT EXISTS stage_events (
 id INTEGER PRIMARY KEY, application_id INTEGER NOT NULL, from_stage TEXT, to_stage TEXT NOT NULL,
 happened_at TEXT NOT NULL, FOREIGN KEY(application_id) REFERENCES applications(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS tasks (
 id INTEGER PRIMARY KEY, application_id INTEGER NOT NULL, title TEXT NOT NULL, due_at TEXT, completed INTEGER DEFAULT 0,
 FOREIGN KEY(application_id) REFERENCES applications(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS contacts (
 id INTEGER PRIMARY KEY, application_id INTEGER NOT NULL, name TEXT NOT NULL, email TEXT DEFAULT '', role TEXT DEFAULT '', notes TEXT DEFAULT '',
 FOREIGN KEY(application_id) REFERENCES applications(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS ingestion_runs (
 id INTEGER PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT, status TEXT DEFAULT 'running',
 jobs_seen INTEGER DEFAULT 0, jobs_new INTEGER DEFAULT 0, jobs_updated INTEGER DEFAULT 0, error TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS ai_requests (
 id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL, requested_at TEXT NOT NULL, model TEXT NOT NULL,
 prompt_version TEXT NOT NULL, status TEXT NOT NULL, prompt_tokens INTEGER DEFAULT 0, completion_tokens INTEGER DEFAULT 0,
 estimated_cost REAL DEFAULT 0, latency_ms INTEGER DEFAULT 0, error TEXT DEFAULT '',
 FOREIGN KEY(job_id) REFERENCES jobs(id)
);
CREATE TABLE IF NOT EXISTS digest_runs (
 id INTEGER PRIMARY KEY, sent_at TEXT NOT NULL, job_count INTEGER DEFAULT 0, status TEXT NOT NULL, error TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS company_list_memberships (
 id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL, source_key TEXT NOT NULL, source_name TEXT NOT NULL,
 source_url TEXT NOT NULL, rank INTEGER, imported_at TEXT NOT NULL,
 FOREIGN KEY(company_id) REFERENCES companies(id) ON DELETE CASCADE,
 UNIQUE(company_id, source_key)
);
"""

def now() -> str:
    return datetime.now(timezone.utc).isoformat()

def init_db() -> None:
    DATA_DIR.mkdir(exist_ok=True); UPLOAD_DIR.mkdir(exist_ok=True)
    with connect() as db:
        db.executescript(SCHEMA)
        job_columns={r[1] for r in db.execute("PRAGMA table_info(jobs)")}
        if "eligible" not in job_columns: db.execute("ALTER TABLE jobs ADD COLUMN eligible INTEGER DEFAULT 1")
        if "eligibility_reason" not in job_columns: db.execute("ALTER TABLE jobs ADD COLUMN eligibility_reason TEXT DEFAULT ''")
        if "match_tier" not in job_columns: db.execute("ALTER TABLE jobs ADD COLUMN match_tier TEXT DEFAULT 'low'")
        if "rule_result" not in job_columns: db.execute("ALTER TABLE jobs ADD COLUMN rule_result TEXT DEFAULT '{}'")
        company_columns={r[1] for r in db.execute("PRAGMA table_info(companies)")}
        if "shortlisted" not in company_columns: db.execute("ALTER TABLE companies ADD COLUMN shortlisted INTEGER DEFAULT 1")
        if "shortlist_reason" not in company_columns: db.execute("ALTER TABLE companies ADD COLUMN shortlist_reason TEXT DEFAULT ''")
        for key, value in DEFAULT_SETTINGS.items():
            db.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (key, json.dumps(value)))
        db.execute("INSERT OR IGNORE INTO profile(id,updated_at) VALUES(1,?)", (now(),))

@contextmanager
def connect():
    DATA_DIR.mkdir(exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        yield db; db.commit()
    except Exception:
        db.rollback(); raise
    finally:
        db.close()

def rows(query: str, params: Iterable[Any] = ()) -> list[dict]:
    with connect() as db:
        return [dict(r) for r in db.execute(query, tuple(params)).fetchall()]

def row(query: str, params: Iterable[Any] = ()) -> dict | None:
    found = rows(query, params)
    return found[0] if found else None

def get_settings() -> dict:
    return {r["key"]: json.loads(r["value"]) for r in rows("SELECT key,value FROM settings")}

def set_settings(values: dict) -> dict:
    with connect() as db:
        for key, value in values.items():
            db.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, json.dumps(value)))
    return get_settings()
