"""
Greenhouse Job Board API Adapter.
Public endpoint: https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true
"""

import logging
from typing import Any, List, Optional
import httpx

from career_pulse.adapters.base import BaseATSAdapter
from career_pulse.core.models import JobListing, ProviderType

logger = logging.getLogger(__name__)


class GreenhouseAdapter(BaseATSAdapter):
    """Adapter for Greenhouse Job Board public JSON API."""

    provider: ProviderType = "greenhouse"
    BASE_URL = "https://boards-api.greenhouse.io/v1/boards"

    async def fetch_jobs(
        self,
        company_identifier: str,
        company_name: Optional[str] = None,
        **kwargs: Any,
    ) -> List[JobListing]:
        """
        Fetch all open jobs for a Greenhouse board token.

        :param company_identifier: Greenhouse board slug/token (e.g. 'stripe', 'cloudflare')
        :param company_name: Optional display name for the company
        :return: List of normalized JobListing objects
        """
        board_token = company_identifier.strip().lower()
        display_name = company_name or board_token.capitalize()
        url = f"{self.BASE_URL}/{board_token}/jobs"
        params = {"content": "true"}

        client = await self._get_client()

        try:
            response = await client.get(url, params=params)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                logger.warning("Greenhouse board '%s' not found (HTTP 404)", board_token)
                return []
            if exc.response.status_code == 429:
                logger.error("Greenhouse rate limit hit for '%s' (HTTP 429)", board_token)
                raise
            logger.error("Greenhouse HTTP error %s for '%s'", exc.response.status_code, board_token)
            raise
        except httpx.RequestError as exc:
            logger.error("Greenhouse network request failed for '%s': %s", board_token, exc)
            raise

        data = response.json()
        if not isinstance(data, dict):
            return []
        raw_jobs = data.get("jobs", [])
        if not isinstance(raw_jobs, list):
            return []
        listings: List[JobListing] = []

        for item in raw_jobs:
            if not isinstance(item, dict):
                continue
            ext_id = str(item.get("id") or "").strip()
            if not ext_id:
                continue

            title = (item.get("title") or "").strip() or "Untitled"

            # Location extraction
            loc_obj = item.get("location")
            if isinstance(loc_obj, dict):
                location_str = loc_obj.get("name", "") or ""
            elif isinstance(loc_obj, str):
                location_str = loc_obj
            else:
                location_str = ""

            if not location_str and item.get("offices"):
                offices = item["offices"]
                if isinstance(offices, list) and len(offices) > 0:
                    location_str = offices[0].get("name", "") or offices[0].get("location", "")

            # Workplace type & remote detection
            is_remote, workplace_type = self.detect_workplace_and_remote(
                title=title,
                location=location_str,
            )

            # Job URL
            job_url = item.get("absolute_url") or f"https://boards.greenhouse.io/{board_token}/jobs/{ext_id}"

            # Department
            department = None
            departments = item.get("departments")
            if isinstance(departments, list) and len(departments) > 0:
                department = departments[0].get("name")

            # Description
            description_html = item.get("content", "")
            description_text = self.strip_html(description_html)

            # Published at
            published_at = self.parse_datetime_safe(item.get("updated_at"))

            listing = JobListing(
                external_id=ext_id,
                company_name=display_name,
                provider="greenhouse",
                title=title,
                location=location_str,
                workplace_type=workplace_type,
                is_remote=is_remote,
                url=job_url,
                department=department,
                description_text=description_text,
                published_at=published_at,
                raw_payload=item,
            )
            listings.append(listing)

        logger.info("Greenhouse: Fetched %d jobs for %s", len(listings), display_name)
        return listings
