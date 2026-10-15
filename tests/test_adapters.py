"""
Comprehensive unit tests for ATS Adapters, ATSDetector, FallbackScraper, and Core Models.
"""

from datetime import datetime, timezone
import json
import pytest
import httpx

from career_pulse.core.models import (
    JobListing,
    Job,
    JobFilterConfig,
    FilterResult,
    CompanyConfig,
    ATSDetectResult,
)
from career_pulse.adapters.base import BaseATSAdapter
from career_pulse.adapters.greenhouse import GreenhouseAdapter
from career_pulse.adapters.lever import LeverAdapter
from career_pulse.adapters.ashby import AshbyAdapter
from career_pulse.adapters.workday import WorkdayAdapter
from career_pulse.adapters.fallback import FallbackScraper
from career_pulse.adapters.detector import ATSDetector
from career_pulse.adapters import get_adapter, ADAPTER_REGISTRY


# ============================================================================
# 1. CORE MODELS TESTS
# ============================================================================

def test_job_listing_instantiation_and_aliases():
    """Verify JobListing instantiation, aliases, and unique key generation."""
    now = datetime.now(timezone.utc)
    job = JobListing(
        external_id="gh_12345",
        company_name="Acme Corp",
        provider="greenhouse",
        title="Software Engineer, Backend",
        location="San Francisco, CA",
        workplace_type="hybrid",
        is_remote=False,
        url="https://boards.greenhouse.io/acme/jobs/12345",
        department="Core Infrastructure",
        description_text="Exciting distributed systems work.",
        published_at=now,
    )

    assert job.external_id == "gh_12345"
    assert job.id == "gh_12345"
    assert job.company_name == "Acme Corp"
    assert job.company == "Acme Corp"
    assert job.remote is False
    assert job.is_remote is False
    assert job.description == "Exciting distributed systems work."
    assert job.posted_at == now
    assert job.get_unique_key() == "greenhouse:acme_corp:gh_12345"


def test_job_alias_constructor_compatibility():
    """Verify Job alias allows using alternative field names like 'company' and 'id'."""
    job = Job(
        id="lever_987",
        company="Tech Inc",
        provider="lever",
        title="Full Stack Developer",
        location="Remote - US",
        remote=True,
        url="https://jobs.lever.co/tech/987",
        description="Build full stack features.",
    )

    assert job.external_id == "lever_987"
    assert job.company_name == "Tech Inc"
    assert job.is_remote is True
    assert job.workplace_type == "unknown"
    assert job.description_text == "Build full stack features."


def test_job_filter_config_defaults():
    """Verify JobFilterConfig default lists and settings."""
    cfg = JobFilterConfig()
    assert "Software Engineer" in cfg.target_titles
    assert "senior" in cfg.negative_title_keywords
    assert "intern" in cfg.negative_title_keywords
    assert "Python" in cfg.required_skills
    assert cfg.skills_match_mode == "any"
    assert cfg.remote_only is False


def test_ats_detect_result_model():
    """Verify ATSDetectResult and alias ATSDetectResponse model structure."""
    result = ATSDetectResult(
        provider="greenhouse",
        identifier="stripe",
        confidence="high",
        canonical_url="https://boards.greenhouse.io/stripe",
    )
    assert result.provider == "greenhouse"
    assert result.identifier == "stripe"
    assert result.confidence == "high"


# ============================================================================
# 2. BASE ADAPTER UTILITY TESTS
# ============================================================================

def test_base_adapter_strip_html():
    """Verify HTML stripping, entity decoding, and whitespace normalization."""
    raw = "<p>Join our <strong>engineering</strong> team!&nbsp;We build &lt;scale&gt; systems.</p><br/>"
    clean = BaseATSAdapter.strip_html(raw)
    assert clean == "Join our engineering team! We build <scale> systems."

    assert BaseATSAdapter.strip_html(None) == ""
    assert BaseATSAdapter.strip_html("   ") == ""


def test_base_adapter_detect_workplace_and_remote():
    """Verify workplace type and remote flag detection heuristics."""
    # Explicit remote flag
    is_rem, wp = BaseATSAdapter.detect_workplace_and_remote("Engineer", "New York", is_remote_flag=True)
    assert is_rem is True
    assert wp == "remote"

    # Title keyword
    is_rem, wp = BaseATSAdapter.detect_workplace_and_remote("Remote Software Developer", "Anytown")
    assert is_rem is True
    assert wp == "remote"

    # Location keyword
    is_rem, wp = BaseATSAdapter.detect_workplace_and_remote("Frontend Engineer", "San Francisco / Remote")
    assert is_rem is True
    assert wp == "remote"

    # Hybrid keyword
    is_rem, wp = BaseATSAdapter.detect_workplace_and_remote("Site Reliability Engineer", "Seattle, WA (Hybrid)")
    assert is_rem is False
    assert wp == "hybrid"

    # On-site
    is_rem, wp = BaseATSAdapter.detect_workplace_and_remote("Hardware Engineer", "Austin, TX")
    assert is_rem is False
    assert wp == "on_site"


