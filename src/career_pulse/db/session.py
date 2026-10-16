"""
Async SQLite Database Service for CareerPulse.

Provides non-blocking SQLite access via aiosqlite, enforcing:
- Write-Ahead Logging (WAL mode) and foreign keys.
- Canonical URL normalization and immutable unique key generation.
- Atomic job upserting with last_seen_at tracking.
- Zero-duplicate atomic alert reservation via ON CONFLICT DO NOTHING.
"""

import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
from urllib.parse import urlparse, urlunparse

import aiosqlite

from ..core.models import JobListing

logger = logging.getLogger("career_pulse.db")

SCHEMA_FILE = Path(__file__).resolve().parent / "schema.sql"


def normalize_url(url: str) -> str:
    """
    Remove query tracking parameters and trailing slashes for canonical deduplication.

    Normalizes the scheme and hostname to lowercase and strips trailing slashes from path.
    """
    if not url:
        return ""
    try:
        parsed = urlparse(url.strip())
        clean_path = parsed.path.rstrip('/')
        return urlunparse((
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            clean_path,
            '',
            '',
            ''
        ))
    except Exception as e:
        logger.debug(f"URL normalization fallback for '{url}': {e}")
        return url.strip().rstrip('/')


def generate_unique_key(provider: str, company_id: int, external_id: str, canonical_url: str) -> str:
    """
    Generate an immutable unique key string for job deduplication.

    Prioritizes official external IDs; falls back to SHA-256 hash of canonical URL.
    """
    prov = (provider or "custom").lower().strip()
    ext_id = (external_id or "").strip()
    if ext_id and ext_id.lower() != "unknown":
        return f"{prov}:{company_id}:{ext_id}"

    url_hash = hashlib.sha256(canonical_url.encode("utf-8")).hexdigest()[:16]
    return f"url_hash:{url_hash}"


class ConnectionContext:
    """
    Context manager wrapper for an aiosqlite Connection to avoid
    'RuntimeError: threads can only be started once' when callers use
    'async with await db.get_connection() as conn:'.
    """
    def __init__(self, conn: aiosqlite.Connection):
        self._conn = conn

    async def __aenter__(self) -> aiosqlite.Connection:
        return self._conn

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self._conn.close()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)

    async def close(self) -> None:
        await self._conn.close()


