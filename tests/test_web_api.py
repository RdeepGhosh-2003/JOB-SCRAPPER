"""
Unit and Integration Tests for CareerPulse FastAPI Web Dashboard & REST API.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from career_pulse.web.app import create_app
from career_pulse.db.session import Database
from career_pulse.config import settings


@pytest.fixture
def app():
    return create_app()


@pytest.mark.asyncio
async def test_dashboard_index_route(app):
    """Verify that root / serves the HTML single-page dashboard shell."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/")
        assert resp.status_code == 200
        assert "CareerPulse" in resp.text
        assert "Discovered Jobs" in resp.text


@pytest.mark.asyncio
async def test_companies_api(app):
    """Verify company registration and auto-detection endpoints."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Detect ATS
        det = await client.post("/api/companies/detect", json={"url": "https://boards.greenhouse.io/figma"})
        assert det.status_code == 200
        data = det.json()
        assert data["detected"] is True
        assert data["provider"] == "greenhouse"

        # List companies
        resp = await client.get("/api/companies")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_companies_registry_api(app):
    """Verify company registry search endpoint."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Default query returns up to 10
        resp = await client.get("/api/companies/registry")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 10

        # Specific query
        q_resp = await client.get("/api/companies/registry?q=stripe")
        assert q_resp.status_code == 200
        q_data = q_resp.json()
        assert len(q_data) >= 1
        assert q_data[0]["name"] == "Stripe"
        assert q_data[0]["ats"] == "greenhouse"

        # Notion query
        notion_resp = await client.get("/api/companies/registry?q=notion")
        assert notion_resp.status_code == 200
        notion_data = notion_resp.json()
        assert len(notion_data) >= 1
        assert notion_data[0]["name"] == "Notion"
        assert notion_data[0]["ats"] == "greenhouse"
        assert "boards.greenhouse.io" in notion_data[0]["career_url"]



@pytest.mark.asyncio
async def test_filters_api(app):
    """Verify fetching and saving search filters."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Get active filters
        resp = await client.get("/api/filters")
        assert resp.status_code == 200
        data = resp.json()
        assert "target_titles" in data

        # Update filters
        data["target_titles"].append("Data Engineer")
        update_resp = await client.put("/api/filters", json=data)
        assert update_resp.status_code == 200
        assert update_resp.json()["success"] is True


@pytest.mark.asyncio
async def test_jobs_api(app):
    """Verify paginated jobs listing and deletion endpoints."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/jobs?limit=10")
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "jobs" in data

        # Test deleting non-existent job returns 404
        del_resp = await client.delete("/api/jobs/999999999")
        assert del_resp.status_code == 404



@pytest.mark.asyncio
async def test_scheduler_api(app):
    """Verify scheduler status and config endpoints."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/scheduler/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "is_running" in data
        assert "in_active_window" in data
        assert "config" in data


@pytest.mark.asyncio
async def test_scheduler_pause_resume_api(app):
    """Verify scheduler pause and resume endpoints."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        p_resp = await client.post("/api/scheduler/pause")
        assert p_resp.status_code == 200
        p_data = p_resp.json()
        assert p_data["success"] is True
        assert p_data["message"] == "Scheduler paused"

        status_resp = await client.get("/api/scheduler/status")
        assert status_resp.status_code == 200
        assert status_resp.json()["config"]["enabled"] is False

        r_resp = await client.post("/api/scheduler/resume")
        assert r_resp.status_code == 200
        r_data = r_resp.json()
        assert r_data["success"] is True
        assert "Scheduler resumed" in r_data["message"]

        status_resp2 = await client.get("/api/scheduler/status")
        assert status_resp2.status_code == 200
        assert status_resp2.json()["config"]["enabled"] is True



@pytest.mark.asyncio
async def test_logs_api(app):
    """Verify scan activity logs API endpoint."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/logs?limit=50")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)


@pytest.mark.asyncio
async def test_overview_stats_api(app):
    """Verify GET /api/overview/stats returns matched_today, jobs_rejected, last_scan, match_rate."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/overview/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "matched_today" in data
        assert "jobs_rejected" in data
        assert "last_scan" in data
        assert "match_rate" in data
        assert isinstance(data["matched_today"], int)
        assert isinstance(data["jobs_rejected"], int)
        assert isinstance(data["match_rate"], (int, float))


@pytest.mark.asyncio
async def test_jobs_matched_only_api(app):
    """Verify GET /api/jobs with matched_only=true filter."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/jobs?limit=10&matched_only=true")
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "jobs" in data
        for j in data["jobs"]:
            assert j.get("alert_status") in ("sent", "mock")


