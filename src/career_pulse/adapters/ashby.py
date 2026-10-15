"""
Ashby Job Board API Adapter.
Public endpoint: https://api.ashbyhq.com/posting-api/job-board/{organization}?includeCompensation=true
"""

import logging
from typing import Any, List, Optional
import httpx

from career_pulse.adapters.base import BaseATSAdapter
from career_pulse.core.models import JobListing, ProviderType

logger = logging.getLogger(__name__)


class AshbyAdapter(BaseATSAdapter):
    """Adapter for Ashby public Job Board JSON API."""

    provider: ProviderType = "ashby"
    BASE_URL = "https://api.ashbyhq.com/posting-api/job-board"

    async def fetch_jobs(
        self,
        company_identifier: str,
        company_name: Optional[str] = None,
        **kwargs: Any,
    ) -> List[JobListing]:
        """
        Fetch all open jobs for an Ashby organization.

        :param company_identifier: Ashby organization slug (e.g. 'linear', 'ramp')
        :param company_name: Optional display name for the company
        :return: List of normalized JobListing objects
        """
        org_slug = company_identifier.strip()
        display_name = company_name or org_slug.capitalize()
        url = f"{self.BASE_URL}/{org_slug}"
        params = {"includeCompensation": "true"}

        client = await self._get_client()

        try:
            response = await client.get(url, params=params)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                logger.warning("Ashby organization '%s' not found (HTTP 404)", org_slug)
                return []
            if exc.response.status_code == 429:
                logger.error("Ashby rate limit hit for '%s' (HTTP 429)", org_slug)
                raise
            logger.error("Ashby HTTP error %s for '%s'", exc.response.status_code, org_slug)
            raise
        except httpx.RequestError as exc:
            logger.error("Ashby network request failed for '%s': %s", org_slug, exc)
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

            location_val = item.get("location")
            if isinstance(location_val, dict):
                location_str = str(location_val.get("name") or location_val.get("location") or "")
            elif location_val:
                location_str = str(location_val)
            else:
                location_str = ""

            if not location_str and item.get("secondaryLocations"):
                sec_locs = item["secondaryLocations"]
                if isinstance(sec_locs, list) and len(sec_locs) > 0:
                    first_loc = sec_locs[0]
                    if isinstance(first_loc, dict):
                        location_str = str(first_loc.get("name") or first_loc.get("location") or "")
                    elif first_loc:
                        location_str = str(first_loc)

            is_remote_flag = item.get("isRemote")
            is_remote, workplace_type = self.detect_workplace_and_remote(
                title=title,
                location=location_str,
                is_remote_flag=is_remote_flag,
            )

            job_url = (
                item.get("applyUrl")
                or item.get("jobUrl")
                or f"https://jobs.ashbyhq.com/{org_slug}/{ext_id}"
            )

            department = item.get("department") or item.get("team")
            if isinstance(department, dict):
                department = department.get("name")
            elif department is not None:
                department = str(department)

            desc_plain = item.get("descriptionPlain")
            if not desc_plain and item.get("descriptionHtml"):
                desc_plain = self.strip_html(item.get("descriptionHtml"))
            description_text = desc_plain or ""

            # If compensation is available, optionally mention it in description
            comp_info = item.get("compensation")
            if isinstance(comp_info, dict) and comp_info.get("compensationTierSummary") is not None:
                summary = str(comp_info["compensationTierSummary"])
                if summary not in description_text:
                    description_text = f"{description_text}\n\nCompensation: {summary}".strip()

            published_at = self.parse_datetime_safe(item.get("publishedAt"))

            listing = JobListing(
                external_id=ext_id,
                company_name=display_name,
                provider="ashby",
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

        logger.info("Ashby: Fetched %d jobs for %s", len(listings), display_name)
        return listings
