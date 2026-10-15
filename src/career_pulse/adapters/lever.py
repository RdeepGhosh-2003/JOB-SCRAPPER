"""
Lever Postings API Adapter.
Public endpoint: https://api.lever.co/v0/postings/{company}?mode=json
"""

import logging
from typing import Any, List, Optional
import httpx

from career_pulse.adapters.base import BaseATSAdapter
from career_pulse.core.models import JobListing, ProviderType

logger = logging.getLogger(__name__)


class LeverAdapter(BaseATSAdapter):
    """Adapter for Lever Postings public JSON API."""

    provider: ProviderType = "lever"
    BASE_URL = "https://api.lever.co/v0/postings"
    EU_BASE_URL = "https://api.eu.lever.co/v0/postings"

    async def fetch_jobs(
        self,
        company_identifier: str,
        company_name: Optional[str] = None,
        is_eu: bool = False,
        **kwargs: Any,
    ) -> List[JobListing]:
        """
        Fetch all open jobs for a Lever company identifier with automatic pagination.

        :param company_identifier: Lever company slug (e.g. 'netflix', 'spotify')
        :param company_name: Optional display name for the company
        :param is_eu: If True, uses the EU endpoint api.eu.lever.co
        :return: List of normalized JobListing objects
        """
        company_slug = company_identifier.strip().lower()
        display_name = company_name or company_slug.capitalize()
        base_endpoint = self.EU_BASE_URL if is_eu else self.BASE_URL
        url = f"{base_endpoint}/{company_slug}"

        client = await self._get_client()
        listings: List[JobListing] = []

        limit = 100
        skip = 0
        max_pages = 50  # Guard against runaway loops

        for page_idx in range(max_pages):
            params = {
                "mode": "json",
                "limit": limit,
                "skip": skip,
            }

            try:
                response = await client.get(url, params=params)
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    logger.warning("Lever company '%s' not found (HTTP 404)", company_slug)
                    return []
                if exc.response.status_code == 429:
                    logger.error("Lever rate limit hit for '%s' (HTTP 429)", company_slug)
                    raise
                logger.error("Lever HTTP error %s for '%s'", exc.response.status_code, company_slug)
                raise
            except httpx.RequestError as exc:
                logger.error("Lever network request failed for '%s': %s", company_slug, exc)
                raise

            items = response.json()
            if not isinstance(items, list) or len(items) == 0:
                break

            for item in items:
                if not isinstance(item, dict):
                    continue
                ext_id = str(item.get("id") or "").strip()
                if not ext_id:
                    continue

                # Title in Lever is the 'text' field
                title = (item.get("text") or "").strip() or "Untitled"

                categories = item.get("categories")
                if not isinstance(categories, dict):
                    categories = {}
                location_str = categories.get("location", "") or ""
                if not location_str and categories.get("allLocations"):
                    all_locs = categories.get("allLocations")
                    if isinstance(all_locs, list) and len(all_locs) > 0:
                        location_str = all_locs[0]

                workplace_type_attr = item.get("workplaceType")
                is_remote, workplace_type = self.detect_workplace_and_remote(
                    title=title,
                    location=location_str,
                    explicit_type=workplace_type_attr,
                )

                job_url = (
                    item.get("applyUrl")
                    or item.get("hostedUrl")
                    or f"https://jobs.lever.co/{company_slug}/{ext_id}"
                )

                department = categories.get("department") or categories.get("team")

                # Description synthesis (plain text preferred, fallback to HTML + lists)
                desc_parts = []
                if item.get("descriptionPlain"):
                    desc_parts.append(item.get("descriptionPlain"))
                elif item.get("description"):
                    desc_parts.append(self.strip_html(item.get("description")))

                lists = item.get("lists")
                if isinstance(lists, list):
                    for lst in lists:
                        if isinstance(lst, dict):
                            hdr = lst.get("text", "") or ""
                            content = self.strip_html(lst.get("content", ""))
                            if hdr or content:
                                desc_parts.append(f"{hdr}\n{content}".strip())

                description_text = "\n\n".join(p for p in desc_parts if p).strip()

                # Published at (createdAt is timestamp in milliseconds)
                published_at = self.parse_datetime_safe(item.get("createdAt"))

                listing = JobListing(
                    external_id=ext_id,
                    company_name=display_name,
                    provider="lever",
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

            if len(items) < limit:
                # Last page reached
                break

            skip += limit

        logger.info("Lever: Fetched %d jobs for %s", len(listings), display_name)
        return listings
