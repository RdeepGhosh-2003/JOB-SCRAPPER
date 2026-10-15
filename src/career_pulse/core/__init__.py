"""
Core domain models and interfaces for CareerPulse.
"""

from .models import (
    JobListing,
    Job,
    JobFilterConfig,
    FilterResult,
    CompanyConfig,
    ATSDetectResponse,
    ATSDetectResult,
)

__all__ = [
    "JobListing",
    "Job",
    "JobFilterConfig",
    "FilterResult",
    "CompanyConfig",
    "ATSDetectResponse",
    "ATSDetectResult",
]
