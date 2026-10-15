"""
Adversarial Stress Test Suite for SQLite Database & Atomic Deduplication Engine (Milestone 2).

Tests:
1. Concurrency race condition: 20-50 simultaneous coroutines attempting reserve_alert_slot on the same job.
   Verifies exactly 1 wins (True) and all others get False.
2. Zero duplicate alert invariant across 5 repeated scans of identical and mixed job sets.
3. URL normalization permutations: varying schemes, tracking params, ports, fragments, and trailing slashes.
4. Database WAL mode concurrency: simulate concurrent reads and writes simultaneously.
"""

import asyncio
from pathlib import Path
import random
import tempfile
from typing import List
import pytest

from career_pulse.core.models import JobListing
from career_pulse.db.session import Database, generate_unique_key, normalize_url


@pytest.fixture
async def temp_adv_db():
    """Provides a temporary, isolated SQLite database instance for adversarial stress testing."""
    temp_dir = tempfile.mkdtemp()
    db_path = Path(temp_dir) / "test_adv_career_pulse.db"
    db = Database(str(db_path))
    await db.init_schema()
    yield db

    # Teardown with graceful Windows lock handling
    try:
        for f in Path(temp_dir).glob("test_adv_career_pulse.db*"):
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


# ==============================================================================
# 1. CONCURRENCY RACE CONDITION STRESS TESTS (20-50 COROUTINES)
# ==============================================================================

