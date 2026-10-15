"""
Telegram Alert Notification Service for CareerPulse.

Handles HTML alert message formatting, character escaping, length constraints,
credential verification, and dispatch via Telegram Bot API or MockTelegramSink.
Implements Contract 4 from PROJECT.md and coordinates with Database for atomic deduplication.
"""

import asyncio
import contextlib
from datetime import datetime, timezone
import html
import logging
from typing import Any, Dict, List, Optional
import httpx

from career_pulse.config import settings
from career_pulse.core.models import FilterResult, JobListing

logger = logging.getLogger("career_pulse.services.telegram")


class MockTelegramSink:
    """
    In-memory sink recording sent Telegram alert messages for offline execution,
    unit testing, and automated system verification.
    """
    sent_messages: List[Dict[str, Any]] = []

    @classmethod
    def record(cls, message: Dict[str, Any]) -> None:
        """Appends a dispatched message dictionary to the in-memory sink."""
        entry = dict(message)
        if "timestamp" not in entry:
            entry["timestamp"] = datetime.now(timezone.utc).isoformat()
        if "parse_mode" not in entry:
            entry["parse_mode"] = "HTML"
        cls.sent_messages.append(entry)

    @classmethod
    def clear(cls) -> None:
        """Clears all recorded messages."""
        cls.sent_messages.clear()

    @classmethod
    def get_last_message(cls) -> Optional[Dict[str, Any]]:
        """Returns defensive copy of the most recently recorded message or None if empty."""
        return dict(cls.sent_messages[-1]) if cls.sent_messages else None

    @classmethod
    def get_messages(cls) -> List[Dict[str, Any]]:
        """Returns defensive copy of all recorded messages."""
        return [dict(m) for m in cls.sent_messages]

    @classmethod
    def get_history(cls) -> List[Dict[str, Any]]:
        """Alias for get_messages."""
        return cls.get_messages()

    @classmethod
    @contextlib.contextmanager
    def capture(cls):
        """Context manager isolating messages captured within the block."""
        cls.sent_messages.clear()
        try:
            yield cls
        finally:
            cls.sent_messages.clear()