def test_base_adapter_parse_datetime_safe():
    """Verify robust datetime parsing for ISO strings and epoch timestamps."""
    iso_z = "2024-03-20T14:32:00Z"
    dt1 = BaseATSAdapter.parse_datetime_safe(iso_z)
    assert dt1 is not None
    assert dt1.year == 2024 and dt1.month == 3

    # Epoch milliseconds (1710945120000)
    epoch_ms = 1710945120000
    dt2 = BaseATSAdapter.parse_datetime_safe(epoch_ms)
    assert dt2 is not None
    assert dt2.year == 2024

    # Invalid string
    assert BaseATSAdapter.parse_datetime_safe("not-a-date") is None
    assert BaseATSAdapter.parse_datetime_safe(None) is None


# ============================================================================
# 3. GREENHOUSE ADAPTER TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_greenhouse_adapter_fetch_jobs_success():
    """Test GreenhouseAdapter successfully parsing standard board payload."""
    payload = {
        "jobs": [
            {
                "id": 551234,
                "title": "Software Engineer II",
                "updated_at": "2024-03-20T14:32:00-04:00",
                "absolute_url": "https://boards.greenhouse.io/acme/jobs/551234",
                "location": {"name": "San Francisco, CA / Remote"},
                "offices": [{"id": 1, "name": "San Francisco"}],
                "departments": [{"id": 10, "name": "Platform Infrastructure"}],
                "content": "<p>We are seeking a <b>Software Engineer</b> to build data pipelines.</p>",
            }
        ],
        "meta": {"total": 1},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert "boards-api.greenhouse.io/v1/boards/acme/jobs" in str(request.url)
        assert request.url.params.get("content") == "true"
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = GreenhouseAdapter(client=client)
        jobs = await adapter.fetch_jobs("acme", company_name="Acme Corp")

        assert len(jobs) == 1
        job = jobs[0]
        assert job.external_id == "551234"
        assert job.company_name == "Acme Corp"
        assert job.provider == "greenhouse"
        assert job.title == "Software Engineer II"
        assert "San Francisco" in job.location
        assert job.is_remote is True
        assert job.workplace_type == "remote"
        assert job.department == "Platform Infrastructure"
        assert "We are seeking a Software Engineer" in job.description_text
        assert job.published_at is not None
        assert job.url == "https://boards.greenhouse.io/acme/jobs/551234"


@pytest.mark.asyncio
async def test_greenhouse_adapter_404_returns_empty():
    """Test GreenhouseAdapter gracefully returns empty list on 404 board not found."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "Not Found"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = GreenhouseAdapter(client=client)
        jobs = await adapter.fetch_jobs("nonexistent_board")
        assert jobs == []


@pytest.mark.asyncio
async def test_greenhouse_adapter_429_raises_status_error():
    """Test GreenhouseAdapter raises on rate limit (429)."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "60"}, json={"error": "Rate limit exceeded"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = GreenhouseAdapter(client=client)
        with pytest.raises(httpx.HTTPStatusError):
            await adapter.fetch_jobs("acme")


# ============================================================================
# 4. LEVER ADAPTER TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_lever_adapter_fetch_jobs_with_pagination():
    """Test LeverAdapter parsing postings with multi-page offset pagination."""
    # Page 1 returns 100 items; Page 2 returns 1 item; Page 3 returns 0 items.
    def handler(request: httpx.Request) -> httpx.Response:
        skip = int(request.url.params.get("skip", 0))
        limit = int(request.url.params.get("limit", 100))
        assert request.url.params.get("mode") == "json"

        if skip == 0:
            # Generate 100 mock postings
            batch = [
                {
                    "id": f"lever_p1_{i}",
                    "text": f"Software Engineer #{i}",
                    "createdAt": 1696000000000,
                    "hostedUrl": f"https://jobs.lever.co/initech/lever_p1_{i}",
                    "applyUrl": f"https://jobs.lever.co/initech/lever_p1_{i}/apply",
                    "categories": {
                        "location": "Remote",
                        "department": "Engineering",
                    },
                    "workplaceType": "remote",
                    "descriptionPlain": f"Role description for #{i}",
                    "lists": [{"text": "Requirements", "content": "<ul><li>Python</li></ul>"}],
                }
                for i in range(limit)
            ]
            return httpx.Response(200, json=batch)
        elif skip == 100:
            batch = [
                {
                    "id": "lever_p2_1",
                    "text": "Principal Architect",
                    "createdAt": 1696000000000,
                    "hostedUrl": "https://jobs.lever.co/initech/lever_p2_1",
                    "categories": {"location": "Austin, TX", "department": "Architecture"},
                    "workplaceType": "onsite",
                    "descriptionPlain": "Architecture lead",
                }
            ]
            return httpx.Response(200, json=batch)
        return httpx.Response(200, json=[])

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = LeverAdapter(client=client)
        jobs = await adapter.fetch_jobs("initech", company_name="Initech")

        assert len(jobs) == 101
        assert jobs[0].external_id == "lever_p1_0"
        assert jobs[0].is_remote is True
        assert jobs[0].workplace_type == "remote"
        assert "Requirements" in jobs[0].description_text
        assert "Python" in jobs[0].description_text

        # Item on page 2
        assert jobs[100].external_id == "lever_p2_1"
        assert jobs[100].title == "Principal Architect"
        assert jobs[100].workplace_type == "on_site"


@pytest.mark.asyncio
async def test_lever_adapter_404_returns_empty():
    """Test LeverAdapter gracefully handles 404 non-existent company."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "Not Found"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = LeverAdapter(client=client)
        jobs = await adapter.fetch_jobs("nonexistent_company")
        assert jobs == []


# ============================================================================
# 5. ASHBY ADAPTER TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_ashby_adapter_fetch_jobs_success():
    """Test AshbyAdapter parsing postings including compensation data."""
    payload = {
        "apiVersion": "1.0",
        "jobs": [
            {
                "id": "ashby_123",
                "title": "Full Stack Engineer",
                "department": "Engineering",
                "team": "Core Product",
                "isRemote": True,
                "location": "Remote - US",
                "publishedAt": "2024-03-15T10:00:00.000Z",
                "jobUrl": "https://jobs.ashbyhq.com/linear/ashby_123",
                "applyUrl": "https://jobs.ashbyhq.com/linear/ashby_123/application",
                "descriptionPlain": "Build next-generation product issue tracker.",
                "compensation": {
                    "compensationTierSummary": "$140,000 - $180,000 USD"
                },
            }
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert "api.ashbyhq.com/posting-api/job-board/linear" in str(request.url)
        assert request.url.params.get("includeCompensation") == "true"
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = AshbyAdapter(client=client)
        jobs = await adapter.fetch_jobs("linear", company_name="Linear")

        assert len(jobs) == 1
        job = jobs[0]
        assert job.external_id == "ashby_123"
        assert job.company_name == "Linear"
        assert job.provider == "ashby"
        assert job.title == "Full Stack Engineer"
        assert job.is_remote is True
        assert job.workplace_type == "remote"
        assert job.department == "Engineering"
        assert "$140,000 - $180,000 USD" in job.description_text
        assert job.url == "https://jobs.ashbyhq.com/linear/ashby_123/application"


@pytest.mark.asyncio
async def test_ashby_adapter_404_returns_empty():
    """Test AshbyAdapter returns empty list when organization not found."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "Not Found"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = AshbyAdapter(client=client)
        jobs = await adapter.fetch_jobs("unknown_org")
        assert jobs == []


# ============================================================================
# 6. WORKDAY ADAPTER TESTS
# ============================================================================

def test_workday_url_parsing():
    """Verify Workday URL and identifier parsing for tenant, site, and domain."""
    # Podded full URL
    t1, s1, h1 = WorkdayAdapter.parse_workday_url(
        "https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite/jobs"
    )
    assert t1 == "nvidia"
    assert s1 == "NVIDIAExternalCareerSite"
    assert h1 == "nvidia.wd5.myworkdayjobs.com"

    # Colon notation tenant:site:host
    t2, s2, h2 = WorkdayAdapter.parse_workday_url("adobe:AdobeExternal:adobe.wd5.myworkdayjobs.com")
    assert t2 == "adobe"
    assert s2 == "AdobeExternal"
    assert h2 == "adobe.wd5.myworkdayjobs.com"


@pytest.mark.asyncio
async def test_workday_adapter_fetch_jobs_success():
    """Test WorkdayAdapter POST request, offset pagination, and requisition ID extraction."""
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        body = json.loads(request.content.decode("utf-8"))
        offset = body.get("offset", 0)

        if offset == 0:
            return httpx.Response(
                200,
                json={
                    "total": 2,
                    "limit": 20,
                    "offset": 0,
                    "jobPostings": [
                        {
                            "title": "Software Engineer, Infrastructure",
                            "externalPath": "/job/San-Jose-CA/Software-Engineer_JR202401",
                            "locationsText": "San Jose, CA, USA / Remote",
                            "postedOn": "Posted 2 Days Ago",
                            "bulletFields": ["JR202401"],
                        },
                        {
                            "title": "AI Research Scientist",
                            "externalPath": "/job/Santa-Clara-CA/AI-Research_JR202402",
                            "locationsText": "Santa Clara, CA, USA",
                            "postedOn": "Posted Today",
                            "bulletFields": [],
                        },
                    ],
                },
            )
        return httpx.Response(200, json={"total": 2, "limit": 20, "offset": offset, "jobPostings": []})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = WorkdayAdapter(client=client)
        jobs = await adapter.fetch_jobs(
            company_identifier="https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite",
            company_name="NVIDIA",
        )

        assert len(jobs) == 2
        # First job: external_id from bulletFields
        assert jobs[0].external_id == "JR202401"
        assert jobs[0].provider == "workday"
        assert jobs[0].title == "Software Engineer, Infrastructure"
        assert jobs[0].is_remote is True
        assert "NVIDIAExternalCareerSite" in jobs[0].url

        # Second job: external_id extracted from externalPath regex
        assert jobs[1].external_id == "JR202402"
        assert jobs[1].is_remote is False
        assert jobs[1].workplace_type == "on_site"


# ============================================================================
# 7. FALLBACK SCRAPER TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_fallback_scraper_json_ld_extraction():
    """Test FallbackScraper extracting Schema.org JobPosting without browser."""
    html_doc = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Careers at Example Corp</title>
        <script type="application/ld+json">
        {
            "@context": "https://schema.org",
            "@type": "JobPosting",
            "title": "Senior Python Engineer",
            "identifier": {"value": "EX-9988"},
            "description": "<p>We are seeking an experienced <b>Python</b> developer.</p>",
            "datePosted": "2024-03-25T08:00:00Z",
            "url": "https://example.com/careers/python-dev",
            "jobLocationType": "TELECOMMUTE",
            "jobLocation": {
                "@type": "Place",
                "address": {
                    "addressLocality": "Remote",
                    "addressCountry": "US"
                }
            }
        }
        </script>
    </head>
    <body><h1>Open Roles</h1></body>
    </html>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html_doc)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        scraper = FallbackScraper(client=client)
        jobs = await scraper.fetch_jobs("https://example.com/careers", company_name="Example Corp")

        assert len(jobs) == 1
        job = jobs[0]
        assert job.external_id == "EX-9988"
        assert job.title == "Senior Python Engineer"
        assert job.is_remote is True
        assert job.workplace_type == "remote"
        assert "experienced Python developer" in job.description_text
        assert job.url == "https://example.com/careers/python-dev"


