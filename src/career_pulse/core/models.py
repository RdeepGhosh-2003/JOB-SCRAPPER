"""
Standardized Pydantic data models for CareerPulse.
"""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, model_validator


ProviderType = Literal["greenhouse", "lever", "ashby", "workday", "playwright", "custom"]
WorkplaceType = Literal["remote", "hybrid", "on_site", "unknown"]


class JobListing(BaseModel):
    """Normalized job listing emitted by all ATS adapters and scrapers."""
    external_id: str = Field(..., description="Provider-assigned job ID or unique requisition code")
    company_name: str = Field(..., description="Target company name")
    provider: ProviderType = Field(default="custom", description="ATS platform or scraper origin")
    title: str = Field(..., description="Official job title")
    location: str = Field(default="", description="Parsed location string")
    workplace_type: WorkplaceType = Field(default="unknown", description="Workplace setup type")
    is_remote: bool = Field(default=False, description="Whether position is tagged remote")
    url: str = Field(..., description="Direct application or job detail URL")
    department: Optional[str] = Field(default=None, description="Department or team name")
    description_text: str = Field(default="", description="Cleaned plaintext of job description")
    published_at: Optional[datetime] = Field(default=None, description="Date and time when job was posted/updated")
    raw_payload: Optional[Dict[str, Any]] = Field(default=None, description="Original raw response payload")

    @model_validator(mode="before")
    @classmethod
    def _normalize_input_aliases(cls, data: Any) -> Any:
        """Allow seamless instantiation with either Job or JobListing field names."""
        if not isinstance(data, dict):
            return data

        d = dict(data)

        # ID alias
        if "external_id" not in d and "id" in d:
            d["external_id"] = str(d["id"])
        elif "id" not in d and "external_id" in d:
            d["id"] = str(d["external_id"])

        if d.get("external_id") is None:
            d["external_id"] = str(d.get("id") or "unknown_id")

        # Company alias
        if "company_name" not in d and "company" in d:
            d["company_name"] = d["company"]

        if d.get("company_name") is None:
            d["company_name"] = d.get("company") or "Unknown Company"

        # Remote alias
        if "is_remote" not in d and "remote" in d:
            val = d["remote"]
            if isinstance(val, str):
                d["is_remote"] = val.strip().lower() in ("true", "1", "yes")
            else:
                d["is_remote"] = bool(val)
        elif "is_remote" in d and isinstance(d["is_remote"], str):
            d["is_remote"] = d["is_remote"].strip().lower() in ("true", "1", "yes")

        # Description alias
        if "description_text" not in d and "description" in d:
            d["description_text"] = d["description"] or ""

        # Posted/Published alias
        if "published_at" not in d and "posted_at" in d:
            d["published_at"] = d["posted_at"]

        # Handle None in string fields
        if d.get("location") is None:
            d["location"] = ""
        if d.get("description_text") is None:
            d["description_text"] = ""
        if d.get("title") is None:
            d["title"] = "Untitled"
        if d.get("url") is None:
            d["url"] = "#"

        # Normalize provider string if lowercase variant
        if "provider" in d and isinstance(d["provider"], str):
            d["provider"] = d["provider"].lower()

        return d

    # Convenient property aliases for compatibility
    @property
    def id(self) -> str:
        return self.external_id

    @property
    def company(self) -> str:
        return self.company_name

    @property
    def remote(self) -> bool:
        return self.is_remote

    @property
    def description(self) -> str:
        return self.description_text

    @property
    def posted_at(self) -> Optional[datetime]:
        return self.published_at

    def get_unique_key(self) -> str:
        """Generate deduplication unique key string."""
        return f"{self.provider}:{self.company_name.lower().replace(' ', '_')}:{self.external_id}"


# Alias Job directly to JobListing
Job = JobListing


class JobFilterConfig(BaseModel):
    """Configurable matching and filtering rules."""
    target_titles: List[str] = Field(
        default_factory=lambda: ["Data Analyst"],
        description="Target job title keywords or phrases"
    )
    negative_title_keywords: List[str] = Field(
        default_factory=lambda: [
            "senior", "sr", "sr.", "principal", "staff", "lead",
            "manager", "director", "head of", "vp", "vice president",
            "intern", "internship", "co-op"
        ],
        description="Strict negative keywords for title exclusion"
    )
    negative_description_keywords: List[str] = Field(
        default_factory=lambda: ["10+ years", "active security clearance", "phd required"],
        description="Strict negative phrases for description exclusion"
    )
    required_skills: List[str] = Field(
        default_factory=lambda: ["Python"],
        description="Skills that must match per skills_match_mode"
    )
    preferred_skills: List[str] = Field(
        default_factory=lambda: ["FastAPI", "PostgreSQL", "Docker", "AWS", "Redis", "TypeScript"],
        description="Preferred skills for match relevance scoring and alert tags"
    )
    skills_match_mode: Literal["any", "all", "none"] = Field(
        default="any",
        description="'any' = at least 1 required skill; 'all' = all required skills; 'none' = bypass skill check"
    )
    remote_only: bool = Field(default=False, description="Require job to be remote")
    allowed_locations: List[str] = Field(
        default_factory=lambda: ["Remote", "United States", "US", "Anywhere"],
        description="Allowed location patterns (empty list allows any location)"
    )
    excluded_locations: List[str] = Field(
        default_factory=list,
        description="Disallowed locations"
    )


class FilterResult(BaseModel):
    """Evaluation result for a job against active filter configuration."""
    matched: bool
    rejection_reason: Optional[str] = None
    matched_title: Optional[str] = None
    matched_skills: List[str] = Field(default_factory=list)
    is_remote_matched: bool = False
    match_score: float = 0.0


class CompanyConfig(BaseModel):
    """Configuration record for a monitored target company."""
    id: Optional[int] = None
    name: str
    url: str
    provider: ProviderType = "custom"
    identifier: str = Field(..., description="ATS board token / company slug / tenant")
    career_site: Optional[str] = Field(default=None, description="Workday specific career site name")
    enabled: bool = True
    last_scanned_at: Optional[datetime] = None
    total_jobs: int = 0


class ATSDetectResult(BaseModel):
    """Detection result for a career URL."""
    provider: ProviderType
    identifier: str
    career_site: Optional[str] = None
    confidence: Literal["high", "medium", "low", "fallback"] = "high"
    canonical_url: str
    extra: Optional[Dict[str, Any]] = None


# Alias for REST API response compatibility
ATSDetectResponse = ATSDetectResult
