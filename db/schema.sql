-- Canonical schema for the Graham & Doddsville newsletter dashboard.
-- Applied idempotently on startup via app/db.py (CREATE TABLE IF NOT EXISTS).

CREATE TABLE IF NOT EXISTS issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    issue_number INTEGER,
    season TEXT,
    title TEXT,
    source_url TEXT UNIQUE,
    pdf_path TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    error TEXT,
    downloaded_at TEXT,
    extracted_at TEXT,
    analyzed_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS ideas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    issue_id INTEGER REFERENCES issues(id) ON DELETE CASCADE,
    kind TEXT NOT NULL DEFAULT 'pitch',
    ticker TEXT,
    company TEXT,
    direction TEXT,
    thesis TEXT,
    challenge TEXT,
    author TEXT,
    price_at_pitch REAL,
    pitch_date TEXT,
    target_price REAL,
    raw_excerpt TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS performance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    idea_id INTEGER NOT NULL REFERENCES ideas(id) ON DELETE CASCADE,
    current_price REAL,
    as_of TEXT,
    return_pct REAL,
    source TEXT,
    price_at_ref REAL,
    fetched_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS llm_verdicts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    idea_id INTEGER REFERENCES ideas(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    model TEXT,
    content TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

-- Background job tracking for admin actions (backfill, analyze); see
-- app/services/jobs.py. `note` holds a JSON progress/result blob.
CREATE TABLE IF NOT EXISTS analysis_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    finished_at TEXT,
    note TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE INDEX IF NOT EXISTS idx_ideas_issue ON ideas(issue_id);
CREATE INDEX IF NOT EXISTS idx_ideas_ticker ON ideas(ticker);
CREATE INDEX IF NOT EXISTS idx_perf_idea ON performance(idea_id);
CREATE INDEX IF NOT EXISTS idx_verdict_idea ON llm_verdicts(idea_id);
