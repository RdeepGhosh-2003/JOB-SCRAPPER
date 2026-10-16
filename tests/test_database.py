"""
Unit tests for CareerPulse SQLite Database & Deduplication Engine (Milestone 2).
"""

import asyncio
from pathlib import Path
import tempfile
import pytest

from career_pulse.core.models import JobListing
from career_pulse.db.session import Database, generate_unique_key, normalize_url


@pytest.fixture
async def temp_db():
    """Provides a temporary, isolated SQLite database instance for testing."""
    temp_dir = tempfile.mkdtemp()
    db_path = Path(temp_dir) / "test_career_pulse.db"
    db = Database(str(db_path))
    await db.init_schema()
    yield db

    # Teardown with graceful Windows lock handling
    try:
        for f in Path(temp_dir).glob("test_career_pulse.db*"):
            try:
                f.unlink()
            except Exception:
                pass
        try:
            Path(temp_dir).rmdir()
        except Exception:
            pass
    except Exception:
        pass


@pytest.mark.asyncio
async def test_init_schema_and_pragmas(temp_db: Database):
    """Verify SQLite WAL mode, foreign keys, and created schema tables."""
    async with await temp_db.get_connection() as conn:
        async with conn.execute("PRAGMA journal_mode;") as cur:
            row = await cur.fetchone()
            assert row[0].lower() == "wal", f"Expected WAL mode, got {row[0]}"

        async with conn.execute("PRAGMA foreign_keys;") as cur:
            row = await cur.fetchone()
            assert row[0] == 1, "Foreign keys must be active"

        async with conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"
        ) as cur:
            tables = [r[0] for r in await cur.fetchall()]
            for expected in ["companies", "jobs", "alerts_history", "settings"]:
                assert expected in tables, f"Expected table '{expected}' not found"


def test_normalize_url():
    """Verify tracking parameters, fragments, and trailing slashes are canonicalized."""
    assert normalize_url("https://boards.greenhouse.io/acme/jobs/12345?gh_jid=12345&source=linkedin") == \
        "https://boards.greenhouse.io/acme/jobs/12345"

    assert normalize_url("HTTP://JOBS.LEVER.CO/NETFLIX/abc-def/") == \
        "http://jobs.lever.co/NETFLIX/abc-def"

    assert normalize_url("https://example.com/careers/role#section-apply") == \
        "https://example.com/careers/role"

    assert normalize_url("") == ""
    assert normalize_url("   ") == ""


def test_generate_unique_key():
    """Verify deterministic key generation using external ID or canonical URL hash."""
    # Standard external ID key
    key1 = generate_unique_key("greenhouse", 42, "100200", "https://boards.greenhouse.io/acme/jobs/100200")
    assert key1 == "greenhouse:42:100200"

    # Fallback to URL hash when external_id is empty or unknown
    key2 = generate_unique_key("custom", 10, "", "https://example.com/jobs/dev-1")
    assert key2.startswith("url_hash:")
    assert len(key2.split(":")[1]) == 16

    key3 = generate_unique_key("custom", 10, "unknown", "https://example.com/jobs/dev-1")
    assert key3 == key2, "Fallback hash should match for same canonical URL"


@pytest.mark.asyncio
async def test_upsert_job_lifecycle(temp_db: Database):
    """Verify job ingestion returns (id, True) on first insert and (id, False) on re-scan."""
    company_id = await temp_db.add_company("Acme Corp", "https://boards.greenhouse.io/acme", "greenhouse")

    job = JobListing(
        external_id="gh-777",
        company_name="Acme Corp",
        provider="greenhouse",
        title="Backend Software Engineer",
        location="Remote",
        is_remote=True,
        url="https://boards.greenhouse.io/acme/jobs/777?utm_source=crawler",
        description_text="Python & FastAPI services.",
        raw_payload={"id": 777, "title": "Backend Software Engineer"},
    )

    # 1. First insert
    job_id1, is_new1 = await temp_db.upsert_job(company_id, job)
    assert is_new1 is True
    assert job_id1 > 0

    record1 = await temp_db.get_job_by_id(job_id1)
    assert record1 is not None
    assert record1["title"] == "Backend Software Engineer"
    assert record1["canonical_url"] == "https://boards.greenhouse.io/acme/jobs/777"
    assert record1["is_remote"] == 1

    # 2. Second scan (same job, updated description)
    updated_job = JobListing(
        external_id="gh-777",
        company_name="Acme Corp",
        provider="greenhouse",
        title="Backend Software Engineer (Updated)",
        location="Remote - US",
        is_remote=True,
        url="https://boards.greenhouse.io/acme/jobs/777?utm_source=rescan",
        description_text="Python, FastAPI, and PostgreSQL.",
    )
    job_id2, is_new2 = await temp_db.upsert_job(company_id, updated_job)
    assert is_new2 is False
    assert job_id2 == job_id1

    record2 = await temp_db.get_job_by_id(job_id1)
    assert record2["title"] == "Backend Software Engineer (Updated)"
    assert record2["location"] == "Remote - US"


