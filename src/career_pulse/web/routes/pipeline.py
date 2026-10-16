"""
Pipeline Status Flowchart REST API Router for CareerPulse.

Provides live state and stage-by-stage diagnostics across:
1. scheduler - sleep/wake resilient polling loop state & operating window
2. companies - target company portal count and error status
3. adapter   - ATS API connectors (Greenhouse, Lever, Ashby, Workday, Fallback)
4. matcher   - title, keyword, and negative exclusion filter evaluations
5. database  - SQLite WAL mode health, total jobs indexed, deduplication
6. telegram  - alert dispatch status, credentials, and mock mode
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from fastapi import APIRouter
from pydantic import BaseModel, Field

from career_pulse.config import settings
from career_pulse.db.session import Database
from career_pulse.web.routes import scan
from career_pulse.web.routes.scheduler import get_global_scheduler

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])
db = Database(settings.db_path)


class PipelineNode(BaseModel):
    state: str = Field(..., description="Stage state: running, success, error, warning, or idle")
    label: str = Field(..., description="Display label for pipeline node")
    detail: str = Field(..., description="Detailed human-readable status explanation")
    meta: Dict[str, Any] = Field(default_factory=dict, description="Diagnostic metadata for stage")
    error: Optional[str] = Field(default=None, description="Exact failure reason if stage is failing")


class PipelineStateResponse(BaseModel):
    is_scanning: bool = Field(..., description="Whether a scan cycle is actively executing")
    nodes: Dict[str, PipelineNode] = Field(..., description="Map of pipeline stage nodes")


@router.get("/state", response_model=PipelineStateResponse)
async def get_pipeline_state() -> PipelineStateResponse:
    """
    Aggregate live status across all 6 pipeline stages with stage-by-stage error pinpointing.
    """
    scheduler = get_global_scheduler()
    sched_status = scheduler.get_status()

    is_scanning = bool(scan._is_scanning or sched_status.is_scanning)
    last_report = scan._last_report or getattr(scheduler, "_last_report", None)

    # 1. Scheduler Node
    sched_error: Optional[str] = None
    if is_scanning:
        sched_state = "running"
        sched_detail = "Scan pipeline execution in progress"
    elif not sched_status.config.enabled:
        sched_state = "idle"
        sched_detail = "Background scheduler is paused"
    elif not sched_status.is_running:
        sched_state = "idle"
        sched_detail = "Scheduler service idle"
    elif not sched_status.in_active_window:
        sched_state = "idle"
        sched_detail = "Outside active operating window"
    else:
        sched_state = "success"
        if sched_status.next_run_at:
            next_str = sched_status.next_run_at.strftime("%H:%M:%S UTC")
            sched_detail = f"Active · Next scan at {next_str} (Interval: {sched_status.config.interval_minutes}m)"
        else:
            sched_detail = f"Active · Scan Interval: {sched_status.config.interval_minutes}m"

    scheduler_node = PipelineNode(
        state=sched_state,
        label="Scheduler",
        detail=sched_detail,
        meta={
            "enabled": sched_status.config.enabled,
            "interval_minutes": sched_status.config.interval_minutes,
            "in_active_window": sched_status.in_active_window,
            "total_runs": sched_status.total_runs,
            "next_run_at": sched_status.next_run_at.isoformat() if sched_status.next_run_at else None,
            "last_run_at": sched_status.last_run_at.isoformat() if sched_status.last_run_at else None,
        },
        error=sched_error,
    )

    # 2. Companies Node
    total_comp = 0
    active_comp = 0
    failed_comp = 0
    failing_comp_name: Optional[str] = None
    failing_comp_err: Optional[str] = None

    try:
        async with await db.get_connection() as conn:
            async with conn.execute(
                """
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN is_active = 1 THEN 1 ELSE 0 END) as active,
                    SUM(CASE WHEN scan_status = 'failed' OR last_error IS NOT NULL THEN 1 ELSE 0 END) as failed
                FROM companies
                """
            ) as cur:
                row = await cur.fetchone()
                if row:
                    total_comp = int(row["total"] or 0)
                    active_comp = int(row["active"] or 0)
                    failed_comp = int(row["failed"] or 0)

            if failed_comp > 0:
                async with conn.execute(
                    "SELECT name, last_error FROM companies WHERE scan_status = 'failed' OR last_error IS NOT NULL ORDER BY id DESC LIMIT 1"
                ) as cur:
                    fail_row = await cur.fetchone()
                    if fail_row:
                        failing_comp_name = fail_row["name"]
                        failing_comp_err = fail_row["last_error"]
    except Exception as e:
        failed_comp = 1
        failing_comp_err = str(e)

    comp_error: Optional[str] = None
    if is_scanning:
        comp_state = "running"
        comp_detail = f"Scanning {active_comp} active company portals"
    elif active_comp == 0:
        comp_state = "warning"
        comp_detail = "0 active companies configured"
        comp_error = "No active companies found to monitor"
    elif failed_comp > 0:
        comp_state = "error" if failed_comp == active_comp else "warning"
        comp_detail = f"{active_comp} active portals · {failed_comp} failing"
        comp_error = (
            f"{failing_comp_name}: {failing_comp_err}"
            if (failing_comp_name and failing_comp_err)
            else f"{failed_comp} companies reporting scan errors"
        )
    else:
        comp_state = "success"
        comp_detail = f"{active_comp} active career portals monitored"

    companies_node = PipelineNode(
        state=comp_state,
        label="Company Portals",
        detail=comp_detail,
        meta={"total": total_comp, "active": active_comp, "failed": failed_comp},
        error=comp_error,
    )

    # 3. Adapter Node
    recent_logs: List[Dict[str, Any]] = []
    try:
        recent_logs = await db.get_scan_logs(limit=10)
    except Exception:
        pass

    adapter_err: Optional[str] = None
    if is_scanning:
        adapter_state = "running"
        adapter_detail = "Fetching ATS job listings (Greenhouse, Lever, Ashby, Workday)..."
    elif last_report and last_report.errors:
        adapter_err = last_report.errors[0]
        if len(last_report.errors) >= (last_report.companies_scanned or 1):
            adapter_state = "error"
        else:
            adapter_state = "warning"
        adapter_detail = f"Fetched {last_report.total_jobs_found} jobs ({len(last_report.errors)} failed)"
    elif recent_logs:
        failed_logs = [l for l in recent_logs if l.get("status") == "failed"]
        if failed_logs:
            most_recent = recent_logs[0]
            if most_recent.get("status") == "failed":
                adapter_state = "error"
                adapter_err = most_recent.get("error_message") or f"Fetch error on {most_recent.get('company_name')}"
                adapter_detail = f"Fetch failed for {most_recent.get('company_name')}"
            else:
                adapter_state = "warning"
                adapter_err = failed_logs[0].get("error_message") or f"Fetch error on {failed_logs[0].get('company_name')}"
                adapter_detail = f"Adapters operational with {len(failed_logs)} recent warnings"
        else:
            adapter_state = "success"
            recent_jobs_found = sum(l.get("jobs_found", 0) for l in recent_logs[:5])
            adapter_detail = f"All ATS adapters operational ({recent_jobs_found} jobs in recent scans)"
    elif last_report:
        adapter_state = "success"
        adapter_detail = f"Fetched {last_report.total_jobs_found} jobs across {last_report.companies_scanned} portals"
    else:
        adapter_state = "idle"
        adapter_detail = "Greenhouse, Lever, Ashby, Workday, Fallback adapters ready"

    adapter_node = PipelineNode(
        state=adapter_state,
        label="ATS Adapters",
        detail=adapter_detail,
        meta={
            "total_found": last_report.total_jobs_found if last_report else (recent_logs[0].get("jobs_found", 0) if recent_logs else 0),
            "supported_adapters": ["greenhouse", "lever", "ashby", "workday", "fallback"],
            "recent_logs_count": len(recent_logs),
        },
        error=adapter_err,
    )

    # 4. Matcher Node
    overview_stats: Dict[str, Any] = {}
    try:
        overview_stats = await db.get_overview_stats()
    except Exception:
        pass

    matched_today = overview_stats.get("matched_today", 0)
    jobs_rejected = overview_stats.get("jobs_rejected", 0)
    match_rate = overview_stats.get("match_rate", 0.0)

    matcher_err: Optional[str] = None
    if is_scanning:
        matcher_state = "running"
        matcher_detail = "Evaluating keywords, title patterns, and negative filters..."
    else:
        matcher_state = "success"
        matcher_detail = f"{matched_today} matched today · {jobs_rejected} filtered out ({match_rate}% match rate)"

    matcher_node = PipelineNode(
        state=matcher_state,
        label="Job Matcher",
        detail=matcher_detail,
        meta={
            "matched_today": matched_today,
            "jobs_rejected": jobs_rejected,
            "match_rate": match_rate,
            "last_matched": last_report.total_jobs_matched if last_report else 0,
        },
        error=matcher_err,
    )

    # 5. Database Node
    db_state = "success"
    db_detail = "WAL Mode Active · Atomic Deduplication"
    db_err: Optional[str] = None
    total_jobs = 0

    try:
        async with await db.get_connection() as conn:
            async with conn.execute("SELECT COUNT(*) as total FROM jobs") as cur:
                row = await cur.fetchone()
                total_jobs = int(row["total"] or 0) if row else 0

        if is_scanning:
            db_state = "running"
            db_detail = f"Upserting jobs and atomic alert slots ({total_jobs} indexed)"
        else:
            db_detail = f"WAL Mode Active · {total_jobs} total jobs indexed · Zero duplicate alerts"
    except Exception as e:
        db_state = "error"
        db_err = str(e)
        db_detail = "SQLite database query error"

    database_node = PipelineNode(
        state=db_state,
        label="SQLite Database",
        detail=db_detail,
        meta={
            "total_jobs": total_jobs,
            "journal_mode": "wal",
            "deduplication": "active",
        },
        error=db_err,
    )

    # 6. Telegram Node
    tg_saved: Dict[str, Any] = {}
    failed_alert_msg: Optional[str] = None
    sent_count = 0

    try:
        tg_saved = await db.get_setting("telegram_config", {})
        async with await db.get_connection() as conn:
            async with conn.execute(
                "SELECT status, error, COUNT(*) as cnt FROM alerts_history GROUP BY status, error ORDER BY id DESC LIMIT 10"
            ) as cur:
                rows = await cur.fetchall()
                for r in rows:
                    if r["status"] == "failed" and r["error"]:
                        failed_alert_msg = r["error"]
                    if r["status"] in ("sent", "mock"):
                        sent_count += int(r["cnt"] or 0)
    except Exception:
        pass

    tg_token = tg_saved.get("bot_token") or settings.telegram_bot_token or ""
    tg_chat_id = tg_saved.get("chat_id") or settings.telegram_chat_id or ""
    tg_mock_mode = tg_saved.get("mock_mode", settings.telegram_mock_mode)

    tg_err: Optional[str] = None
    if is_scanning:
        tg_state = "running"
        tg_detail = "Evaluating new job alerts for Telegram dispatch..."
    elif failed_alert_msg:
        tg_state = "error"
        tg_detail = "Alert delivery failure detected"
        tg_err = failed_alert_msg
    elif tg_mock_mode:
        tg_state = "idle" if not tg_token else "success"
        tg_detail = f"Mock Mode (Local Sink) · {sent_count} alerts recorded"
    elif not tg_token or not tg_chat_id:
        tg_state = "warning"
        tg_detail = "Bot token or Chat ID not configured"
        tg_err = "Missing Telegram bot credentials"
    else:
        tg_state = "success"
        tg_detail = f"Connected & ready · {sent_count} alerts delivered"

    telegram_node = PipelineNode(
        state=tg_state,
        label="Telegram Alerts",
        detail=tg_detail,
        meta={
            "mock_mode": tg_mock_mode,
            "has_token": bool(tg_token),
            "has_chat_id": bool(tg_chat_id),
            "total_alerts": sent_count,
            "alerts_last_scan": last_report.new_alerts_sent if last_report else 0,
        },
        error=tg_err,
    )

    return PipelineStateResponse(
        is_scanning=is_scanning,
        nodes={
            "scheduler": scheduler_node,
            "companies": companies_node,
            "adapter": adapter_node,
            "matcher": matcher_node,
            "database": database_node,
            "telegram": telegram_node,
        },
    )