@pytest.mark.asyncio
async def test_fallback_scraper_dom_card_extraction():
    """Test FallbackScraper extracting semantic DOM cards when no JSON-LD is found."""
    html_doc = """
    <!DOCTYPE html>
    <html>
    <body>
        <div class="jobs-container">
            <div class="job-card">
                <a href="/careers/job/101">
                    <h3>Backend Systems Engineer</h3>
                </a>
                <span class="location">San Francisco, CA / Remote</span>
            </div>
            <div class="job-card">
                <a href="/careers/job/102">
                    <h3>Data Scientist</h3>
                </a>
                <span class="location">New York, NY</span>
            </div>
        </div>
    </body>
    </html>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html_doc)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        scraper = FallbackScraper(client=client)
        jobs = await scraper.fetch_jobs("https://customcompany.com/careers", company_name="Custom Company")

        assert len(jobs) == 2
        assert jobs[0].title == "Backend Systems Engineer"
        assert jobs[0].url == "https://customcompany.com/careers/job/101"
        assert jobs[0].is_remote is True
        assert jobs[1].title == "Data Scientist"
        assert jobs[1].url == "https://customcompany.com/careers/job/102"
        assert jobs[1].is_remote is False


# ============================================================================
# 8. ATS DETECTOR TESTS
# ============================================================================

def test_ats_detector_phase1_instant_matches():
    """Verify Phase 1 regex matching across all supported ATS vendors."""
    # Greenhouse standard
    res_gh = ATSDetector.match_url("https://boards.greenhouse.io/stripe")
    assert res_gh is not None
    assert res_gh.provider == "greenhouse"
    assert res_gh.identifier == "stripe"
    assert res_gh.confidence == "high"

    # Greenhouse embedded with query parameter
    res_gh_embed = ATSDetector.match_url("https://job-boards.greenhouse.io/embed/job_board?for=figma")
    assert res_gh_embed is not None
    assert res_gh_embed.provider == "greenhouse"
    assert res_gh_embed.identifier == "figma"

    # Lever
    res_lever = ATSDetector.match_url("https://jobs.lever.co/netflix")
    assert res_lever is not None
    assert res_lever.provider == "lever"
    assert res_lever.identifier == "netflix"

    # Ashby
    res_ashby = ATSDetector.match_url("https://jobs.ashbyhq.com/linear")
    assert res_ashby is not None
    assert res_ashby.provider == "ashby"
    assert res_ashby.identifier == "linear"

    # Workday
    res_wd = ATSDetector.match_url("https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite")
    assert res_wd is not None
    assert res_wd.provider == "workday"
    assert "nvidia" in res_wd.identifier
    assert res_wd.career_site == "NVIDIAExternalCareerSite"

    # Unmatched custom portal
    assert ATSDetector.match_url("https://custom-portal.org/careers") is None


@pytest.mark.asyncio
async def test_ats_detector_phase2_probing():
    """Verify Phase 2 HTTP probing detecting iframes and embed markers."""
    # Custom career page embedding a Greenhouse iframe
    html_page = """
    <html>
        <body>
            <h1>Careers</h1>
            <iframe src="https://boards.greenhouse.io/embed/job_board?for=airtable"></iframe>
        </body>
    </html>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html_page)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        detector = ATSDetector(client=client)
        detected = await detector.detect("https://airtable.com/careers")

        assert detected.provider == "greenhouse"
        assert detected.identifier == "airtable"
        assert detected.confidence == "medium"


