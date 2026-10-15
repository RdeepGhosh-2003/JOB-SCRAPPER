"""
Workday CXS (Candidate Experience Services) API Adapter.
Public endpoint: POST https://{tenant}.{pod}.myworkdayjobs.com/wday/cxs/{tenant}/{careerSite}/jobs
"""

import logging
import re
from typing import Any, List, Optional, Tuple
from urllib.parse import urlparse
import httpx

from career_pulse.adapters.base import BaseATSAdapter
from career_pulse.core.models import JobListing, ProviderType

logger = logging.getLogger(__name__)

_REQ_ID_RE = re.compile(r"([A-Z0-9_\-]+)$")


class WorkdayAdapter(BaseATSAdapter):
    """Adapter for Workday CXS JSON API."""

    provider: ProviderType = "workday"

    @classmethod
    def parse_workday_url(cls, url_or_identifier: str) -> Tuple[str, str, str]:
        """
        Extract tenant, career_site, and host from a Workday URL or formatted string.
        Returns (tenant, career_site, host).
        """
        val = url_or_identifier.strip()
        if val.startswith("http://") or val.startswith("https://"):
            parsed = urlparse(val)
            host = parsed.netloc
            # Host typically format: {tenant}.wd{pod}.myworkdayjobs.com or {tenant}.myworkdayjobs.com
            tenant = host.split(".")[0]
            # Path typically: /en-US/{careerSite}/... or /{careerSite}
            path_parts = [p for p in parsed.path.split("/") if p and not re.match(r"^[a-z]{2}(?:-[A-Za-z]{2})?$", p, re.I)]
            career_site = path_parts[0] if path_parts else "External"
            return tenant, career_site, host

        # Handle colon-separated notation tenant:career_site:host
        parts = val.split(":")
        tenant = parts[0]
        career_site = parts[1] if len(parts) > 1 and parts[1] else "External"
        host = parts[2] if len(parts) > 2 and parts[2] else f"{tenant}.myworkdayjobs.com"
        return tenant, career_site, host

    async def fetch_jobs(
        self,
        company_identifier: str,
        company_name: Optional[str] = None,
        career_site: Optional[str] = None,
        host: Optional[str] = None,
        max_jobs: int = 500,
        **kwargs: Any,
    ) -> List[JobListing]:
        """
        Fetch jobs from Workday CXS endpoint with pagination.

        :param company_identifier: Workday URL, tenant name, or tenant:career_site:host notation
        :param company_name: Optional display name for the company
        :param career_site: Override career site name (e.g. 'NVIDIAExternalCareerSite')
        :param host: Override host domain (e.g. 'nvidia.wd5.myworkdayjobs.com')
        :param max_jobs: Safety ceiling on total jobs to fetch in one scan
        :return: List of normalized JobListing objects
        """
        extracted_tenant, extracted_site, extracted_host = self.parse_workday_url(company_identifier)
        tenant = extracted_tenant
        site = career_site or extracted_site or "External"
        domain = host or extracted_host or f"{tenant}.myworkdayjobs.com"
        display_name = company_name or tenant.capitalize()

        endpoint_url = f"https://{domain}/wday/cxs/{tenant}/{site}/jobs"

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": self.user_agent,
            "Origin": f"https://{domain}",
            "Referer": f"https://{domain}/en-US/{site}/jobs",
        }

        client = await self._get_client()
        listings: List[JobListing] = []

        limit = 20  # Workday CXS enforces limit=20
        offset = 0
        max_pages = (max_jobs // limit) + 1

        for _ in range(max_pages):
            payload = {
                "appliedFacets": {},
                "limit": limit,
                "offset": offset,
                "searchText": "",
            }

            try:
                response = await client.post(endpoint_url, json=payload, headers=headers)
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    logger.warning("Workday CXS endpoint not found: %s (HTTP 404)", endpoint_url)
                    return []
                if exc.response.status_code == 429:
                    logger.error("Workday rate limit hit for '%s' (HTTP 429)", tenant)
                    raise
                logger.error("Workday HTTP error %s for '%s'", exc.response.status_code, tenant)
                raise
            except httpx.RequestError as exc:
                logger.error("Workday network request failed for '%s': %s", tenant, exc)
                raise

            data = response.json()
            if not isinstance(data, dict):
                break
            postings = data.get("jobPostings", [])
            total = data.get("total", len(postings))

            if not isinstance(postings, list) or len(postings) == 0:
                break

            for item in postings:
                if not isinstance(item, dict):
                    continue
                ext_path = item.get("externalPath", "") or ""

                # Determine external ID
                bullet_fields = item.get("bulletFields", [])
                ext_id = ""
                if isinstance(bullet_fields, list) and bullet_fields:
                    ext_id = str(bullet_fields[0]).strip()

                if not ext_id and ext_path:
                    # Extract requisition ID from externalPath e.g. /job/.../Title_JR12345
                    match = _REQ_ID_RE.search(ext_path.rstrip("/"))
                    if match:
                        ext_id = match.group(1).lstrip("_-")
                    else:
                        ext_id = ext_path.strip("/")

                if not ext_id:
                    ext_id = f"wday_{abs(hash(str(item.get('title') or '') + ext_path))}"

                title = (item.get("title") or "").strip() or "Untitled"
                location_str = item.get("locationsText", "") or ""

                is_remote, workplace_type = self.detect_workplace_and_remote(
                    title=title,
                    location=location_str,
                )

                # Format absolute URL
                clean_path = ext_path.lstrip("/")
                job_url = f"https://{domain}/en-US/{site}/{clean_path}"

                # Posted on
                published_at = self.parse_datetime_safe(item.get("startDate"))

                listing = JobListing(
                    external_id=ext_id,
                    company_name=display_name,
                    provider="workday",
                    title=title,
                    location=location_str,
                    workplace_type=workplace_type,
                    is_remote=is_remote,
                    url=job_url,
                    department=None,
                    description_text=f"Posted: {item.get('postedOn', '')}".strip(),
                    published_at=published_at,
                    raw_payload=item,
                )
                listings.append(listing)

                if len(listings) >= max_jobs:
                    break

            offset += limit
            if offset >= total or len(listings) >= max_jobs:
                break

        logger.info("Workday: Fetched %d jobs for %s", len(listings), display_name)
        return listings