class Database:
    """
    Asynchronous SQLite Database Manager for CareerPulse.

    Handles connection pooling, schema initialization, job upserts,
    and ACID atomic alert reservation.
    """

    def __init__(self, db_path: Union[str, Path] = "career_pulse.db"):
        self.db_path = str(db_path)

    async def get_connection(self) -> ConnectionContext:
        """
        Open and configure an aiosqlite connection with WAL mode and PRAGMAs.
        """
        conn = await aiosqlite.connect(self.db_path)
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA journal_mode = WAL;")
        await conn.execute("PRAGMA foreign_keys = ON;")
        await conn.execute("PRAGMA busy_timeout = 5000;")
        await conn.execute("PRAGMA synchronous = NORMAL;")
        return ConnectionContext(conn)

    async def init_schema(self, schema_sql: Optional[str] = None) -> None:
        """
        Initialize tables, indexes, and constraints.
        """
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        if schema_sql is None:
            if SCHEMA_FILE.exists():
                schema_sql = SCHEMA_FILE.read_text(encoding="utf-8")
            else:
                raise FileNotFoundError(f"Schema file not found at {SCHEMA_FILE}")

        async with await self.get_connection() as conn:
            await conn.executescript(schema_sql)
            await conn.commit()

    async def upsert_job(self, company_id: int, job: JobListing) -> Tuple[int, bool]:
        """
        Insert a new job or update an existing job's last_seen_at timestamp.

        Returns (job_id, is_new):
        - is_new is True if the job was newly inserted.
        - is_new is False if the job was already present and updated.
        """
        canonical_url = normalize_url(job.url)
        unique_key = generate_unique_key(job.provider, company_id, job.external_id, canonical_url)

        async with await self.get_connection() as conn:
            # Check existing record by unique key
            async with conn.execute(
                "SELECT id, is_active FROM jobs WHERE unique_key = ?",
                (unique_key,)
            ) as cursor:
                row = await cursor.fetchone()

            if row:
                job_id = int(row["id"])
                await conn.execute(
                    """
                    UPDATE jobs
                    SET last_seen_at = CURRENT_TIMESTAMP,
                        title = ?,
                        location = ?,
                        workplace_type = ?,
                        is_remote = ?,
                        apply_url = ?,
                        description_text = ?,
                        is_active = 1
                    WHERE id = ?
                    """,
                    (
                        job.title,
                        job.location or "Unknown",
                        job.workplace_type or "unknown",
                        1 if job.is_remote else 0,
                        job.url,
                        job.description_text or "",
                        job_id,
                    ),
                )
                await conn.commit()
                return job_id, False
            else:
                raw_json = json.dumps(job.raw_payload) if job.raw_payload is not None else None
                pub_at = job.published_at.isoformat() if job.published_at else None
                async with conn.execute(
                    """
                    INSERT INTO jobs (
                        company_id, external_id, unique_key, canonical_url,
                        title, department, location, workplace_type, is_remote,
                        apply_url, description_text, raw_payload, published_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        company_id,
                        job.external_id,
                        unique_key,
                        canonical_url,
                        job.title,
                        job.department,
                        job.location or "Unknown",
                        job.workplace_type or "unknown",
                        1 if job.is_remote else 0,
                        job.url,
                        job.description_text or "",
                        raw_json,
                        pub_at,
                    ),
                ) as cursor:
                    job_id = int(cursor.lastrowid)
                await conn.commit()
                return job_id, True

    async def reserve_alert_slot(self, job_id: int, channel: str = "telegram") -> bool:
        """
        Atomic reservation to guarantee zero duplicate alerts.

        Executes INSERT INTO alerts_history ... ON CONFLICT DO NOTHING.
        Returns True if reservation was acquired (new un-alerted job),
        False if an alert has already been reserved/sent for this job and channel.
        """
        async with await self.get_connection() as conn:
            try:
                cursor = await conn.execute(
                    """
                    INSERT INTO alerts_history (job_id, channel, status)
                    VALUES (?, ?, 'pending')
                    ON CONFLICT(job_id, channel) DO NOTHING;
                    """,
                    (job_id, channel),
                )
                await conn.commit()
                return bool(cursor.rowcount > 0)
            except Exception as e:
                logger.error(f"Error reserving alert slot for job {job_id}: {e}")
                return False

    async def finalize_alert_status(
        self,
        job_id: int,
        channel: str,
        status: str,
        preview: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        """
        Update alert status to 'sent', 'mock', or 'failed' with optional message preview.
        """
        async with await self.get_connection() as conn:
            await conn.execute(
                """
                UPDATE alerts_history
                SET status = ?,
                    message_preview = ?,
                    error_message = ?,
                    sent_at = CURRENT_TIMESTAMP
                WHERE job_id = ? AND channel = ?
                """,
                (status, preview, error, job_id, channel),
            )
            await conn.commit()

    async def get_job_by_id(self, job_id: int) -> Optional[Dict[str, Any]]:
        """Fetch a single job record by its primary key ID."""
        async with await self.get_connection() as conn:
            async with conn.execute(
                "SELECT * FROM jobs WHERE id = ?", (job_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def get_jobs(
        self,
        company_id: Optional[int] = None,
        is_active: Optional[bool] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Fetch job listings with optional filtering and pagination."""
        query = "SELECT * FROM jobs WHERE 1=1"
        params: List[Any] = []

        if company_id is not None:
            query += " AND company_id = ?"
            params.append(company_id)
        if is_active is not None:
            query += " AND is_active = ?"
            params.append(1 if is_active else 0)

        query += " ORDER BY first_seen_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        async with await self.get_connection() as conn:
            async with conn.execute(query, tuple(params)) as cursor:
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]

    async def get_alert(self, job_id: int, channel: str = "telegram") -> Optional[Dict[str, Any]]:
        """Fetch alert history record for a given job and channel."""
        async with await self.get_connection() as conn:
            async with conn.execute(
                "SELECT * FROM alerts_history WHERE job_id = ? AND channel = ?",
                (job_id, channel),
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def add_company(self, name: str, career_url: str, ats_provider: str) -> int:
        """Register a new monitored target company."""
        async with await self.get_connection() as conn:
            async with conn.execute(
                """
                INSERT INTO companies (name, career_url, ats_provider)
                VALUES (?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET career_url = excluded.career_url, ats_provider = excluded.ats_provider
                """,
                (name, career_url, ats_provider),
            ) as cursor:
                await conn.commit()
                if cursor.lastrowid:
                    return int(cursor.lastrowid)

            # In case of update without new rowid
            async with conn.execute("SELECT id FROM companies WHERE name = ?", (name,)) as cur:
                row = await cur.fetchone()
                return int(row["id"]) if row else 1

    async def get_setting(self, key: str, default: Any = None) -> Any:
        """Retrieve a JSON-deserialized value from settings table."""
        async with await self.get_connection() as conn:
            async with conn.execute("SELECT value FROM settings WHERE key = ?", (key,)) as cur:
                row = await cur.fetchone()
                if row:
                    return json.loads(row["value"])
                return default

    async def set_setting(self, key: str, value: Any) -> None:
        """Store a JSON-serialized value into settings table."""
        val_str = json.dumps(value)
        async with await self.get_connection() as conn:
            await conn.execute(
                """
                INSERT INTO settings (key, value, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP
                """,
                (key, val_str),
            )
            await conn.commit()

    async def write_scan_log(
        self,
        company_name: str,
        company_id: Optional[int] = None,
        provider: str = "custom",
        jobs_found: int = 0,
        jobs_matched: int = 0,
        alerts_sent: int = 0,
        duration_seconds: float = 0.0,
        status: str = "success",
        error_message: Optional[str] = None,
    ) -> int:
        """Insert a scan log entry and prune history to retain newest 200 entries."""
        async with await self.get_connection() as conn:
            cursor = await conn.execute(
                """
                INSERT INTO scan_logs (
                    company_id, company_name, provider,
                    jobs_found, jobs_matched, alerts_sent,
                    duration_seconds, status, error_message
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    company_id, company_name, provider,
                    jobs_found, jobs_matched, alerts_sent,
                    duration_seconds, status, error_message
                ),
            )
            log_id = cursor.lastrowid or 0

            # Immediately purge rows beyond the newest 200
            await conn.execute(
                "DELETE FROM scan_logs WHERE id NOT IN (SELECT id FROM scan_logs ORDER BY id DESC LIMIT 200)"
            )
            await conn.commit()
            return int(log_id)

    async def get_scan_logs(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Retrieve recent scan logs up to limit."""
        async with await self.get_connection() as conn:
            async with conn.execute(
                "SELECT * FROM scan_logs ORDER BY id DESC LIMIT ?",
                (limit,),
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]

    async def get_overview_stats(self) -> Dict[str, Any]:
        """Compute aggregated statistics for the overview dashboard."""
        async with await self.get_connection() as conn:
            # 1. matched_today: count of jobs where first_seen_at >= today's date AND alert_status IN ('sent', 'mock')
            async with conn.execute(
                """
                SELECT COUNT(DISTINCT j.id) as cnt
                FROM jobs j
                JOIN alerts_history a ON a.job_id = j.id
                WHERE (date(j.first_seen_at) >= date('now') OR date(j.first_seen_at, 'localtime') >= date('now', 'localtime'))
                  AND a.status IN ('sent', 'mock')
                """
            ) as cur:
                row = await cur.fetchone()
                matched_today = int(row["cnt"]) if row else 0

            # 2. jobs_rejected: total jobs in DB that have NO matching alert
            async with conn.execute(
                """
                SELECT COUNT(j.id) as cnt
                FROM jobs j
                LEFT JOIN alerts_history a ON a.job_id = j.id
                WHERE a.id IS NULL
                """
            ) as cur:
                row = await cur.fetchone()
                jobs_rejected = int(row["cnt"]) if row else 0

            # 3. last_scan: object with company_name and scanned_at from scan_logs (or companies fallback)
            last_scan: Optional[Dict[str, Any]] = None
            try:
                async with conn.execute(
                    "SELECT company_name, scanned_at FROM scan_logs ORDER BY id DESC LIMIT 1"
                ) as cur:
                    row = await cur.fetchone()
                    if row:
                        last_scan = {"company_name": row["company_name"], "scanned_at": row["scanned_at"]}
            except Exception:
                pass

            if not last_scan:
                async with conn.execute(
                    """
                    SELECT name as company_name, last_scanned_at as scanned_at
                    FROM companies
                    WHERE last_scanned_at IS NOT NULL
                    ORDER BY last_scanned_at DESC LIMIT 1
                    """
                ) as cur:
                    row = await cur.fetchone()
                    if row:
                        last_scan = {"company_name": row["company_name"], "scanned_at": row["scanned_at"]}
                    else:
                        last_scan = {"company_name": "None", "scanned_at": None}

            # 4. match_rate: (total jobs that have an alert / total jobs) * 100, rounded to 1 decimal
            async with conn.execute("SELECT COUNT(*) as total FROM jobs") as cur:
                row = await cur.fetchone()
                total_jobs = int(row["total"]) if row else 0

            async with conn.execute(
                "SELECT COUNT(DISTINCT job_id) as alerted FROM alerts_history WHERE status IN ('sent', 'mock')"
            ) as cur:
                row = await cur.fetchone()
                alerted_jobs = int(row["alerted"]) if row else 0

            if total_jobs > 0:
                match_rate = round((alerted_jobs / total_jobs) * 100, 1)
            else:
                match_rate = 0.0

            return {
                "matched_today": matched_today,
                "jobs_rejected": jobs_rejected,
                "last_scan": last_scan,
                "match_rate": match_rate,
            }


