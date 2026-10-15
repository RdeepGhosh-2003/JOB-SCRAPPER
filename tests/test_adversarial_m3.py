"""
Adversarial Stress Test Suite for Milestone 3 (Telegram Notification Service):
- Concurrent delivery stress test: 50 concurrent async tasks and multi-threaded dispatching
  through MockTelegramSink simultaneously with zero message drops and exact count preservation.
- Mock credential validation vs live credential edge cases (empty strings, None, whitespace,
  invalid tokens, missing chat IDs, HTTP 401/404/500, network connection errors).
- HTTP 429 rate limit backoff, malformed retry parameters, and exhaustion handling.
- Database alert state transition: verify that dispatch_job_alert properly updates alerts_history
  status from 'pending' to 'mock' / 'sent', and correctly records error_message on simulated
  failure without leaving orphaned 'pending' locks.
- Concurrency and idempotency audits on duplicate alert prevention.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
import tempfile
from typing import Any, Dict, List, Optional
import httpx
import pytest

from career_pulse.core.models import FilterResult, JobListing
from career_pulse.db.session import Database
from career_pulse.services.telegram import (
    MockTelegramSink,
    TelegramNotifier,
    dispatch_job_alert,
)


@pytest.fixture(autouse=True)
def clean_mock_sink():
    """Ensure MockTelegramSink is completely clean before and after each test."""
    MockTelegramSink.clear()
    yield
    MockTelegramSink.clear()


@pytest.fixture
async def temp_adv_db():
    """Provides a clean temporary SQLite database instance with WAL mode."""
    temp_dir = tempfile.mkdtemp()
    db_path = Path(temp_dir) / "test_adv_m3_alerts.db"
    db = Database(str(db_path))
    await db.init_schema()
    yield db

    # Windows cleanup
    try:
        for f in Path(temp_dir).glob("test_adv_m3_alerts.db*"):
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
# 1. MOCK TELEGRAM SINK CONCURRENCY & STRESS TESTS
# ==============================================================================

class TestMockTelegramSinkStress:
    """Stress test MockTelegramSink concurrency, race immunity, and count preservation."""

    @pytest.mark.asyncio
    async def test_concurrent_delivery_50_async_tasks(self):
        """
        Verify 50 concurrent async tasks dispatching messages through MockTelegramSink
        simultaneously experience zero drops, exact count preservation, and thread-safety.
        """
        notifier = TelegramNotifier(mock_mode=True, chat_id="stress_chat_1")
        assert len(MockTelegramSink.sent_messages) == 0

        barrier = asyncio.Event()

        async def worker(task_id: int) -> bool:
            await barrier.wait()
            return await notifier.send_message(f"Concurrent task message {task_id}")

        tasks = [asyncio.create_task(worker(i)) for i in range(50)]
        barrier.set()

        results = await asyncio.gather(*tasks)

        # Assert all 50 tasks succeeded
        assert all(results)
        assert len(results) == 50

        # Verify exact count preservation in sink
        sent = MockTelegramSink.get_messages()
        assert len(sent) == 50, f"Expected 50 messages, got {len(sent)}"
        assert len(MockTelegramSink.sent_messages) == 50

        # Verify all message payloads are present with zero drops
        received_texts = {m["text"] for m in sent}
        for i in range(50):
            expected = f"Concurrent task message {i}"
            assert expected in received_texts, f"Message '{expected}' was dropped!"

        # Verify chat_id and parse_mode integrity
        for m in sent:
            assert m["chat_id"] == "stress_chat_1"
            assert m["parse_mode"] == "HTML"
            assert "timestamp" in m

    def test_mock_sink_thread_safety_50_threads(self):
        """
        Verify MockTelegramSink is thread-safe when 50 OS threads call record()
        simultaneously via ThreadPoolExecutor.
        """
        MockTelegramSink.clear()

        def worker(thread_id: int):
            MockTelegramSink.record({
                "chat_id": f"thread_{thread_id}",
                "text": f"Thread message payload {thread_id}",
            })

        with ThreadPoolExecutor(max_workers=50) as executor:
            list(executor.map(worker, range(50)))

        assert len(MockTelegramSink.sent_messages) == 50
        history = MockTelegramSink.get_history()
        assert len(history) == 50

        thread_texts = {m["text"] for m in history}
        for i in range(50):
            assert f"Thread message payload {i}" in thread_texts

    @pytest.mark.asyncio
    async def test_mock_sink_100_burst_concurrent_large_payloads(self):
        """
        Verify 100 simultaneous concurrent dispatches carrying large 2KB payloads.
        Verifies zero drops and no payload truncation.
        """
        notifier = TelegramNotifier(mock_mode=True)
        large_body = "A" * 2000

        async def send_large(idx: int) -> bool:
            return await notifier.send_message(f"Msg-{idx}: {large_body}")

        tasks = [send_large(i) for i in range(100)]
        results = await asyncio.gather(*tasks)

        assert all(results)
        messages = MockTelegramSink.get_messages()
        assert len(messages) == 100
        for m in messages:
            assert large_body in m["text"]

    def test_mock_sink_defensive_copies(self):
        """Verify mutating returned dict from get_last_message or get_messages does not corrupt sink."""
        MockTelegramSink.record({"chat_id": "orig_chat", "text": "original_content"})

        last = MockTelegramSink.get_last_message()
        assert last is not None
        last["text"] = "tampered"
        last["chat_id"] = "tampered_chat"

        fresh = MockTelegramSink.get_last_message()
        assert fresh is not None
        assert fresh["text"] == "original_content"
        assert fresh["chat_id"] == "orig_chat"

        all_msgs = MockTelegramSink.get_messages()
        all_msgs[0]["text"] = "tampered_again"
        fresh_again = MockTelegramSink.get_last_message()
        assert fresh_again["text"] == "original_content"

    def test_mock_sink_capture_context_manager(self):
        """Verify capture() context manager cleanly isolates test block and restores clean state."""
        MockTelegramSink.record({"chat_id": "pre", "text": "pre_test"})
        assert len(MockTelegramSink.sent_messages) == 1

        with MockTelegramSink.capture() as sink:
            assert len(sink.sent_messages) == 0
            sink.record({"chat_id": "inner", "text": "inside_context"})
            assert len(sink.sent_messages) == 1
            assert sink.get_last_message()["text"] == "inside_context"

        # After block exit, sink is cleared
        assert len(MockTelegramSink.sent_messages) == 0
        assert MockTelegramSink.get_last_message() is None


# ==============================================================================
# 2. CREDENTIAL VALIDATION & RATE LIMITING EDGE CASES
# ==============================================================================

class TestCredentialValidationAndRateLimitingEdgeCases:
    """Stress test mock and live credential edge cases, HTTP 429 backoff, and network failures."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("bot_token", ["", "   ", None, "invalid_tok_123"])
    @pytest.mark.parametrize("chat_id", ["", "   ", None, "12345"])
    async def test_mock_credential_validation_permutations(self, bot_token: Optional[str], chat_id: Optional[str]):
        """
        Verify mock credential validation always returns valid=True and mock=True
        regardless of missing, whitespace, None, or dummy tokens.
        """
        notifier = TelegramNotifier(bot_token=bot_token, chat_id=chat_id, mock_mode=True)
        res = await notifier.verify_credentials()

        assert res.get("valid") is True
        assert res.get("mock") is True
        assert "MockCareerPulseBot" in res.get("bot_name", "")
        assert "verified" in res.get("message", "").lower()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("empty_token", ["", "   ", None])
    async def test_live_credentials_empty_or_whitespace_tokens(self, empty_token: Optional[str]):
        """
        Verify that in live mode (mock_mode=False), empty, whitespace, or None tokens
        are rejected immediately with valid=False without making any HTTP network request.
        """
        notifier = TelegramNotifier(bot_token=empty_token, mock_mode=False)
        res = await notifier.verify_credentials()

        assert res.get("valid") is False
        assert res.get("mock") is False
        assert "not configured" in res.get("error", "").lower() or "empty" in res.get("error", "").lower()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status_code, error_desc", [
        (401, "Unauthorized: bot token is invalid"),
        (404, "Not Found"),
        (500, "Internal Server Error"),
    ])
    async def test_live_credentials_http_error_responses(self, status_code: int, error_desc: str):
        """
        Verify live credential check handles HTTP 401, 404, 500 error responses from /getMe cleanly.
        """
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(status_code, text=error_desc)

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        notifier = TelegramNotifier(bot_token="invalid_token_99", mock_mode=False, client=client)

        res = await notifier.verify_credentials()
        assert res.get("valid") is False
        assert res.get("mock") is False
        assert str(status_code) in res.get("error", "")

    @pytest.mark.asyncio
    async def test_live_credentials_network_timeout_and_connection_error(self):
        """Verify network connection errors during /getMe return valid=False with error message."""
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Connection refused by peer")

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        notifier = TelegramNotifier(bot_token="token_net_err", mock_mode=False, client=client)

        res = await notifier.verify_credentials()
        assert res.get("valid") is False
        assert res.get("mock") is False
        assert "Network error" in res.get("error", "") or "Connection refused" in res.get("error", "")

    @pytest.mark.asyncio
    async def test_live_credentials_chat_ping_failure(self):
        """
        Verify when bot token is valid (/getMe returns 200), but chat_id is invalid
        (/sendMessage returns 400 Bad Request), verify_credentials reports chat delivery failure.
        """
        def handler(request: httpx.Request) -> httpx.Response:
            if "getMe" in str(request.url):
                return httpx.Response(200, json={"ok": True, "result": {"id": 1, "username": "TestBot"}})
            if "sendMessage" in str(request.url):
                return httpx.Response(400, json={"ok": False, "description": "Bad Request: chat not found"})
            return httpx.Response(404)

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        notifier = TelegramNotifier(bot_token="tok", chat_id="bad_chat_id", mock_mode=False, client=client)

        res = await notifier.verify_credentials()
        assert res.get("valid") is False
        assert "failed to deliver test message" in res.get("error", "").lower()
        assert res.get("bot_username") == "TestBot"

    @pytest.mark.asyncio
    async def test_rate_limiting_429_single_retry_success(self):
        """Verify HTTP 429 response initiates sleep based on retry_after and succeeds on second attempt."""
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            if calls == 1:
                return httpx.Response(429, json={"parameters": {"retry_after": 0.01}})
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 101}})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        notifier = TelegramNotifier(bot_token="token_429", chat_id="chat_429", mock_mode=False, client=client)

        sent = await notifier.send_message("<b>Retry message</b>")
        assert sent is True
        assert calls == 2
        assert notifier.last_error is None

    @pytest.mark.asyncio
    async def test_rate_limiting_429_exhausted_retry_returns_false(self):
        """Verify persistent HTTP 429 after retry returns False and sets last_error."""
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(429, json={"parameters": {"retry_after": 0.01}})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        notifier = TelegramNotifier(bot_token="token_429_exhaust", chat_id="chat_429", mock_mode=False, client=client)

        sent = await notifier.send_message("<b>Flood message</b>")
        assert sent is False
        assert calls == 2
        assert notifier.last_error is not None
        assert "429" in notifier.last_error

    @pytest.mark.asyncio
    async def test_rate_limiting_429_malformed_retry_after_json(self):
        """Verify HTTP 429 with non-numeric or missing retry_after parameter does not crash."""
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            if calls == 1:
                # Malformed parameters object
                return httpx.Response(429, json={"parameters": {"retry_after": "not-a-number"}})
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 102}})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        notifier = TelegramNotifier(bot_token="token_malformed_429", chat_id="chat_429", mock_mode=False, client=client)

        sent = await notifier.send_message("<b>Malformed 429 Test</b>")
        assert sent is True
        assert calls == 2


