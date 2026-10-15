"""
Job Search Filter Configuration REST Endpoints.
"""

from typing import Any, Dict
from fastapi import APIRouter
from career_pulse.config import settings
from career_pulse.core.models import JobFilterConfig
from career_pulse.db.session import Database

router = APIRouter(prefix="/api/filters", tags=["filters"])
db = Database(settings.db_path)


@router.get("")
async def get_filters() -> JobFilterConfig:
    """Get active job filter configuration."""
    raw = await db.get_setting("filter_config")
    if raw and isinstance(raw, dict):
        try:
            return JobFilterConfig(**raw)
        except Exception:
            pass
    return JobFilterConfig()


@router.put("")
async def update_filters(config: JobFilterConfig) -> Dict[str, Any]:
    """Update job filter configuration."""
    await db.set_setting("filter_config", config.model_dump())
    return {"success": True, "message": "Filter configuration saved", "config": config}