@pytest.mark.asyncio
async def test_ats_detector_phase2_fallback_to_custom():
    """Verify Phase 2 defaults to 'custom' provider when no ATS markers exist."""
    html_page = "<html><body><h1>Careers</h1><p>Send your resume to jobs@test.com</p></body></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html_page)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        detector = ATSDetector(client=client)
        detected = await detector.detect("https://privatestartup.io/jobs")

        assert detected.provider == "custom"
        assert detected.confidence == "fallback"


def test_get_adapter_registry():
    """Verify get_adapter factory returns appropriate adapter instances."""
    gh = get_adapter("greenhouse")
    assert isinstance(gh, GreenhouseAdapter)

    lev = get_adapter("lever")
    assert isinstance(lev, LeverAdapter)

    ash = get_adapter("ashby")
    assert isinstance(ash, AshbyAdapter)

    wd = get_adapter("workday")
    assert isinstance(wd, WorkdayAdapter)

    cust = get_adapter("custom")
    assert isinstance(cust, FallbackScraper)

    pw = get_adapter("playwright")
    assert isinstance(pw, FallbackScraper)


# ============================================================================
# 9. ADDITIONAL EDGE CASE AND CONTEXT MANAGER TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_adapter_context_manager_lifecycle():
    """Verify adapter works as an async context manager and closes internal client cleanly."""
    async with GreenhouseAdapter() as adapter:
        assert adapter.provider == "greenhouse"
        client = await adapter._get_client()
        assert not client.is_closed

    # After exiting context manager, client should be closed
    assert adapter._client is None or adapter._client.is_closed


@pytest.mark.asyncio
async def test_greenhouse_empty_jobs_array():
    """Verify Greenhouse handles empty jobs list correctly."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jobs": [], "meta": {"total": 0}})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = GreenhouseAdapter(client=client)
        jobs = await adapter.fetch_jobs("empty_board")
        assert jobs == []


@pytest.mark.asyncio
async def test_lever_empty_or_non_list_response():
    """Verify Lever handles empty or unexpected response format gracefully."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = LeverAdapter(client=client)
        jobs = await adapter.fetch_jobs("empty_lever")
        assert jobs == []


@pytest.mark.asyncio
async def test_workday_empty_job_postings():
    """Verify Workday handles 0 postings gracefully."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"total": 0, "limit": 20, "offset": 0, "jobPostings": []})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = WorkdayAdapter(client=client)
        jobs = await adapter.fetch_jobs("tenant:site:host")
        assert jobs == []


@pytest.mark.asyncio
async def test_fallback_scraper_empty_html():
    """Verify FallbackScraper on empty HTML produces empty list without error."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html><body></body></html>")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        scraper = FallbackScraper(client=client)
        jobs = await scraper.fetch_jobs("https://empty.example.com")
        assert jobs == []

