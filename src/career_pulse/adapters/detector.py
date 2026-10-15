"""
Two-Phase ATS Auto-Detector.
Phase 1: Instant zero-network URL regex matching for Greenhouse, Lever, Ashby, Workday.
Phase 2: Lightweight async HTTP probing & HTML fingerprinting (redirects, iframes, embed scripts).
"""

import logging
import re
from typing import Optional, Tuple
from urllib.parse import parse_qs, urlparse
from bs4 import BeautifulSoup
import httpx

from career_pulse.config import settings
from career_pulse.core.models import ATSDetectResult, ProviderType

logger = logging.getLogger(__name__)

# Phase 1 URL regex patterns
GREENHOUSE_URL_RE = re.compile(
    r"^https?://(?:boards|job-boards|boards\.eu)\.greenhouse\.io/(?:embed/job_board\?for=)?(?P<token>[a-zA-Z0-9_\-]+)",
    re.IGNORECASE,
)
LEVER_URL_RE = re.compile(
    r"^https?://jobs\.(?:eu\.)?lever\.co/(?P<company>[a-zA-Z0-9_\-]+)",
    re.IGNORECASE,
)
ASHBY_URL_RE = re.compile(
    r"^https?://jobs\.ashbyhq\.com/(?P<org>[a-zA-Z0-9_\-]+)",
    re.IGNORECASE,
)
WORKDAY_URL_RE = re.compile(
    r"^https?://(?P<tenant>[a-zA-Z0-9_\-]+)(?:\.(?P<pod>wd\d+))?\.myworkdayjobs\.com/(?:[a-z]{2}(?:-[A-Za-z]{2})?/)?(?P<site>[a-zA-Z0-9_\-]+)",
    re.IGNORECASE,
)


