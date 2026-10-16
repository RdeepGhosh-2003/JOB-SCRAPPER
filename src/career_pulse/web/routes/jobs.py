"""
Job History & Feed REST Endpoints.
"""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query
from career_pulse.config import settings
from career_pulse.db.session import Database

router = APIRouter(prefix="/api/jobs", tags=["jobs"])
db = Database(settings.db_path)


@router.get("")
async def list_jobs(
    company_id: Optional[int] = Query(None),
    is_remote: Optional[bool] = Query(None),
    q: Optional[str] = Query(None, description="Search query for title or company"),
    matched_only: Optional[bool] = Query(None, description="Filter only matching jobs that triggered an alert"),
    alert_status: Optional[str] = Query(None, description="Filter by specific alert status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Dict[str, Any]:
    """List scraped jobs with filtering, search query, and alert status."""
    conditions = ["1=1"]
    params: List[Any] = []

    if company_id is not None:
        conditions.append("j.company_id = ?")
        params.append(company_id)

    if is_remote is not None:
        conditions.append("j.is_remote = ?")
        params.append(1 if is_remote else 0)

    if matched_only:
        conditions.append("a.status IN ('sent', 'mock')")
    elif alert_status:
        conditions.append("a.status = ?")
        params.append(alert_status)

    if q and q.strip():
        search_term = f"%{q.strip()}%"
        conditions.append("(j.title LIKE ? OR c.name LIKE ? OR j.description_text LIKE ?)")
        params.extend([search_term, search_term, search_term])

    where_clause = " AND ".join(conditions)

    async with await db.get_connection() as conn:
        # Get total matching count
        count_query = f"""
            SELECT COUNT(j.id) as total
            FROM jobs j
            JOIN companies c ON c.id = j.company_id
            LEFT JOIN alerts_history a ON a.job_id = j.id AND a.channel = 'telegram'
            WHERE {where_clause}
        """
        async with conn.execute(count_query, tuple(params)) as cur:
            row = await cur.fetchone()
            total = row["total"] if row else 0

        # Fetch paginated jobs
        data_query = f"""
            SELECT j.*, c.name as company_name, c.ats_provider,
                   a.status as alert_status, a.sent_at as alert_sent_at
            FROM jobs j
            JOIN companies c ON c.id = j.company_id
            LEFT JOIN alerts_history a ON a.job_id = j.id AND a.channel = 'telegram'
            WHERE {where_clause}
            ORDER BY j.first_seen_at DESC
            LIMIT ? OFFSET ?
        """
        fetch_params = list(params) + [limit, offset]
        async with conn.execute(data_query, tuple(fetch_params)) as cur:
            rows = await cur.fetchall()
            jobs = [dict(r) for r in rows]

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "jobs": jobs,
    }


@router.delete("")
async def clear_jobs(company_id: Optional[int] = Query(None)) -> Dict[str, Any]:
    """Delete jobs, optionally filtered by company_id, or all jobs."""
    async with await db.get_connection() as conn:
        if company_id is not None:
            cursor = await conn.execute("DELETE FROM jobs WHERE company_id = ?", (company_id,))
        else:
            cursor = await conn.execute("DELETE FROM jobs")
        await conn.commit()
        return {"success": True, "deleted_count": cursor.rowcount}


@router.delete("/{job_id}")
async def delete_job(job_id: int) -> Dict[str, Any]:
    """Delete a specific job listing."""
    async with await db.get_connection() as conn:
        cursor = await conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        await conn.commit()
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Job not found")
        return {"success": True, "message": f"Job {job_id} deleted"}

