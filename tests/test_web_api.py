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


@pytest.mark.asyncio
async def test_pipeline_state_api(app):
    """Verify GET /api/pipeline/state returns 6 stages with required schema."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/pipeline/state")
        assert resp.status_code == 200
        data = resp.json()

        assert "is_scanning" in data
        assert isinstance(data["is_scanning"], bool)
        assert "nodes" in data
        assert "last_cycle" in data
        if data["last_cycle"] is not None:
            assert isinstance(data["last_cycle"], dict)
            assert "duration_seconds" in data["last_cycle"]
            assert "companies_scanned" in data["last_cycle"]
            assert "total_jobs_matched" in data["last_cycle"]

        expected_nodes = ["scheduler", "companies", "adapter", "matcher", "database", "telegram"]
        for node_key in expected_nodes:
            assert node_key in data["nodes"], f"Missing node: {node_key}"
            node = data["nodes"][node_key]
            assert "state" in node
            assert node["state"] in ("running", "success", "error", "warning", "idle")
            assert "label" in node and isinstance(node["label"], str) and len(node["label"]) > 0
            assert "detail" in node and isinstance(node["detail"], str)
            assert "meta" in node and isinstance(node["meta"], dict)
            assert "error" in node

        # Check adapter breakdown and company failed_companies list
        assert "adapters_breakdown" in data["nodes"]["adapter"]["meta"]
        assert isinstance(data["nodes"]["adapter"]["meta"]["adapters_breakdown"], dict)
        for expected_ats in ["greenhouse", "lever", "ashby", "workday", "fallback"]:
            assert expected_ats in data["nodes"]["adapter"]["meta"]["adapters_breakdown"]
        assert "failed_companies" in data["nodes"]["companies"]["meta"]
        assert isinstance(data["nodes"]["companies"]["meta"]["failed_companies"], list)


@pytest.mark.asyncio
async def test_pipeline_state_scanning_mode(app):
    """Verify GET /api/pipeline/state reflects scanning mode when active."""
    from career_pulse.web.routes import scan
    original = scan._is_scanning
    try:
        scan._is_scanning = True
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/pipeline/state")
            assert resp.status_code == 200
            data = resp.json()
            assert data["is_scanning"] is True
            assert data["nodes"]["companies"]["state"] == "running"
            assert data["nodes"]["adapter"]["state"] == "running"
            assert data["nodes"]["matcher"]["state"] == "running"
            assert data["nodes"]["database"]["state"] == "running"
            assert data["nodes"]["telegram"]["state"] == "running"
    finally:
        scan._is_scanning = original


@pytest.mark.asyncio
async def test_pipeline_state_error_pinpointing(app):
    """Verify stage-by-stage error pinpointing when a failure is detected in database."""
    db = Database(settings.db_path)
    async with await db.get_connection() as conn:
        cursor = await conn.execute(
            """
            INSERT INTO companies (name, career_url, ats_provider, identifier, url, provider, scan_status, last_error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "Failing Pipeline Test Inc",
                "https://failing-test.example.com",
                "greenhouse",
                "failing-test",
                "https://failing-test.example.com",
                "greenhouse",
                "failed",
                "HTTP 503 Service Unavailable",
            ),
        )
        await conn.commit()
        comp_id = cursor.lastrowid

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/pipeline/state")
            assert resp.status_code == 200
            data = resp.json()
            comp_node = data["nodes"]["companies"]
            assert comp_node["state"] in ("error", "warning")
            assert comp_node["error"] is not None
            assert "503" in comp_node["error"]
            failed_comps = comp_node["meta"].get("failed_companies", [])
            assert any(fc["name"] == "Failing Pipeline Test Inc" and "503" in fc["error"] for fc in failed_comps)
    finally:
        async with await db.get_connection() as conn:
            await conn.execute("DELETE FROM companies WHERE id = ?", (comp_id,))
            await conn.commit()


@pytest.mark.asyncio
async def test_pipeline_dashboard_html_elements(app):
    """Verify dashboard HTML contains the pipeline tab button, tab panel, badge, run button, summary, and flow container."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/")
        assert resp.status_code == 200
        html = resp.text
        assert 'data-tab="tab-pipeline"' in html
        assert 'id="tab-pipeline"' in html
        assert 'id="pipeline-flow"' in html
        assert 'id="pipeline-scan-badge"' in html
        assert 'id="btn-pipeline-run-scan"' in html
        assert 'id="pipeline-cycle-summary"' in html
        assert "Live Pipeline Monitor" in html


