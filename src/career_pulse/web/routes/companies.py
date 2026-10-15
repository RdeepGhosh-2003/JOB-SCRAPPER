"""
Company Management REST Endpoints.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from career_pulse.adapters.detector import ATSDetector
from career_pulse.db.session import Database
from career_pulse.config import settings

REGISTRY_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "company_registry.json"


def _load_company_registry() -> List[Dict[str, Any]]:
    if REGISTRY_PATH.exists():
        try:
            with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


router = APIRouter(prefix="/api/companies", tags=["companies"])
db = Database(settings.db_path)


class CompanyCreateRequest(BaseModel):
    name: str = Field(..., min_length=1)
    career_url: str = Field(..., min_length=3)
    ats_provider: Optional[str] = None
    identifier: Optional[str] = None


class DetectRequest(BaseModel):
    url: str = Field(..., min_length=3)


@router.get("")
async def list_companies() -> List[Dict[str, Any]]:
    """List all configured target companies with job counts and scan status."""
    async with await db.get_connection() as conn:
        async with conn.execute(
            """
            SELECT c.*, 
                   COUNT(j.id) as job_count,
                   SUM(CASE WHEN a.status IN ('sent', 'mock') THEN 1 ELSE 0 END) as alerts_count
            FROM companies c
            LEFT JOIN jobs j ON j.company_id = c.id
            LEFT JOIN alerts_history a ON a.job_id = j.id
            GROUP BY c.id
            ORDER BY c.created_at DESC
            """
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


@router.post("")
async def add_company(req: CompanyCreateRequest) -> Dict[str, Any]:
    """Add a new company with automatic ATS detection from URL."""
    provider = (req.ats_provider or "").lower().strip()
    identifier = req.identifier

    # Auto-detect ATS provider if not specified
    if not provider or provider == "custom":
        detected = ATSDetector.match_url(req.career_url)
        if detected:
            provider = detected.provider
            identifier = identifier or detected.identifier
        else:
            provider = "custom"

    async with await db.get_connection() as conn:
        try:
            cursor = await conn.execute(
                """
                INSERT INTO companies (name, career_url, ats_provider, identifier, url, provider)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (req.name.strip(), req.career_url.strip(), provider, identifier, req.career_url.strip(), provider),
            )
            await conn.commit()
            company_id = cursor.lastrowid
            return {
                "id": company_id,
                "name": req.name.strip(),
                "career_url": req.career_url.strip(),
                "ats_provider": provider,
                "identifier": identifier,
                "message": "Company registered successfully",
            }
        except Exception as e:
            if "UNIQUE constraint failed" in str(e):
                raise HTTPException(status_code=400, detail=f"Company with name '{req.name}' already exists.")
            raise HTTPException(status_code=500, detail=str(e))


@router.get("/registry")
async def get_company_registry(q: str = Query(default="")) -> List[Dict[str, Any]]:
    """Return companies matching query from the curated registry, identifying already added companies."""
    companies = _load_company_registry()
    query = (q or "").strip().lower()

    # Query currently monitored companies to check already added status
    existing_names = set()
    existing_urls = set()
    try:
        async with await db.get_connection() as conn:
            async with conn.execute("SELECT LOWER(TRIM(name)) as name, LOWER(TRIM(career_url)) as url FROM companies") as cursor:
                rows = await cursor.fetchall()
                for r in rows:
                    if r["name"]:
                        existing_names.add(r["name"])
                    if r["url"]:
                        existing_urls.add(r["url"])
    except Exception:
        pass

    enriched = []
    for c in companies:
        c_copy = dict(c)
        c_name = c.get("name", "").strip().lower()
        c_url = c.get("career_url", "").strip().lower()
        c_copy["already_added"] = (c_name in existing_names or c_url in existing_urls)
        enriched.append(c_copy)

    if not query:
        # Prioritize unadded companies first so they appear at top of suggestions, filling up to 10
        sorted_by_unadded = sorted(enriched, key=lambda c: 1 if c.get("already_added") else 0)
        return sorted_by_unadded[:10]

    matches = [c for c in enriched if query in c.get("name", "").lower()]
    return matches[:8]


@router.delete("/{company_id}")
async def delete_company(company_id: int) -> Dict[str, Any]:
    """Delete a company and its associated jobs."""
    async with await db.get_connection() as conn:
        cursor = await conn.execute("DELETE FROM companies WHERE id = ?", (company_id,))
        await conn.commit()
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Company not found")
        return {"success": True, "message": f"Company {company_id} deleted"}


@router.post("/detect")
async def detect_ats(req: DetectRequest) -> Dict[str, Any]:
    """Test ATS auto-detection for any career URL."""
    res = ATSDetector.match_url(req.url)
    if res:
        return {
            "detected": True,
            "provider": res.provider,
            "identifier": res.identifier,
            "career_site": res.career_site,
            "confidence": res.confidence,
        }
    return {
        "detected": False,
        "provider": "custom",
        "confidence": "fallback",
        "message": "Custom career portal. Will use Playwright / HTML DOM fallback.",
    }