class ATSDetector:
    """Detects ATS type and identifiers from career page URLs."""

    def __init__(
        self,
        client: Optional[httpx.AsyncClient] = None,
        timeout: Optional[float] = None,
        user_agent: Optional[str] = None,
    ):
        self._external_client = client is not None
        self._client = client
        self.timeout = timeout or 10.0
        self.user_agent = user_agent or settings.user_agent

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            headers = {"User-Agent": self.user_agent}
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                headers=headers,
                follow_redirects=True,
            )
        return self._client

    async def close(self) -> None:
        if not self._external_client and self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    @classmethod
    def match_url(cls, url: str) -> Optional[ATSDetectResult]:
        """
        Phase 1: Deterministic regex URL matcher without network requests.
        Returns ATSDetectResult if matched, otherwise None.
        """
        clean_url = url.strip()
        parsed = urlparse(clean_url)
        netloc = parsed.netloc.lower()

        # Greenhouse match
        if "greenhouse.io" in netloc:
            # Check query param ?for=
            query_params = parse_qs(parsed.query)
            if "for" in query_params and query_params["for"]:
                token = query_params["for"][0]
                return ATSDetectResult(
                    provider="greenhouse",
                    identifier=token,
                    confidence="high",
                    canonical_url=clean_url,
                )
            match = GREENHOUSE_URL_RE.match(clean_url)
            if match:
                token = match.group("token")
                return ATSDetectResult(
                    provider="greenhouse",
                    identifier=token,
                    confidence="high",
                    canonical_url=clean_url,
                )
            # Fallback for boards.greenhouse.io/{token}/jobs/...
            path_parts = [p for p in parsed.path.split("/") if p and p != "embed"]
            if path_parts:
                return ATSDetectResult(
                    provider="greenhouse",
                    identifier=path_parts[0],
                    confidence="high",
                    canonical_url=clean_url,
                )

        # Lever match
        if "lever.co" in netloc:
            match = LEVER_URL_RE.match(clean_url)
            if match:
                company = match.group("company")
                return ATSDetectResult(
                    provider="lever",
                    identifier=company,
                    confidence="high",
                    canonical_url=clean_url,
                )
            path_parts = [p for p in parsed.path.split("/") if p]
            if path_parts:
                return ATSDetectResult(
                    provider="lever",
                    identifier=path_parts[0],
                    confidence="high",
                    canonical_url=clean_url,
                )

        # Ashby match
        if "ashbyhq.com" in netloc:
            match = ASHBY_URL_RE.match(clean_url)
            if match:
                org = match.group("org")
                return ATSDetectResult(
                    provider="ashby",
                    identifier=org,
                    confidence="high",
                    canonical_url=clean_url,
                )
            path_parts = [p for p in parsed.path.split("/") if p and p != "posting-api"]
            if path_parts:
                return ATSDetectResult(
                    provider="ashby",
                    identifier=path_parts[-1],
                    confidence="high",
                    canonical_url=clean_url,
                )

        # Workday match
        if "myworkdayjobs.com" in netloc:
            match = WORKDAY_URL_RE.match(clean_url)
            tenant = netloc.split(".")[0]
            career_site = "External"
            if match:
                tenant = match.group("tenant") or tenant
                career_site = match.group("site") or career_site
            else:
                path_parts = [p for p in parsed.path.split("/") if p and not re.match(r"^[a-z]{2}(?:-[A-Za-z]{2})?$", p, re.I)]
                if path_parts:
                    career_site = path_parts[0]

            return ATSDetectResult(
                provider="workday",
                identifier=tenant,
                career_site=career_site,
                confidence="high",
                canonical_url=clean_url,
                extra={"tenant": tenant, "career_site": career_site, "host": netloc},
            )

        return None

    async def detect(self, url: str, probe_network: bool = True) -> ATSDetectResult:
        """
        Detect ATS provider and tokens for a given URL using Phase 1 then Phase 2.

        :param url: User supplied URL (direct ATS or company careers portal)
        :param probe_network: Whether to execute Phase 2 HTTP probing if Phase 1 misses
        :return: ATSDetectResult with provider, identifier, and confidence
        """
        clean_url = url.strip()
        if not clean_url.startswith("http://") and not clean_url.startswith("https://"):
            clean_url = f"https://{clean_url}"

        # Phase 1: Zero-network URL pattern match
        instant_match = self.match_url(clean_url)
        if instant_match:
            return instant_match

        if not probe_network:
            return ATSDetectResult(
                provider="custom",
                identifier=clean_url,
                confidence="fallback",
                canonical_url=clean_url,
            )

        # Phase 2: HTTP probing and HTML fingerprinting
        client = await self._get_client()
        try:
            response = await client.get(clean_url)
            final_url = str(response.url)

            # Check if redirect lands on an ATS URL
            redirect_match = self.match_url(final_url)
            if redirect_match:
                redirect_match.canonical_url = final_url
                redirect_match.confidence = "high"
                return redirect_match

            # Fingerprint HTML content
            html_content = response.text
            soup = BeautifulSoup(html_content, "html.parser")

            detected = self._fingerprint_html(soup, final_url)
            if detected:
                return detected

        except Exception as exc:
            logger.warning("ATSDetector probing failed for %s: %s", clean_url, exc)

        # Final fallback to custom Playwright scraper
        return ATSDetectResult(
            provider="custom",
            identifier=clean_url,
            confidence="fallback",
            canonical_url=clean_url,
        )

    def _fingerprint_html(self, soup: BeautifulSoup, base_url: str) -> Optional[ATSDetectResult]:
        """Scan HTML DOM for embedded iframes, script tags, and outbound ATS links."""
        # 1. Check embedded iframes
        for iframe in soup.find_all("iframe", src=True):
            src = iframe["src"]
            match = self.match_url(src)
            if match:
                match.confidence = "medium"
                match.canonical_url = base_url
                return match

        # 2. Check embed script tags
        for script in soup.find_all("script", src=True):
            src = script["src"]
            if "greenhouse.io" in src:
                # Look for for= query param
                parsed = urlparse(src)
                qs = parse_qs(parsed.query)
                if "for" in qs and qs["for"]:
                    return ATSDetectResult(
                        provider="greenhouse",
                        identifier=qs["for"][0],
                        confidence="medium",
                        canonical_url=base_url,
                    )
            elif "assets.lever.co" in src:
                # Often accompanied by lever embed div
                return ATSDetectResult(
                    provider="lever",
                    identifier=urlparse(base_url).netloc.split(".")[0],
                    confidence="medium",
                    canonical_url=base_url,
                )
            elif "ashbyhq.com" in src:
                match = self.match_url(src)
                if match:
                    match.confidence = "medium"
                    match.canonical_url = base_url
                    return match

        # 3. Check inline markers
        lever_div = soup.select_one(".lever-jobs-embed, div[data-lever-site]")
        if lever_div:
            site = lever_div.get("data-lever-site") or urlparse(base_url).netloc.split(".")[0]
            return ATSDetectResult(
                provider="lever",
                identifier=str(site),
                confidence="medium",
                canonical_url=base_url,
            )

        greenhouse_div = soup.select_one("#grnhse_app, [data-grnhse-board]")
        if greenhouse_div:
            board = greenhouse_div.get("data-grnhse-board") or urlparse(base_url).netloc.split(".")[0]
            return ATSDetectResult(
                provider="greenhouse",
                identifier=str(board),
                confidence="medium",
                canonical_url=base_url,
            )

        # 4. Outbound career links tally
        counts = {"greenhouse": 0, "lever": 0, "ashby": 0, "workday": 0}
        detected_results = {}

        for a in soup.find_all("a", href=True):
            href = a["href"]
            match = self.match_url(href)
            if match:
                counts[match.provider] += 1
                detected_results[match.provider] = match

        for prov, count in counts.items():
            if count >= 2:
                res = detected_results[prov]
                res.confidence = "medium"
                res.canonical_url = base_url
                return res

        return None