class TestConcurrencyRaceCondition:
    """Stress test atomic reservation under heavy concurrent coroutine competition."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("num_tasks", [20, 35, 50])
    async def test_reserve_alert_slot_high_concurrency_race(self, temp_adv_db: Database, num_tasks: int):
        """
        Verify that when 20 to 50 simultaneous coroutines attempt to reserve an alert slot
        for the same job, EXACTLY 1 wins (returns True) and all other (num_tasks - 1) get False.
        """
        db = temp_adv_db
        company_id = await db.add_company(f"RaceCo_{num_tasks}", "https://race.example.com", "lever")
        job = JobListing(
            external_id=f"race-{num_tasks}-001",
            company_name=f"RaceCo_{num_tasks}",
            provider="lever",
            title="Senior Concurrency Specialist",
            location="Remote",
            is_remote=True,
            url=f"https://race.example.com/jobs/{num_tasks}-001",
            description_text="High concurrency async systems",
        )
        job_id, is_new = await db.upsert_job(company_id, job)
        assert is_new is True

        # Launch num_tasks simultaneous coroutines
        barrier = asyncio.Event()

        async def worker():
            await barrier.wait()
            return await db.reserve_alert_slot(job_id, channel="telegram")

        tasks = [asyncio.create_task(worker()) for _ in range(num_tasks)]
        # Trigger all tasks simultaneously
        barrier.set()
        results = await asyncio.gather(*tasks)

        winners = sum(1 for r in results if r is True)
        losers = sum(1 for r in results if r is False)

        assert winners == 1, f"Expected exactly 1 winner among {num_tasks} coroutines, got {winners}"
        assert losers == num_tasks - 1, f"Expected {num_tasks - 1} losers, got {losers}"

        # Verify database alert row count is exactly 1
        async with await db.get_connection() as conn:
            async with conn.execute(
                "SELECT COUNT(*) FROM alerts_history WHERE job_id = ? AND channel = 'telegram'",
                (job_id,)
            ) as cur:
                count = (await cur.fetchone())[0]
                assert count == 1, f"Expected exactly 1 record in alerts_history, found {count}"


# ==============================================================================
# 2. ZERO DUPLICATE ALERT INVARIANT ACROSS 5 REPEATED SCANS
# ==============================================================================

class TestZeroDuplicateAlertRepeatedScans:
    """Stress test zero-duplicate invariant across 5 realistic scan cycles."""

    @pytest.mark.asyncio
    async def test_zero_duplicate_alert_across_5_scans(self, temp_adv_db: Database):
        """
        Simulate 5 consecutive scheduled scan cycles with identical and mixed batches:
        - Scan 1: 10 brand-new jobs (all 10 new, all 10 reserved)
        - Scan 2: Exactly identical 10 jobs (0 new, 0 reserved)
        - Scan 3: 10 existing jobs + 5 newly posted jobs (5 new, 5 reserved)
        - Scan 4: Exactly identical 15 jobs (0 new, 0 reserved)
        - Scan 5: Mixed subset (8 existing + 2 new jobs) (2 new, 2 reserved)
        Verify zero duplicate alerts were EVER reserved across all 5 scans.
        """
        db = temp_adv_db
        company_id = await db.add_company("ScanTargetCorp", "https://scantarget.com", "greenhouse")

        def make_job(idx: int) -> JobListing:
            return JobListing(
                external_id=f"gh-scan-{idx}",
                company_name="ScanTargetCorp",
                provider="greenhouse",
                title=f"Engineer Level {idx}",
                location="Remote - US",
                is_remote=True,
                url=f"https://boards.greenhouse.io/scantarget/jobs/{idx}?utm_source=scan",
                description_text=f"Role description for job {idx}",
            )

        batch_1_to_10 = [make_job(i) for i in range(1, 11)]
        batch_11_to_15 = [make_job(i) for i in range(11, 16)]
        batch_16_to_17 = [make_job(i) for i in range(16, 18)]

        total_alerts_reserved = 0

        # SCAN 1: 10 brand-new jobs
        scan_1_new = 0
        scan_1_reserved = 0
        for job in batch_1_to_10:
            jid, is_new = await db.upsert_job(company_id, job)
            if is_new:
                scan_1_new += 1
                if await db.reserve_alert_slot(jid, channel="telegram"):
                    scan_1_reserved += 1
                    await db.finalize_alert_status(jid, "telegram", "sent", preview=f"Job {job.external_id}")

        assert scan_1_new == 10
        assert scan_1_reserved == 10
        total_alerts_reserved += scan_1_reserved

        # SCAN 2: Identical 10 jobs
        scan_2_new = 0
        scan_2_reserved = 0
        for job in batch_1_to_10:
            jid, is_new = await db.upsert_job(company_id, job)
            if is_new:
                scan_2_new += 1
            # Even if alert check is called blindly:
            if await db.reserve_alert_slot(jid, channel="telegram"):
                scan_2_reserved += 1

        assert scan_2_new == 0, "Scan 2 should find 0 new jobs"
        assert scan_2_reserved == 0, "Scan 2 must reserve 0 alerts"
        total_alerts_reserved += scan_2_reserved

        # SCAN 3: 10 existing + 5 new jobs (jobs 1 to 15)
        scan_3_batch = batch_1_to_10 + batch_11_to_15
        scan_3_new = 0
        scan_3_reserved = 0
        for job in scan_3_batch:
            jid, is_new = await db.upsert_job(company_id, job)
            if is_new:
                scan_3_new += 1
            if await db.reserve_alert_slot(jid, channel="telegram"):
                scan_3_reserved += 1
                await db.finalize_alert_status(jid, "telegram", "sent", preview=f"Job {job.external_id}")

        assert scan_3_new == 5, f"Scan 3 should find exactly 5 new jobs, got {scan_3_new}"
        assert scan_3_reserved == 5, f"Scan 3 must reserve exactly 5 alerts, got {scan_3_reserved}"
        total_alerts_reserved += scan_3_reserved

        # SCAN 4: Identical 15 jobs (jobs 1 to 15)
        scan_4_new = 0
        scan_4_reserved = 0
        for job in scan_3_batch:
            jid, is_new = await db.upsert_job(company_id, job)
            if is_new:
                scan_4_new += 1
            if await db.reserve_alert_slot(jid, channel="telegram"):
                scan_4_reserved += 1

        assert scan_4_new == 0, "Scan 4 should find 0 new jobs"
        assert scan_4_reserved == 0, "Scan 4 must reserve 0 alerts"
        total_alerts_reserved += scan_4_reserved

        # SCAN 5: Mixed subset (8 existing jobs + 2 brand-new jobs 16, 17)
        scan_5_batch = batch_1_to_10[:8] + batch_16_to_17
        scan_5_new = 0
        scan_5_reserved = 0
        for job in scan_5_batch:
            jid, is_new = await db.upsert_job(company_id, job)
            if is_new:
                scan_5_new += 1
            if await db.reserve_alert_slot(jid, channel="telegram"):
                scan_5_reserved += 1
                await db.finalize_alert_status(jid, "telegram", "sent", preview=f"Job {job.external_id}")

        assert scan_5_new == 2, f"Scan 5 should find exactly 2 new jobs, got {scan_5_new}"
        assert scan_5_reserved == 2, f"Scan 5 must reserve exactly 2 alerts, got {scan_5_reserved}"
        total_alerts_reserved += scan_5_reserved

        # VERIFY INVARIANTS:
        # Total alerts reserved must equal 10 + 0 + 5 + 0 + 2 = 17
        assert total_alerts_reserved == 17

        # Verify DB contains exactly 17 records in alerts_history
        async with await db.get_connection() as conn:
            async with conn.execute("SELECT COUNT(*) FROM alerts_history") as cur:
                count = (await cur.fetchone())[0]
                assert count == 17, f"Expected 17 alert records in total, got {count}"

            # Verify no job_id appears more than once
            async with conn.execute(
                "SELECT job_id, COUNT(*) as c FROM alerts_history GROUP BY job_id HAVING c > 1"
            ) as cur:
                duplicates = await cur.fetchall()
                assert len(duplicates) == 0, f"Found duplicate alert reservations for job_ids: {duplicates}"


# ==============================================================================
# 3. URL NORMALIZATION PERMUTATIONS
# ==============================================================================

class TestURLNormalizationPermutations:
    """Stress test URL canonicalization across various schemes, ports, fragments, params, and slashes."""

    def test_scheme_variations(self):
        """Verify scheme variations (uppercase, lowercase, mixed case) normalize cleanly."""
        assert normalize_url("http://example.com/jobs/1") == "http://example.com/jobs/1"
        assert normalize_url("HTTP://example.com/jobs/1") == "http://example.com/jobs/1"
        assert normalize_url("Https://example.com/jobs/1") == "https://example.com/jobs/1"
        assert normalize_url("HTTPS://EXAMPLE.COM/jobs/1") == "https://example.com/jobs/1"
        assert normalize_url("hTtP://Example.Com/jobs/1") == "http://example.com/jobs/1"

    def test_tracking_parameter_permutations(self):
        """Verify query strings, marketing params, and tracking tokens are removed."""
        expected = "https://boards.greenhouse.io/acme/jobs/456"
        urls = [
            "https://boards.greenhouse.io/acme/jobs/456?gh_jid=456",
            "https://boards.greenhouse.io/acme/jobs/456?utm_source=linkedin&utm_medium=cpc&utm_campaign=hiring",
            "https://boards.greenhouse.io/acme/jobs/456?fbclid=IwAR09123xyz",
            "https://boards.greenhouse.io/acme/jobs/456?gclid=EAIaIQobChMI",
            "https://boards.greenhouse.io/acme/jobs/456?ref=referral&mode=preview&token=123",
            "https://boards.greenhouse.io/acme/jobs/456?",
            "https://boards.greenhouse.io/acme/jobs/456?foo=bar#apply",
        ]
        for u in urls:
            assert normalize_url(u) == expected, f"Failed to normalize {u}"

    def test_port_permutations(self):
        """Verify standard and custom ports are preserved in canonical netloc."""
        assert normalize_url("http://localhost:8080/jobs/1/") == "http://localhost:8080/jobs/1"
        assert normalize_url("HTTP://LOCALHOST:8080/jobs/1") == "http://localhost:8080/jobs/1"
        assert normalize_url("https://internal.corp:8443/careers/role/") == "https://internal.corp:8443/careers/role"

    def test_fragment_permutations(self):
        """Verify URL anchors/fragments are stripped."""
        assert normalize_url("https://example.com/careers/role#apply") == "https://example.com/careers/role"
        assert normalize_url("https://example.com/careers/role#section-qualifications") == "https://example.com/careers/role"
        assert normalize_url("https://example.com/careers/role#top") == "https://example.com/careers/role"

    def test_trailing_slashes_and_whitespace(self):
        """Verify single, multiple trailing slashes and surrounding whitespace are stripped."""
        assert normalize_url("https://example.com/jobs/role/") == "https://example.com/jobs/role"
        assert normalize_url("https://example.com/jobs/role///") == "https://example.com/jobs/role"
        assert normalize_url("   https://example.com/jobs/role/   ") == "https://example.com/jobs/role"
        assert normalize_url("https://example.com/") == "https://example.com"
        assert normalize_url("https://example.com///") == "https://example.com"
        assert normalize_url("") == ""
        assert normalize_url("    ") == ""

    @pytest.mark.asyncio
    async def test_fallback_url_hash_deduplication_under_permutations(self, temp_adv_db: Database):
        """
        Verify that custom jobs lacking official external_id use the canonical URL hash,
        preventing duplicates even when ingested with different tracking params and trailing slashes.
        """
        db = temp_adv_db
        company_id = await db.add_company("CustomPortalCorp", "https://customportal.com", "custom")

        # Ingestion 1: original URL
        job1 = JobListing(
            external_id="unknown",
            company_name="CustomPortalCorp",
            provider="custom",
            title="Full Stack Developer",
            location="Remote",
            url="https://customportal.com/careers/dev-101/?utm_source=indeed",
            description_text="Python & React",
        )
        jid1, is_new1 = await db.upsert_job(company_id, job1)
        assert is_new1 is True

        # Ingestion 2: different tracking params, trailing slashes, uppercase scheme
        job2 = JobListing(
            external_id="unknown",
            company_name="CustomPortalCorp",
            provider="custom",
            title="Full Stack Developer (Updated)",
            location="Remote",
            url="HTTPS://CUSTOMPORTAL.COM/careers/dev-101///?utm_campaign=spring&fbclid=xyz#apply",
            description_text="Python & React with Docker",
        )
        jid2, is_new2 = await db.upsert_job(company_id, job2)
        assert is_new2 is False, "Job with permuted URL should match existing canonical URL hash"
        assert jid2 == jid1


# ==============================================================================
# 4. DATABASE WAL MODE CONCURRENCY (SIMULTANEOUS READS AND WRITES)
# ==============================================================================

class TestDatabaseWALModeConcurrency:
    """Stress test SQLite WAL mode under concurrent simultaneous readers and writers."""

    @pytest.mark.asyncio
    async def test_concurrent_readers_and_writers_in_wal_mode(self, temp_adv_db: Database):
        """
        Simulate 25 concurrent writer coroutines and 25 concurrent reader coroutines
        accessing the database at the same time.
        Verify:
        - No 'database is locked' errors occur.
        - All writes succeed and commits are durable.
        - All reads execute cleanly and return consistent state.
        """
        db = temp_adv_db
        company_id = await db.add_company("WALStressCorp", "https://walstress.com", "greenhouse")

        start_barrier = asyncio.Event()

        # Writer coroutine: inserts or updates a unique job
        async def writer(worker_id: int):
            await start_barrier.wait()
            job = JobListing(
                external_id=f"wal-job-{worker_id}",
                company_name="WALStressCorp",
                provider="greenhouse",
                title=f"Concurrent Worker Role {worker_id}",
                location="Remote",
                is_remote=True,
                url=f"https://walstress.com/jobs/{worker_id}",
                description_text="Concurrency stress test",
            )
            jid, is_new = await db.upsert_job(company_id, job)
            reserved = await db.reserve_alert_slot(jid, channel="telegram")
            if reserved:
                await db.finalize_alert_status(jid, "telegram", "sent", preview=f"Role {worker_id}")
            return (jid, is_new, reserved)

        # Reader coroutine: repeatedly queries jobs and alert history
        async def reader(worker_id: int):
            await start_barrier.wait()
            results = []
            for _ in range(5):
                jobs = await db.get_jobs(company_id=company_id, limit=50)
                setting = await db.get_setting("filter_rules", default={})
                results.append(len(jobs))
                await asyncio.sleep(0.01)  # tiny yield
            return results

        writers = [asyncio.create_task(writer(i)) for i in range(25)]
        readers = [asyncio.create_task(reader(i)) for i in range(25)]

        # Start all tasks simultaneously
        start_barrier.set()

        writer_results = await asyncio.gather(*writers)
        reader_results = await asyncio.gather(*readers)

        # Assert all 25 writers succeeded
        assert len(writer_results) == 25
        assert all(is_new is True for (_, is_new, _) in writer_results)
        assert all(reserved is True for (_, _, reserved) in writer_results)

        # Assert all 25 readers succeeded without exceptions
        assert len(reader_results) == 25
        for r in reader_results:
            assert isinstance(r, list)
            assert len(r) == 5

        # Final verification: exactly 25 jobs and 25 alerts exist in the DB
        async with await db.get_connection() as conn:
            async with conn.execute("SELECT COUNT(*) FROM jobs WHERE company_id = ?", (company_id,)) as cur:
                job_count = (await cur.fetchone())[0]
                assert job_count == 25

            async with conn.execute("SELECT COUNT(*) FROM alerts_history") as cur:
                alert_count = (await cur.fetchone())[0]
                assert alert_count == 25