# ==============================================================================
# 3. DATABASE ALERT STATE TRANSITIONS & ZERO ORPHANED 'PENDING' LOCKS
# ==============================================================================

class TestDatabaseAlertStateTransitions:
    """Stress test database alert transitions: 'pending' -> 'mock' / 'sent' / 'failed'."""

    @pytest.mark.asyncio
    async def test_alert_state_transition_mock_success(self, temp_adv_db: Database):
        """
        Verify dispatch_job_alert in mock mode transitions alert from initial state
        to 'mock', setting message_preview and sent_at, with zero orphaned 'pending' records.
        """
        db = temp_adv_db
        company_id = await db.add_company("MockTransCo", "https://mocktrans.com", "greenhouse")
        job = JobListing(
            external_id="mock-job-01",
            company_name="MockTransCo",
            provider="greenhouse",
            title="Senior Mock Specialist",
            url="https://mocktrans.com/jobs/01",
        )
        job_id, is_new = await db.upsert_job(company_id, job)
        assert is_new is True

        match = FilterResult(matched=True, matched_skills=["Python"])
        notifier = TelegramNotifier(mock_mode=True)

        sent = await notifier.dispatch_job_alert(db, job_id, job, match)
        assert sent is True
        assert len(MockTelegramSink.sent_messages) == 1

        # Check DB state
        alert = await db.get_alert(job_id, channel="telegram")
        assert alert is not None
        assert alert["status"] == "mock", f"Expected status 'mock', found '{alert['status']}'"
        assert alert["message_preview"] == "[MockTransCo] Senior Mock Specialist"
        assert alert["error_message"] is None
        assert alert["sent_at"] is not None

        # Verify NO orphaned 'pending' rows exist in the entire database
        async with await db.get_connection() as conn:
            async with conn.execute("SELECT COUNT(*) FROM alerts_history WHERE status = 'pending'") as cur:
                pending_count = (await cur.fetchone())[0]
                assert pending_count == 0, f"Found {pending_count} orphaned 'pending' alerts!"

    @pytest.mark.asyncio
    async def test_alert_state_transition_live_success(self, temp_adv_db: Database):
        """
        Verify live delivery transitions status from 'pending' to 'sent' upon HTTP 200,
        leaving zero orphaned 'pending' records.
        """
        db = temp_adv_db
        company_id = await db.add_company("LiveTransCo", "https://livetrans.com", "lever")
        job = JobListing(
            external_id="live-job-01",
            company_name="LiveTransCo",
            provider="lever",
            title="Live Alert Specialist",
            url="https://livetrans.com/jobs/01",
        )
        job_id, is_new = await db.upsert_job(company_id, job)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 555}})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        notifier = TelegramNotifier(bot_token="live_token", chat_id="live_chat", mock_mode=False, client=client)

        match = FilterResult(matched=True)
        sent = await notifier.dispatch_job_alert(db, job_id, job, match)
        assert sent is True

        alert = await db.get_alert(job_id, channel="telegram")
        assert alert is not None
        assert alert["status"] == "sent", f"Expected status 'sent', found '{alert['status']}'"
        assert alert["message_preview"] == "[LiveTransCo] Live Alert Specialist"
        assert alert["error_message"] is None

        # Verify NO orphaned 'pending' rows exist
        async with await db.get_connection() as conn:
            async with conn.execute("SELECT COUNT(*) FROM alerts_history WHERE status = 'pending'") as cur:
                pending_count = (await cur.fetchone())[0]
                assert pending_count == 0, f"Found {pending_count} orphaned 'pending' alerts!"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("simulated_failure_case", [
        ("http_500", 500, "Internal Server Error"),
        ("http_400", 400, "Bad Request: chat not found"),
        ("http_429", 429, "Too Many Requests"),
    ])
    async def test_alert_state_transition_simulated_http_failure(
        self,
        temp_adv_db: Database,
        simulated_failure_case,
    ):
        """
        Verify simulated HTTP failures (500, 400, 429) transition alert status
        from 'pending' to 'failed' and record the error message, leaving NO orphaned 'pending' locks.
        """
        case_name, status_code, error_text = simulated_failure_case
        db = temp_adv_db
        company_id = await db.add_company(f"FailCo_{case_name}", f"https://fail_{case_name}.com", "ashby")
        job = JobListing(
            external_id=f"fail-job-{case_name}",
            company_name=f"FailCo_{case_name}",
            provider="ashby",
            title=f"Failure Role {case_name}",
            url=f"https://fail.com/{case_name}",
        )
        job_id, _ = await db.upsert_job(company_id, job)

        def handler(request: httpx.Request) -> httpx.Response:
            if status_code == 429:
                return httpx.Response(429, json={"parameters": {"retry_after": 0.01}})
            return httpx.Response(status_code, text=error_text)

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        notifier = TelegramNotifier(bot_token="tok_fail", chat_id="chat_fail", mock_mode=False, client=client)

        match = FilterResult(matched=True)
        sent = await notifier.dispatch_job_alert(db, job_id, job, match)
        assert sent is False

        # Alert status must be updated to 'failed'
        alert = await db.get_alert(job_id, channel="telegram")
        assert alert is not None
        assert alert["status"] == "failed", f"Expected status 'failed', got '{alert['status']}'"
        assert alert["error_message"] is not None
        assert str(status_code) in alert["error_message"]

        # Verify NO orphaned 'pending' rows exist
        async with await db.get_connection() as conn:
            async with conn.execute("SELECT COUNT(*) FROM alerts_history WHERE status = 'pending'") as cur:
                pending_count = (await cur.fetchone())[0]
                assert pending_count == 0, f"Found {pending_count} orphaned 'pending' locks!"

    @pytest.mark.asyncio
    async def test_alert_state_transition_network_exception(self, temp_adv_db: Database):
        """
        Verify network exceptions (e.g. ConnectError) during dispatch update status
        to 'failed' with error_message recorded, without leaving an orphaned 'pending' lock.
        """
        db = temp_adv_db
        company_id = await db.add_company("NetFailCo", "https://netfail.com", "lever")
        job = JobListing(
            external_id="net-fail-job",
            company_name="NetFailCo",
            provider="lever",
            title="Network Failure Engineer",
            url="https://netfail.com/jobs/1",
        )
        job_id, _ = await db.upsert_job(company_id, job)

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Network unreachable")

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        notifier = TelegramNotifier(bot_token="tok_net", chat_id="chat_net", mock_mode=False, client=client)

        match = FilterResult(matched=True)
        sent = await notifier.dispatch_job_alert(db, job_id, job, match)
        assert sent is False

        alert = await db.get_alert(job_id, channel="telegram")
        assert alert is not None
        assert alert["status"] == "failed"
        assert "network" in alert["error_message"].lower() or "unreachable" in alert["error_message"].lower()

        # Check for zero orphaned pending records
        async with await db.get_connection() as conn:
            async with conn.execute("SELECT COUNT(*) FROM alerts_history WHERE status = 'pending'") as cur:
                assert (await cur.fetchone())[0] == 0

    @pytest.mark.asyncio
    async def test_alert_state_transition_missing_live_credentials(self, temp_adv_db: Database):
        """
        Verify live dispatch with missing token or chat ID updates status to 'failed'
        and records the missing credential error message, leaving no orphaned 'pending' lock.
        """
        db = temp_adv_db
        company_id = await db.add_company("NoCredsCo", "https://nocreds.com", "greenhouse")
        job = JobListing(
            external_id="no-creds-job",
            company_name="NoCredsCo",
            provider="greenhouse",
            title="Missing Creds Engineer",
            url="https://nocreds.com/jobs/1",
        )
        job_id, _ = await db.upsert_job(company_id, job)

        # Live mode with no bot token and no chat id
        notifier = TelegramNotifier(bot_token="", chat_id="", mock_mode=False)

        match = FilterResult(matched=True)
        sent = await notifier.dispatch_job_alert(db, job_id, job, match)
        assert sent is False

        alert = await db.get_alert(job_id, channel="telegram")
        assert alert is not None
        assert alert["status"] == "failed"
        assert "missing" in alert["error_message"].lower()

        # Check zero orphaned pending records
        async with await db.get_connection() as conn:
            async with conn.execute("SELECT COUNT(*) FROM alerts_history WHERE status = 'pending'") as cur:
                assert (await cur.fetchone())[0] == 0

    @pytest.mark.asyncio
    async def test_second_dispatch_rejection_leaves_status_intact(self, temp_adv_db: Database):
        """
        Verify that a second call to dispatch_job_alert for an already alerted job
        is rejected by reservation conflict and does NOT alter or overwrite the existing status.
        """
        db = temp_adv_db
        company_id = await db.add_company("IdempCo", "https://idemp.com", "lever")
        job = JobListing(
            external_id="idemp-job-01",
            company_name="IdempCo",
            provider="lever",
            title="Idempotency Architect",
            url="https://idemp.com/jobs/01",
        )
        job_id, _ = await db.upsert_job(company_id, job)
        match = FilterResult(matched=True)
        notifier = TelegramNotifier(mock_mode=True)

        # First dispatch -> 'mock'
        first_res = await notifier.dispatch_job_alert(db, job_id, job, match)
        assert first_res is True

        alert_first = await db.get_alert(job_id, channel="telegram")
        assert alert_first["status"] == "mock"

        # Second dispatch -> rejected
        second_res = await notifier.dispatch_job_alert(db, job_id, job, match)
        assert second_res is False

        alert_second = await db.get_alert(job_id, channel="telegram")
        assert alert_second["status"] == "mock"
        assert alert_second["sent_at"] == alert_first["sent_at"]

    @pytest.mark.asyncio
    async def test_unhandled_exception_between_reserve_and_finalize_audit(self, temp_adv_db: Database):
        """
        Architectural vulnerability audit:
        If an unhandled exception or task cancellation occurs after reserve_alert_slot()
        executes but before finalize_alert_status() completes, the row remains in 'pending'.
        
        Demonstrates the edge case where an unhandled exception leaves an orphaned
        'pending' record that permanently silences subsequent alerts due to ON CONFLICT DO NOTHING.
        """
        db = temp_adv_db
        company_id = await db.add_company("CrashCo", "https://crash.com", "lever")
        job = JobListing(
            external_id="crash-job-01",
            company_name="CrashCo",
            provider="lever",
            title="Crash Specialist",
            url="https://crash.com/jobs/01",
        )
        job_id, _ = await db.upsert_job(company_id, job)
        match = FilterResult(matched=True)

        class FaultyNotifier(TelegramNotifier):
            async def send_message(self, text: str) -> bool:
                # Simulate unhandled exception or asyncio.CancelledError
                raise RuntimeError("Simulated unhandled runtime failure in send_message")

        faulty = FaultyNotifier(mock_mode=True)

        with pytest.raises(RuntimeError, match="Simulated unhandled runtime failure"):
            await faulty.dispatch_job_alert(db, job_id, job, match)

        # Audit finding: check whether 'pending' row was left behind
        alert = await db.get_alert(job_id, channel="telegram")
        assert alert is not None
        # In current telegram.py without try...finally around reserve & finalize,
        # the status remains 'pending'!
        assert alert["status"] == "pending", (
            "Documented architectural finding: unhandled exceptions leave orphaned 'pending' locks."
        )

        # Because status is 'pending', subsequent scan reservation will fail:
        reserved_again = await db.reserve_alert_slot(job_id, channel="telegram")
        assert reserved_again is False, (
            "Orphaned 'pending' lock permanently prevents future alerts for this job!"
        )
