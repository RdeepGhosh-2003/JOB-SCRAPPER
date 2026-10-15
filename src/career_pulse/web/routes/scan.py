"""
Scan Trigger & Reporting REST Endpoints.
"""

from typing import Any, Dict, Optional
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from career_pulse.core.pipeline import ScanPipeline, ScanReport
from career_pulse.db.session import Database
from career_pulse.config import settings

router = APIRouter(prefix="/api/scan", tags=["scan"])
pipeline = ScanPipeline()

_last_report: Optional[ScanReport] = None
_is_scanning: bool = False


class ScanTriggerRequest(BaseModel):
    company_id: Optional[int] = None


@router.post("/trigger")
async def trigger_scan(req: Optional[ScanTriggerRequest] = None) -> ScanReport:
    """Execute on-demand scan across all or single company."""
    global _last_report, _is_scanning
    if _is_scanning:
        raise HTTPException(status_code=409, detail="A scan is already in progress.")

    _is_scanning = True
    try:
        cid = req.company_id if req else None
        report = await pipeline.run_scan(company_id=cid)
        _last_report = report
        return report
    finally:
        _is_scanning = False


@router.get("/status")
async def get_scan_status() -> Dict[str, Any]:
    """Retrieve current scan progress or most recent report."""
    return {
        "is_scanning": _is_scanning,
        "last_report": _last_report,
    }
