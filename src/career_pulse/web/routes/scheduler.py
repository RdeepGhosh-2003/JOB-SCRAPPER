"""
Scheduler Management REST Endpoints.
"""

from typing import Any, Dict
from fastapi import APIRouter
from pydantic import BaseModel

from career_pulse.scheduler.resilient import ResilientScheduler, SchedulerConfig, SchedulerStatus

router = APIRouter(prefix="/api/scheduler", tags=["scheduler"])

# Shared global scheduler instance
_scheduler: ResilientScheduler = ResilientScheduler()


def get_global_scheduler() -> ResilientScheduler:
    return _scheduler


@router.get("/status")
async def get_scheduler_status() -> SchedulerStatus:
    """Get current background scheduler state."""
    return _scheduler.get_status()


@router.post("/toggle")
async def toggle_scheduler(enable: bool) -> SchedulerStatus:
    """Enable or disable background scheduled scanning."""
    _scheduler.config.enabled = enable
    if enable and not _scheduler._running:
        _scheduler.start()
    elif not enable and _scheduler._running:
        await _scheduler.stop()
    return _scheduler.get_status()


@router.post("/config")
async def update_scheduler_config(config: SchedulerConfig) -> Dict[str, Any]:
    """Update background schedule interval and time windows."""
    _scheduler.config = config
    return {"success": True, "message": "Scheduler configuration updated", "config": config}