@pytest.mark.asyncio
async def test_zero_duplicate_alert_deduplication(temp_db: Database):
    """
    CRITICAL INVARIANT TEST:
    Verify that reserve_alert_slot acquires the slot exactly once,
    and returns False on all subsequent attempts (Zero Duplicate Alerts).
    """
    company_id = await temp_db.add_company("Globex", "https://globex.com", "custom")
    job = JobListing(
        external_id="gb-101",
        company_name="Globex",
        provider="custom",
        title="Platform Engineer",
        location="Remote",
        is_remote=True,
        url="https://globex.com/job/101",
        description_text="Cloud infrastructure",
    )
    job_id, is_new = await temp_db.upsert_job(company_id, job)
    assert is_new is True

    # First reservation attempt: must succeed
    slot1 = await temp_db.reserve_alert_slot(job_id, channel="telegram")
    assert slot1 is True

    # Finalize status to 'sent'
    await temp_db.finalize_alert_status(job_id, channel="telegram", status="sent", preview="Test alert")
    alert = await temp_db.get_alert(job_id, channel="telegram")
    assert alert is not None
    assert alert["status"] == "sent"
    assert alert["message_preview"] == "Test alert"

    # Re-scan in next scheduled cycle (simulated)
    _, is_new_again = await temp_db.upsert_job(company_id, job)
    assert is_new_again is False

    # Second reservation attempt: MUST return False (Duplicate dropped)
    slot2 = await temp_db.reserve_alert_slot(job_id, channel="telegram")
    assert slot2 is False

    # Check alert table row count remains exactly 1
    async with await temp_db.get_connection() as conn:
        async with conn.execute("SELECT COUNT(*) FROM alerts_history WHERE job_id = ?", (job_id,)) as cur:
            count = (await cur.fetchone())[0]
            assert count == 1


@pytest.mark.asyncio
async def test_incremental_batch_ingestion(temp_db: Database):
    """Verify batch ingestion correctly segregates existing jobs from new jobs."""
    company_id = await temp_db.add_company("Initech", "https://initech.com", "ashby")

    batch_1 = [
        JobListing(
            external_id=f"init-{i}",
            company_name="Initech",
            provider="ashby",
            title=f"Engineer {i}",
            location="Remote",
            is_remote=True,
            url=f"https://initech.com/jobs/{i}",
            description_text="Python",
        )
        for i in range(1, 6)
    ]

    # Ingest Batch 1 (5 jobs)
    for j in batch_1:
        jid, is_new = await temp_db.upsert_job(company_id, j)
        assert is_new is True
        assert await temp_db.reserve_alert_slot(jid, "telegram") is True

    # Ingest Batch 2 (5 existing + 2 new jobs)
    batch_2 = batch_1 + [
        JobListing(
            external_id="init-6",
            company_name="Initech",
            provider="ashby",
            title="Engineer 6",
            location="Remote",
            is_remote=True,
            url="https://initech.com/jobs/6",
            description_text="Python",
        ),
        JobListing(
            external_id="init-7",
            company_name="Initech",
            provider="ashby",
            title="Engineer 7",
            location="Remote",
            is_remote=True,
            url="https://initech.com/jobs/7",
            description_text="Python",
        ),
    ]

    new_count = 0
    new_reserved = 0
    for j in batch_2:
        jid, is_new = await temp_db.upsert_job(company_id, j)
        if is_new:
            new_count += 1
            if await temp_db.reserve_alert_slot(jid, "telegram"):
                new_reserved += 1

    assert new_count == 2
    assert new_reserved == 2


@pytest.mark.asyncio
async def test_concurrent_atomic_slot_reservation_race(temp_db: Database):
    """
    STRESS TEST:
    Simulate 10 concurrent async tasks attempting to reserve an alert slot
    simultaneously for the exact same job.
    Exactly 1 task must succeed (True); exactly 9 must fail (False).
    """
    company_id = await temp_db.add_company("RaceCorp", "https://race.com", "lever")
    job = JobListing(
        external_id="race-001",
        company_name="RaceCorp",
        provider="lever",
        title="High Concurrency Engineer",
        location="Remote",
        is_remote=True,
        url="https://race.com/jobs/001",
        description_text="asyncio concurrency",
    )
    job_id, _ = await temp_db.upsert_job(company_id, job)

    async def attempt():
        return await temp_db.reserve_alert_slot(job_id, channel="telegram")

    results = await asyncio.gather(*[attempt() for _ in range(10)])

    successes = sum(1 for r in results if r is True)
    failures = sum(1 for r in results if r is False)

    assert successes == 1, f"Expected exactly 1 winner in atomic race, got {successes}"
    assert failures == 9, f"Expected 9 dropped reservations, got {failures}"


