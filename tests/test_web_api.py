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
async def test_logs_api(app):
    """Verify scan activity logs API endpoint."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/logs?limit=50")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

