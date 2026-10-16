"""
Scan Activity Logs API Router.
"""

from typing import List, Dict, Any
from fastapi import APIRouter, Query

from career_pulse.config import settings
from career_pulse.db.session import Database

router = APIRouter(prefix="/api/logs", tags=["logs"])


@router.get("", response_model=List[Dict[str, Any]])
async def get_logs(limit: int = Query(100, ge=1, le=200)):
    """Retrieve recent scan activity logs."""
    db = Database(settings.db_path)
    safe_limit = min(max(1, limit), 200)
    return await db.get_scan_logs(limit=safe_limit)