@pytest.mark.asyncio
async def test_settings_storage(temp_db: Database):
    """Verify JSON-serialized settings storage and retrieval."""
    test_config = {
        "target_titles": ["Python Developer", "Full Stack"],
        "max_alerts_per_run": 25,
        "active": True,
    }
    await temp_db.set_setting("filter_rules", test_config)

    retrieved = await temp_db.get_setting("filter_rules")
    assert retrieved == test_config

    # Default fallback
    missing = await temp_db.get_setting("non_existent_key", default={"fallback": True})
    assert missing == {"fallback": True}


@pytest.mark.asyncio
async def test_foreign_key_cascading_delete(temp_db: Database):
    """Verify ON DELETE CASCADE removes associated jobs and alert history."""
    company_id = await temp_db.add_company("Ephemeral Corp", "https://ephemeral.com", "workday")
    job = JobListing(
        external_id="eph-1",
        company_name="Ephemeral Corp",
        provider="workday",
        title="DevOps Engineer",
        location="Remote",
        is_remote=True,
        url="https://ephemeral.com/jobs/1",
        description_text="Terraform & AWS",
    )
    job_id, _ = await temp_db.upsert_job(company_id, job)
    await temp_db.reserve_alert_slot(job_id, "telegram")

    # Delete company
    async with await temp_db.get_connection() as conn:
        await conn.execute("DELETE FROM companies WHERE id = ?", (company_id,))
        await conn.commit()

    # Job and alert must be deleted via cascade
    assert await temp_db.get_job_by_id(job_id) is None
    assert await temp_db.get_alert(job_id, "telegram") is None


@pytest.mark.asyncio
async def test_scan_logs_persistence_and_purge(temp_db: Database):
    """Verify scan logs writing, limit retrieval, and retention pruning to 200 items."""
    # Write 205 log entries
    for i in range(205):
        await temp_db.write_scan_log(
            company_name=f"Company {i}",
            company_id=1,
            provider="greenhouse",
            jobs_found=5,
            jobs_matched=1 if i % 2 == 0 else 0,
            alerts_sent=1 if i % 2 == 0 else 0,
            duration_seconds=1.25,
            status="success" if i % 2 == 0 else "warning",
        )

    # Retrieval respects limit
    logs_50 = await temp_db.get_scan_logs(limit=50)
    assert len(logs_50) == 50
    assert logs_50[0]["company_name"] == "Company 204"

    # Total entries must not exceed 200 due to automatic pruning
    all_logs = await temp_db.get_scan_logs(limit=300)
    assert len(all_logs) == 200
    assert all_logs[0]["company_name"] == "Company 204"
    assert all_logs[-1]["company_name"] == "Company 5"


@pytest.mark.asyncio
async def test_overview_stats_calculation(temp_db: Database):
    """Verify aggregated metrics: matched_today, jobs_rejected, last_scan, match_rate."""
    company_id = await temp_db.add_company("StatsCorp", "https://stats.com", "greenhouse")

    # Add 4 jobs
    j1 = JobListing(external_id="s-1", company_name="StatsCorp", provider="greenhouse", title="Job 1", location="Remote", url="https://stats.com/1")
    j2 = JobListing(external_id="s-2", company_name="StatsCorp", provider="greenhouse", title="Job 2", location="Remote", url="https://stats.com/2")
    j3 = JobListing(external_id="s-3", company_name="StatsCorp", provider="greenhouse", title="Job 3", location="Remote", url="https://stats.com/3")
    j4 = JobListing(external_id="s-4", company_name="StatsCorp", provider="greenhouse", title="Job 4", location="Remote", url="https://stats.com/4")

    id1, _ = await temp_db.upsert_job(company_id, j1)
    id2, _ = await temp_db.upsert_job(company_id, j2)
    id3, _ = await temp_db.upsert_job(company_id, j3)
    id4, _ = await temp_db.upsert_job(company_id, j4)

    # Reserve & finalize alert for j1 (sent)
    await temp_db.reserve_alert_slot(id1, "telegram")
    await temp_db.finalize_alert_status(id1, "telegram", "sent")

    # Log a scan
    await temp_db.write_scan_log(
        company_name="StatsCorp",
        company_id=company_id,
        provider="greenhouse",
        jobs_found=4,
        jobs_matched=1,
        alerts_sent=1,
        duration_seconds=1.5,
        status="success",
    )

    stats = await temp_db.get_overview_stats()
    assert stats["matched_today"] == 1
    assert stats["jobs_rejected"] == 3  # id2, id3, id4 have no alert
    assert stats["last_scan"]["company_name"] == "StatsCorp"
    assert stats["match_rate"] == 25.0  # 1/4 * 100