class TelegramNotifier:
    """
    Telegram Bot Notification dispatcher supporting both live Telegram Bot API
    transmissions (via HTTPX) and offline in-memory MockTelegramSink recording.
    """

    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
        mock_mode: Optional[bool] = None,
        timeout: float = 10.0,
        timeout_seconds: Optional[float] = None,
        client: Optional[httpx.AsyncClient] = None,
    ):
        """
        Initializes the notifier.

        :param bot_token: Telegram bot token. Defaults to settings.telegram_bot_token.
        :param chat_id: Telegram chat ID. Defaults to settings.telegram_chat_id or '12345678'.
        :param mock_mode: If True, routes messages to MockTelegramSink. If None, auto-detected
                          based on settings.mock_telegram and availability of bot_token.
        :param timeout: HTTP request timeout in seconds.
        :param timeout_seconds: Backwards-compatible alias for timeout.
        :param client: Optional httpx.AsyncClient instance.
        """
        eff_timeout = timeout_seconds if timeout_seconds is not None else timeout
        self.timeout: float = float(eff_timeout)

        # Token resolution
        if bot_token is not None and bot_token.strip():
            self.bot_token: Optional[str] = bot_token.strip()
        else:
            self.bot_token = getattr(settings, "telegram_bot_token", None)

        # Mock mode auto-detection
        if mock_mode is None:
            self.mock_mode: bool = bool(getattr(settings, "mock_telegram", False) or not self.bot_token)
        else:
            self.mock_mode = bool(mock_mode)

        # Chat ID resolution
        resolved_chat_id = chat_id if chat_id is not None else getattr(settings, "telegram_chat_id", None)
        if resolved_chat_id is not None:
            resolved_chat_id = resolved_chat_id.strip() if resolved_chat_id.strip() else None

        if self.mock_mode:
            self.chat_id: Optional[str] = resolved_chat_id or "12345678"
        else:
            self.chat_id = resolved_chat_id

        self._client: Optional[httpx.AsyncClient] = client
        self._owns_client: bool = client is None
        self.last_error: Optional[str] = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def close(self) -> None:
        """Clean up HTTP client if owned."""
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    def format_job_message(self, job: JobListing, match: FilterResult) -> str:
        """
        Builds a clean, safe HTML alert message adhering to Telegram formatting specs.
        - Strict HTML escaping for company name, job title, location, ATS provider, and skill tags.
        - Escaped URL attribute in direct 1-click apply link:
          <a href="{escaped_url}"><b>👉 Apply Directly on Company Site</b></a>
        - Strictly enforces Telegram 4,096 character/byte limit with intelligent truncation.
        """
        raw_company = job.company_name or "Unknown Company"
        raw_title = job.title or "Untitled"
        raw_loc = job.location or "Unknown"
        raw_provider = job.provider or "Custom"
        raw_url = job.url or "#"

        # Bounding raw lengths on excessive fields to prevent header overflow
        if len(raw_company) > 200:
            raw_company = raw_company[:197] + "..."
        if len(raw_title) > 200:
            raw_title = raw_title[:197] + "..."
        if len(raw_loc) > 200:
            raw_loc = raw_loc[:197] + "..."
        if len(raw_url) > 2000:
            raw_url = raw_url[:2000]

        company = html.escape(raw_company, quote=True)
        title = html.escape(raw_title, quote=True)
        location = html.escape(raw_loc, quote=True)
        ats = html.escape(raw_provider.capitalize(), quote=True)
        remote_badge = "🌐 Remote" if job.is_remote else "🏢 On-Site / Hybrid"
        url = html.escape(raw_url, quote=True)

        def build_rendered(skills_part: str) -> str:
            return (
                f"🎯 <b>New Job Match: {company}</b>\n\n"
                f"💼 <b>Title:</b> {title}\n"
                f"📍 <b>Location:</b> {location} ({remote_badge})\n"
                f"{skills_part}"
                f"⚡ <b>ATS Platform:</b> {ats}\n\n"
                f"🔗 <a href=\"{url}\"><b>👉 Apply Directly on Company Site</b></a>"
            )

        skills_str = ""
        if match.matched_skills:
            tags = [f"<code>{html.escape(s, quote=True)}</code>" for s in match.matched_skills]
            full_skills = f"🏷️ <b>Matched Tech:</b> {', '.join(tags)}\n"
            full_msg = build_rendered(full_skills)

            if len(full_msg.encode("utf-8")) > 4000:
                included_tags: List[str] = []
                for tag in tags:
                    test_tags = included_tags + [tag]
                    remaining = len(tags) - len(test_tags)
                    suffix = f", <i>(+{remaining} more)</i>" if remaining > 0 else ""
                    test_skills = f"🏷️ <b>Matched Tech:</b> {', '.join(test_tags)}{suffix}\n"
                    test_msg = build_rendered(test_skills)
                    if len(test_msg.encode("utf-8")) > 4000:
                        break
                    included_tags.append(tag)

                if included_tags:
                    remaining_count = len(tags) - len(included_tags)
                    suffix = f", <i>(+{remaining_count} more)</i>" if remaining_count > 0 else ""
                    skills_str = f"🏷️ <b>Matched Tech:</b> {', '.join(included_tags)}{suffix}\n"
                else:
                    skills_str = f"🏷️ <b>Matched Tech:</b> <i>(+{len(tags)} more)</i>\n"
            else:
                skills_str = full_skills

        message = build_rendered(skills_str)
        return message

    async def send_message(self, text: str) -> bool:
        """
        Transmits HTML-formatted message to Telegram API or MockTelegramSink.
        Handles mock mode, HTTP 200 success, HTTP 429 rate limit retries,
        and logs failures on 4xx/5xx responses or network exceptions.
        """
        if self.mock_mode:
            logger.info(f"[MOCK TELEGRAM] Sending to chat {self.chat_id}:\n{text}")
            MockTelegramSink.record({
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": "HTML",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            self.last_error = None
            return True

        if not self.bot_token or not self.chat_id:
            self.last_error = "Cannot send Telegram message: bot_token or chat_id is missing."
            logger.warning(self.last_error)
            return False

        endpoint = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        }

        try:
            if self._client is not None:
                return await self._dispatch_post(self._client, endpoint, payload)
            else:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    return await self._dispatch_post(client, endpoint, payload)
        except Exception as e:
            self.last_error = f"Telegram network exception: {e}"
            logger.error(self.last_error)
            return False

    async def _dispatch_post(self, client: httpx.AsyncClient, endpoint: str, payload: dict) -> bool:
        """Helper to post payload with 429 retry logic."""
        response = await client.post(endpoint, json=payload)
        if response.status_code == 200:
            self.last_error = None
            return True
        elif response.status_code == 429:
            retry_after = 1.0
            try:
                retry_after = float(response.json().get("parameters", {}).get("retry_after", 1.0))
            except Exception:
                pass
            logger.warning(f"Telegram 429 rate limit encountered. Waiting {retry_after}s...")
            await asyncio.sleep(retry_after)
            retry_response = await client.post(endpoint, json=payload)
            if retry_response.status_code == 200:
                self.last_error = None
                return True
            self.last_error = f"Telegram retry failed (429): {retry_response.text}"
            logger.error(self.last_error)
            return False
        else:
            self.last_error = f"Telegram API failed ({response.status_code}): {response.text}"
            logger.error(self.last_error)
            return False

    async def send_job_alert(self, job: JobListing, match: FilterResult) -> bool:
        """
        Convenience method to format and send a job alert in one call.
        """
        text = self.format_job_message(job, match)
        return await self.send_message(text)

    async def send_alert(self, job: JobListing, match: FilterResult) -> bool:
        """Alias for send_job_alert."""
        return await self.send_job_alert(job, match)

    async def dispatch_job_alert(
        self,
        db: Any,
        job_id: int,
        job: JobListing,
        match: FilterResult,
    ) -> bool:
        """
        Coordinates atomic alert slot reservation, HTML formatting,
        Telegram delivery, and database status finalization.
        Ensures zero duplicate notifications.
        """
        if db is not None:
            reserved = await db.reserve_alert_slot(job_id, channel="telegram")
            if not reserved:
                logger.info(f"Alert slot for job_id {job_id} already reserved/sent; skipping duplicate.")
                return False

        preview = f"[{job.company_name or 'Unknown'}] {job.title or 'Untitled'}"
        text = self.format_job_message(job, match)
        sent = await self.send_message(text)

        if db is not None:
            if sent:
                status = "mock" if self.mock_mode else "sent"
                await db.finalize_alert_status(
                    job_id=job_id,
                    channel="telegram",
                    status=status,
                    preview=preview,
                )
            else:
                error = self.last_error or "Failed to deliver Telegram message"
                await db.finalize_alert_status(
                    job_id=job_id,
                    channel="telegram",
                    status="failed",
                    preview=preview,
                    error=error,
                )

        return sent

    async def verify_credentials(self) -> Dict[str, Any]:
        """
        Verify Telegram bot credentials.

        In mock mode: returns mock success payload.
        In live mode: issues GET request to /getMe on Telegram Bot API,
        and optionally sends a confirmation welcome message if chat_id is configured.
        """
        if self.mock_mode:
            return {
                "valid": True,
                "mock": True,
                "bot_name": "MockCareerPulseBot",
                "bot_username": "MockCareerPulseBot",
                "message": "Mock credentials verified successfully.",
            }

        if not self.bot_token:
            return {
                "valid": False,
                "mock": False,
                "error": "Telegram bot_token is empty or not configured.",
            }

        endpoint = f"https://api.telegram.org/bot{self.bot_token}/getMe"
        try:
            if self._client is not None:
                res = await self._client.get(endpoint)
            else:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    res = await client.get(endpoint)

            if res.status_code != 200:
                return {
                    "valid": False,
                    "mock": False,
                    "error": f"Invalid bot token ({res.status_code}): {res.text}",
                }

            data = res.json()
            bot_info = data.get("result", {})
            bot_username = bot_info.get("username") or bot_info.get("first_name", "Bot")
            bot_id = bot_info.get("id")

            if self.chat_id:
                test_text = (
                    f"🔔 <b>CareerPulse Bot Connected!</b>\n"
                    f"Successfully authenticated with bot @{bot_username}.\n"
                    f"Job alerts will be delivered here."
                )
                sent = await self.send_message(test_text)
                if not sent:
                    return {
                        "valid": False,
                        "mock": False,
                        "bot_username": bot_username,
                        "bot_name": bot_username,
                        "error": "Bot token is valid, but failed to deliver test message to chat_id.",
                    }

            return {
                "valid": True,
                "mock": False,
                "bot_username": bot_username,
                "bot_name": bot_username,
                "bot_id": bot_id,
                "message": f"Bot token and chat ID verified successfully as @{bot_username}.",
            }
        except Exception as e:
            return {
                "valid": False,
                "mock": False,
                "error": f"Network error contacting Telegram: {e}",
            }

    async def send_test_message(self) -> Dict[str, Any]:
        """Dispatch a test message to verify Telegram credentials."""
        test_text = (
            "<b>CareerPulse Alert Test</b>\n"
            "Your Telegram alerting connection is working properly!\n"
            f"Timestamp: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
        )
        if self.mock_mode or not self.bot_token:
            MockTelegramSink.record({
                "chat_id": self.chat_id or "mock_chat",
                "text": test_text,
                "parse_mode": "HTML",
            })
            return {"success": True, "mock": True, "text": test_text}

        ok = await self.send_message(test_text)
        return {"success": ok, "mock": False, "text": test_text}


async def dispatch_job_alert(
    db: Any,
    job_id: int,
    job: JobListing,
    match: FilterResult,
    notifier: Optional[TelegramNotifier] = None,
) -> bool:
    """
    Module-level helper coordinating atomic alert slot reservation,
    HTML message generation, Telegram transmission, and database finalization.
    Guarantees zero duplicate notifications.
    """
    if notifier is None:
        notifier = TelegramNotifier()
    return await notifier.dispatch_job_alert(db, job_id, job, match)


def get_telegram_notifier(
    bot_token: Optional[str] = None,
    chat_id: Optional[str] = None,
    mock_mode: Optional[bool] = None,
) -> TelegramNotifier:
    """Factory helper returning a configured TelegramNotifier instance."""
    return TelegramNotifier(
        bot_token=bot_token or settings.telegram_bot_token,
        chat_id=chat_id or settings.telegram_chat_id,
        mock_mode=mock_mode if mock_mode is not None else settings.telegram_mock_mode,
    )

