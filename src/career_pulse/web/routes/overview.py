"""
Overview Dashboard Statistics API Router.
"""

from typing import Any, Dict
from fastapi import APIRouter
from career_pulse.config import settings
from career_pulse.db.session import Database

router = APIRouter(prefix="/api/overview", tags=["overview"])
db = Database(settings.db_path)


@router.get("/stats")
async def get_overview_stats() -> Dict[str, Any]:
    """Retrieve aggregated overview metrics: matched_today, jobs_rejected, last_scan, match_rate."""
    return await db.get_overview_stats()
