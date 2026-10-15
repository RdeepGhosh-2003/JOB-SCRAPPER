"""
Base ATS Adapter interface and common utility functions.
"""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
import html
import re
from typing import Any, List, Optional, Tuple
import httpx

from career_pulse.config import settings
from career_pulse.core.models import JobListing, ProviderType, WorkplaceType


_HTML_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_STYLE_RE = re.compile(r"<(script|style)[\s\S]*?</\1>", flags=re.I)
_WHITESPACE_RE = re.compile(r"\s+")
_REMOTE_KEYWORDS = ("remote", "telecommute", "work from anywhere", "wfa", "anywhere")
_HYBRID_KEYWORDS = ("hybrid", "flexible")


class BaseATSAdapter(ABC):
    """Abstract base class for all ATS adapters and web scrapers."""

    provider: ProviderType = "custom"

    def __init__(
        self,
        client: Optional[httpx.AsyncClient] = None,
        timeout: Optional[float] = None,
        user_agent: Optional[str] = None,
    ):
        self._external_client = client is not None
        self._client = client
        self.timeout = timeout or settings.request_timeout
        self.user_agent = user_agent or settings.user_agent

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or initialize the underlying httpx.AsyncClient."""
        if self._client is None or self._client.is_closed:
            headers = {"User-Agent": self.user_agent}
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                headers=headers,
                follow_redirects=True,
            )
        return self._client

    async def close(self) -> None:
        """Close HTTP client if owned by this adapter instance."""
        if not self._external_client and self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    @abstractmethod
    async def fetch_jobs(
        self,
        company_identifier: str,
        company_name: Optional[str] = None,
        **kwargs: Any,
    ) -> List[JobListing]:
        """
        Fetch open job postings from the ATS.

        :param company_identifier: ATS board token / organization slug / tenant ID
        :param company_name: Display company name (defaults to company_identifier if not provided)
        :param kwargs: Adapter-specific parameters (e.g. career_site for Workday)
        :return: List of normalized JobListing instances
        """
        pass

    @staticmethod
    def strip_html(text: Optional[str]) -> str:
        """Strip HTML tags and unescape HTML entities to clean plaintext."""
        if not text:
            return ""
        # 1. Strip script and style blocks first
        no_script = _SCRIPT_STYLE_RE.sub(" ", text)
        # 2. Strip all HTML tags
        plain = _HTML_TAG_RE.sub(" ", no_script)
        # 3. Decode remaining entities
        unescaped = html.unescape(plain)
        # 4. Normalize whitespace
        cleaned = _WHITESPACE_RE.sub(" ", unescaped).strip()
        return cleaned

    @staticmethod
    def detect_workplace_and_remote(
        title: str,
        location: str,
        explicit_type: Optional[str] = None,
        is_remote_flag: Optional[bool] = None,
    ) -> Tuple[bool, WorkplaceType]:
        """
        Determine is_remote boolean and workplace_type enum from attributes.
        """
        if is_remote_flag is True:
            return True, "remote"

        t_lower = title.lower()
        loc_lower = location.lower()
        exp_lower = (explicit_type or "").lower()

        # Check explicit workplace type
        if "remote" in exp_lower:
            return True, "remote"
        if "hybrid" in exp_lower:
            return False, "hybrid"
        if "on_site" in exp_lower or "onsite" in exp_lower or "in-office" in exp_lower:
            return False, "on_site"

        # Check location and title keywords
        for kw in _REMOTE_KEYWORDS:
            if kw in loc_lower or kw in t_lower:
                return True, "remote"

        for kw in _HYBRID_KEYWORDS:
            if kw in loc_lower or kw in t_lower:
                return False, "hybrid"

        if location.strip():
            return False, "on_site"

        return False, "unknown"

    @staticmethod
    def parse_datetime_safe(val: Any) -> Optional[datetime]:
        """Safely parse various datetime representations."""
        if val is None or isinstance(val, bool):
            return None
        if not val:
            return None
        if isinstance(val, datetime):
            return val
        if isinstance(val, (int, float)):
            # Epoch milliseconds or seconds
            try:
                if val > 1e11:  # likely milliseconds
                    return datetime.fromtimestamp(val / 1000.0, tz=timezone.utc)
                return datetime.fromtimestamp(val, tz=timezone.utc)
            except Exception:
                return None
        if isinstance(val, str):
            val_clean = val.strip()
            # ISO 8601 parsing
            try:
                # Replace trailing Z with +00:00 for fromisoformat compatibility
                if val_clean.endswith("Z"):
                    val_clean = val_clean[:-1] + "+00:00"
                return datetime.fromisoformat(val_clean)
            except Exception:
                pass
        return None
