-- CareerPulse SQLite Database Schema
-- Provides ACID-compliant persistence, WAL mode for high concurrency,
-- and strict unique constraints to guarantee zero duplicate alerts.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;
PRAGMA synchronous = NORMAL;

-- Target Companies Monitored by CareerPulse
CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    career_url TEXT NOT NULL DEFAULT '',
    ats_provider TEXT NOT NULL DEFAULT 'custom', -- 'greenhouse', 'lever', 'ashby', 'workday', 'playwright', 'custom'
    identifier TEXT,
    provider TEXT,
    url TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    last_scanned_at TIMESTAMP,
    scan_status TEXT DEFAULT 'pending', -- 'success', 'failed', 'pending', 'scanning'
    last_error TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_companies_active ON companies(is_active);
CREATE INDEX IF NOT EXISTS idx_companies_provider ON companies(ats_provider);

-- Ingested Job Listings Repository
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    external_id TEXT NOT NULL,
    unique_key TEXT NOT NULL UNIQUE, -- '{provider}:{company_id}:{external_id}' or 'url_hash:{hash}'
    canonical_url TEXT NOT NULL,
    title TEXT NOT NULL,
    department TEXT,
    location TEXT NOT NULL DEFAULT 'Unknown',
    workplace_type TEXT NOT NULL DEFAULT 'unknown',
    is_remote INTEGER NOT NULL DEFAULT 0,
    apply_url TEXT NOT NULL,
    description_text TEXT,
    raw_payload TEXT, -- Raw JSON blob
    published_at TIMESTAMP,
    first_seen_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    is_active INTEGER NOT NULL DEFAULT 1,
    CONSTRAINT uq_company_external UNIQUE (company_id, external_id)
);

CREATE INDEX IF NOT EXISTS idx_jobs_unique_key ON jobs(unique_key);
CREATE INDEX IF NOT EXISTS idx_jobs_company_id ON jobs(company_id);
CREATE INDEX IF NOT EXISTS idx_jobs_is_active ON jobs(is_active);
CREATE INDEX IF NOT EXISTS idx_jobs_first_seen ON jobs(first_seen_at DESC);

-- Alerts Dispatch History (Atomic Deduplication Constraint)
CREATE TABLE IF NOT EXISTS alerts_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    sent_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    channel TEXT NOT NULL DEFAULT 'telegram',
    status TEXT NOT NULL, -- 'sent', 'failed', 'mock', 'pending'
    error_message TEXT,
    message_preview TEXT,
    CONSTRAINT uq_alerts_job_channel UNIQUE (job_id, channel)
);

CREATE INDEX IF NOT EXISTS idx_alerts_job ON alerts_history(job_id);
CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts_history(status);

-- Key-Value System Configuration & Filter State
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL, -- JSON-serialized value
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Scan Activity History
CREATE TABLE IF NOT EXISTS scan_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scanned_at TEXT NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%SZ', 'NOW')),
    company_id INTEGER,
    company_name TEXT NOT NULL,
    provider TEXT NOT NULL DEFAULT 'custom',
    jobs_found INTEGER NOT NULL DEFAULT 0,
    jobs_matched INTEGER NOT NULL DEFAULT 0,
    alerts_sent INTEGER NOT NULL DEFAULT 0,
    duration_seconds REAL NOT NULL DEFAULT 0.0,
    status TEXT NOT NULL DEFAULT 'success',
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_scan_logs_id ON scan_logs(id DESC);

