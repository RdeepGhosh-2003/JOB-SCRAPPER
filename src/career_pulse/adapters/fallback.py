"""
Fallback Web Scraper for custom corporate career portals.
Employs a cascading multi-tier strategy:
1. Fast HTTP + BeautifulSoup Schema.org JSON-LD (JobPosting) extraction.
2. Fast HTTP + Semantic DOM card extraction.
3. Headless Playwright browser automation with resource-blocking for SPA pages.
"""

from hashlib import sha256
import json
import logging
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
import httpx

from career_pulse.adapters.base import BaseATSAdapter
from career_pulse.core.models import JobListing, ProviderType

logger = logging.getLogger(__name__)


class FallbackScraper(BaseATSAdapter):
    """Headless scraper and HTML parser for non-standard corporate career portals."""

    provider: ProviderType = "custom"

    async def fetch_jobs(
        self,
        company_identifier: str,
        company_name: Optional[str] = None,
        use_browser: bool = False,
        **kwargs: Any,
    ) -> List[JobListing]:
        """
        Fetch jobs from a custom URL using cascading static and dynamic extraction.

        :param company_identifier: URL of the target careers page
        :param company_name: Optional display name for the company
        :param use_browser: If True, forces dynamic Playwright rendering immediately
        :return: List of normalized JobListing objects
        """
        url = company_identifier.strip()
        if not url.startswith("http://") and not url.startswith("https://"):
            url = f"https://{url}"

        domain = urlparse(url).netloc
        display_name = company_name or domain.replace("www.", "").split(".")[0].capitalize()

        listings: List[JobListing] = []

        # Tier 1 & 2: Static HTTP fetch with JSON-LD & DOM extraction
        if not use_browser:
            try:
                listings = await self._fetch_static(url, display_name)
                if listings:
                    logger.info("FallbackScraper (static): Extracted %d jobs from %s", len(listings), url)
                    return listings
            except Exception as exc:
                logger.debug("FallbackScraper static fetch failed for %s: %s; falling back to browser", url, exc)

        # Tier 3: Dynamic Playwright headless browser fallback
        try:
            listings = await self._fetch_playwright(url, display_name)
            logger.info("FallbackScraper (playwright): Extracted %d jobs from %s", len(listings), url)
        except Exception as exc:
            logger.warning("FallbackScraper browser execution failed for %s: %s", url, exc)

        return listings

    async def _fetch_static(self, url: str, display_name: str) -> List[JobListing]:
        """Attempt static HTML fetch and parsing."""
        client = await self._get_client()
        response = await client.get(url)
        response.raise_for_status()

        html_content = response.text
        soup = BeautifulSoup(html_content, "html.parser")

        # First try JSON-LD JobPosting
        json_ld_jobs = self._extract_json_ld(soup, url, display_name)
        if json_ld_jobs:
            return json_ld_jobs

        # Fallback to semantic DOM cards
        return self._extract_dom_cards(soup, url, display_name)

    async def _fetch_playwright(self, url: str, display_name: str) -> List[JobListing]:
        """Launch headless Playwright with aggressive resource blocking."""
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.warning("Playwright is not installed. Returning empty listings for dynamic crawl.")
            return []

        listings: List[JobListing] = []

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-gpu",
                        "--disable-background-networking",
                    ],
                )
                try:
                    context = await browser.new_context(
                        user_agent=self.user_agent,
                        viewport={"width": 1280, "height": 800},
                    )

                    # Intercept and abort heavy static assets to minimize RAM/CPU
                    async def route_filter(route):
                        if route.request.resource_type in ["image", "media", "font", "stylesheet"]:
                            await route.abort()
                        else:
                            await route.continue_()

                    await context.route("**/*", route_filter)

                    page = await context.new_page()
                    try:
                        await page.goto(url, wait_until="domcontentloaded", timeout=self.timeout * 1000)
                        # Brief hydration wait
                        await page.wait_for_timeout(1500)
                        rendered_html = await page.content()
                    finally:
                        await page.close()
                    await context.close()
                finally:
                    await browser.close()

            soup = BeautifulSoup(rendered_html, "html.parser")
            listings = self._extract_json_ld(soup, url, display_name)
            if not listings:
                listings = self._extract_dom_cards(soup, url, display_name)

        except Exception as exc:
            logger.warning("Playwright execution error on %s: %s", url, exc)

        return listings

    @staticmethod
    def _is_job_posting(item: Any) -> bool:
        """Verify whether an item is a Schema.org JobPosting dict."""
        if not isinstance(item, dict):
            return False
        t = item.get("@type")
        if isinstance(t, str):
            t_clean = t.strip()
            return t_clean == "JobPosting" or t_clean.endswith("/JobPosting")
        if isinstance(t, list):
            return any(
                isinstance(x, str) and (x.strip() == "JobPosting" or x.strip().endswith("/JobPosting"))
                for x in t
            )
        return False

    def _extract_json_ld(self, soup: BeautifulSoup, base_url: str, company_name: str) -> List[JobListing]:
        """Extract Schema.org JobPosting objects from script tags."""
        listings: List[JobListing] = []
        script_tags = soup.find_all("script", type="application/ld+json")

        for tag in script_tags:
            content = tag.string or tag.text
            if not content:
                continue

            try:
                data = json.loads(content.strip())
            except Exception:
                continue

            candidates: List[Any] = []
            if isinstance(data, list):
                candidates.extend(data)
            elif isinstance(data, dict):
                if "@graph" in data and isinstance(data["@graph"], list):
                    candidates.extend(data["@graph"])
                else:
                    candidates.append(data)

            items = [item for item in candidates if self._is_job_posting(item)]

            for item in items:
                if not isinstance(item, dict):
                    continue
                title_val = item.get("title")
                if not isinstance(title_val, str) or not title_val.strip():
                    continue
                title = title_val.strip()

                raw_url = item.get("url") or item.get("sameAs")
                direct_url = urljoin(base_url, str(raw_url)) if raw_url else base_url

                # Location
                location_str = ""
                job_loc = item.get("jobLocation")
                if isinstance(job_loc, dict):
                    addr = job_loc.get("address", {})
                    if isinstance(addr, dict):
                        parts = [
                            addr.get("addressLocality"),
                            addr.get("addressRegion"),
                            addr.get("addressCountry"),
                        ]
                        location_str = ", ".join(p for p in parts if p)
                    elif isinstance(addr, str):
                        location_str = addr
                elif isinstance(job_loc, list) and job_loc:
                    first = job_loc[0]
                    if isinstance(first, dict):
                        addr = first.get("address", {})
                        if isinstance(addr, dict):
                            location_str = addr.get("addressLocality", "")

                # Workplace type & remote
                applicant_location = str(item.get("applicantLocationRequirements", ""))
                is_remote_flag = (
                    item.get("jobLocationType") == "TELECOMMUTE"
                    or "telecommute" in applicant_location.lower()
                    or "remote" in location_str.lower()
                )
                is_remote, workplace_type = self.detect_workplace_and_remote(
                    title=title,
                    location=location_str,
                    is_remote_flag=is_remote_flag,
                )

                # Unique ID
                raw_id = item.get("identifier")
                if isinstance(raw_id, dict):
                    ext_id = str(raw_id.get("value") or raw_id.get("name") or "")
                elif raw_id:
                    ext_id = str(raw_id)
                else:
                    ext_id = sha256(direct_url.encode("utf-8")).hexdigest()[:16]

                desc_text = self.strip_html(item.get("description", ""))
                published_at = self.parse_datetime_safe(item.get("datePosted"))

                dept = item.get("occupationalCategory") or item.get("department")

                listing = JobListing(
                    external_id=ext_id,
                    company_name=company_name,
                    provider="custom",
                    title=title,
                    location=location_str,
                    workplace_type=workplace_type,
                    is_remote=is_remote,
                    url=direct_url,
                    department=str(dept) if dept else None,
                    description_text=desc_text,
                    published_at=published_at,
                    raw_payload=item,
                )
                listings.append(listing)

        return listings

    def _extract_dom_cards(self, soup: BeautifulSoup, base_url: str, company_name: str) -> List[JobListing]:
        """Extract job listings heuristically from semantic DOM cards and anchor tags."""
        listings: List[JobListing] = []
        seen_urls = set()

        # Target links that look like job postings
        job_link_selectors = [
            "a[href*='/job/']",
            "a[href*='/jobs/']",
            "a[href*='/career/']",
            "a[href*='/careers/']",
            "a[href*='/position/']",
            "a[href*='/openings/']",
            "a[href*='/opening/']",
        ]

        found_links = soup.select(", ".join(job_link_selectors))

        for link in found_links:
            href = link.get("href")
            if not href or href.startswith("#") or href.startswith("javascript:"):
                continue

            full_url = urljoin(base_url, href)
            if full_url in seen_urls:
                continue
            seen_urls.add(full_url)

            # Title extraction: look inside headings or link text
            title_text = ""
            heading = link.find(["h1", "h2", "h3", "h4", "h5", "strong"])
            if heading:
                title_text = heading.get_text(strip=True)
            if not title_text:
                title_text = link.get_text(strip=True)

            # Skip short links or navigation elements like 'Apply Now', 'View Jobs'
            if len(title_text) < 4 or title_text.lower() in [
                "apply", "apply now", "view job", "details", "learn more", "careers", "jobs"
            ]:
                continue

            # Look for location in parent card container
            location_str = ""
            parent_container = link.find_parent(["tr", "li", "div", "article", "section"])
            if parent_container:
                loc_elem = parent_container.select_one(
                    "[class*='location'], [class*='city'], [class*='place'], span[data-location]"
                )
                if loc_elem and loc_elem != link:
                    location_str = loc_elem.get_text(strip=True)

            is_remote, workplace_type = self.detect_workplace_and_remote(
                title=title_text,
                location=location_str,
            )

            ext_id = sha256(full_url.encode("utf-8")).hexdigest()[:16]

            listing = JobListing(
                external_id=ext_id,
                company_name=company_name,
                provider="custom",
                title=title_text,
                location=location_str,
                workplace_type=workplace_type,
                is_remote=is_remote,
                url=full_url,
                department=None,
                description_text="",
                published_at=None,
                raw_payload={"extracted_from": "dom_heuristic", "href": href},
            )
            listings.append(listing)

            if len(listings) >= 100:
                break

        return listings
