"""
Adversarial Stress Test Suite for Milestone 1:
- Core Model Bidirectional Alias Compatibility (Job / JobListing)
- FallbackScraper Robustness on Dirty HTML & Malformed JSON-LD
- LeverAdapter Pagination Termination and Edge Conditions
"""

from datetime import datetime, timezone
import json
import pytest
import httpx
from bs4 import BeautifulSoup

from career_pulse.core.models import Job, JobListing
from career_pulse.adapters.fallback import FallbackScraper
from career_pulse.adapters.lever import LeverAdapter


# ============================================================================
# 1. MODEL BIDIRECTIONAL ALIAS COMPATIBILITY STRESS TESTS
# ============================================================================

class TestModelBidirectionalAliases:
    """Stress test Job / JobListing bidirectional alias behavior."""

    def test_canonical_fields_instantiation(self):
        """Instantiate using canonical field names and verify property aliases."""
        now = datetime.now(timezone.utc)
        listing = JobListing(
            external_id="ext-001",
            company_name="Acme Inc",
            title="Senior Backend Engineer",
            location="San Francisco, CA",
            is_remote=True,
            url="https://example.com/jobs/1",
            description_text="Backend systems in Python.",
            published_at=now,
        )

        # Verify canonical attributes
        assert listing.external_id == "ext-001"
        assert listing.company_name == "Acme Inc"
        assert listing.is_remote is True
        assert listing.description_text == "Backend systems in Python."
        assert listing.published_at == now

        # Verify alias properties
        assert listing.id == "ext-001"
        assert listing.company == "Acme Inc"
        assert listing.remote is True
        assert listing.description == "Backend systems in Python."
        assert listing.posted_at == now

    def test_alias_fields_instantiation(self):
        """Instantiate using legacy / alternative alias field names."""
        now = datetime.now(timezone.utc)
        job = Job(
            id="alias-002",
            company="Beta Corp",
            title="Frontend Engineer",
            location="Remote",
            remote=False,
            url="https://example.com/jobs/2",
            description="React and TypeScript.",
            posted_at=now,
        )

        # Verify canonical attributes populated from aliases
        assert job.external_id == "alias-002"
        assert job.company_name == "Beta Corp"
        assert job.is_remote is False
        assert job.description_text == "React and TypeScript."
        assert job.published_at == now

        # Verify alias properties match
        assert job.id == "alias-002"
        assert job.company == "Beta Corp"
        assert job.remote is False
        assert job.description == "React and TypeScript."
        assert job.posted_at == now

    def test_dict_model_validate_bidirectional(self):
        """Verify model_validate handles alias dicts and canonical dicts identically."""
        alias_data = {
            "id": "dict-100",
            "company": "Gamma LLC",
            "title": "Data Engineer",
            "remote": True,
            "url": "https://example.com/jobs/100",
            "description": "SQL and Spark pipeline.",
        }
        job = Job.model_validate(alias_data)
        assert job.external_id == "dict-100"
        assert job.company_name == "Gamma LLC"
        assert job.is_remote is True
        assert job.description_text == "SQL and Spark pipeline."

        # Re-dump and validate round-trip
        dumped = job.model_dump()
        job2 = JobListing.model_validate(dumped)
        assert job2.external_id == "dict-100"
        assert job2.id == "dict-100"
        assert job2.company_name == "Gamma LLC"
        assert job2.company == "Gamma LLC"

    def test_int_id_coercion(self):
        """Verify numeric IDs (e.g. integer 12345 from some ATS) get stringified cleanly."""
        job = Job(
            id=12345,
            company="Delta Co",
            title="DevOps",
            remote=0,
            url="https://example.com/jobs/12345",
            description="Terraform.",
        )
        assert job.external_id == "12345"
        assert job.id == "12345"
        assert job.is_remote is False

    def test_precedence_when_both_canonical_and_alias_provided(self):
        """When both external_id and id are passed, canonical must take precedence or resolve deterministically."""
        job = JobListing(
            external_id="canonical-id",
            id="alias-id",
            company_name="Canonical Co",
            company="Alias Co",
            is_remote=True,
            remote=False,
            description_text="Canonical description",
            description="Alias description",
            title="Architect",
            url="https://example.com/arch",
        )
        # Canonical fields should not be overwritten by aliases
        assert job.external_id == "canonical-id"
        assert job.company_name == "Canonical Co"
        assert job.is_remote is True
        assert job.description_text == "Canonical description"

    def test_unique_key_consistency(self):
        """Unique key generation must produce identical output regardless of instantiation style."""
        job1 = JobListing(
            external_id="k-1",
            company_name="Mega Corp",
            title="Engineer",
            url="https://example.com/1",
        )
        job2 = Job(
            id="k-1",
            company="Mega Corp",
            title="Engineer",
            url="https://example.com/1",
        )
        assert job1.get_unique_key() == job2.get_unique_key()
        assert job1.get_unique_key() == "custom:mega_corp:k-1"

    def test_string_boolean_remote_alias(self):
        """
        Adversarial test: remote='false' string representation.
        Pydantic parses is_remote='false' as False.
        Does remote='false' alias also evaluate to False, or does bool('false') mistakenly produce True?
        """
        job = Job(
            id="bool-1",
            company="Test",
            title="Developer",
            url="https://example.com",
            remote="false",
        )
        # In python, bool("false") is True! If _normalize_input_aliases does bool(d["remote"]), this fails!
        assert job.is_remote is False, f"Expected is_remote to be False for remote='false', but got {job.is_remote}"



# ============================================================================
# 2. FALLBACK SCRAPER ON DIRTY HTML & MALFORMED JSON-LD
# ============================================================================

class TestFallbackScraperDirtyHtml:
    """Stress test FallbackScraper against malformed HTML, invalid JSON-LD, and non-job schemas."""

    @pytest.mark.asyncio
    async def test_multiple_json_ld_with_broken_json_and_non_job_types(self):
        """
        HTML containing:
        - 1 broken JSON script
        - 1 valid JSON Organization script
        - 1 valid JSON WebSite script
        - 1 valid JSON JobPosting script
        - 1 empty script tag
        """
        dirty_html = """
        <!DOCTYPE html>
        <html>
        <head>
            <!-- 1. Broken JSON -->
            <script type="application/ld+json">
                { "name": "Broken", "unclosed": 
            </script>
            <!-- 2. Non-JobPosting: Organization -->
            <script type="application/ld+json">
                {
                    "@context": "https://schema.org",
                    "@type": "Organization",
                    "name": "Global Corp",
                    "url": "https://globalcorp.com"
                }
            </script>
            <!-- 3. Empty script -->
            <script type="application/ld+json"></script>
            <!-- 4. Non-JobPosting: WebSite -->
            <script type="application/ld+json">
                {
                    "@context": "https://schema.org",
                    "@type": "WebSite",
                    "name": "Global Corp Careers",
                    "url": "https://globalcorp.com/careers"
                }
            </script>
            <!-- 5. Valid JobPosting -->
            <script type="application/ld+json">
                {
                    "@context": "https://schema.org",
                    "@type": "JobPosting",
                    "title": "Lead Security Engineer",
                    "identifier": {
                        "@type": "PropertyValue",
                        "value": "SEC-909"
                    },
                    "jobLocation": {
                        "@type": "Place",
                        "address": {
                            "addressLocality": "Austin",
                            "addressRegion": "TX",
                            "addressCountry": "US"
                        }
                    },
                    "jobLocationType": "TELECOMMUTE",
                    "url": "/careers/sec-909",
                    "description": "<p>Protect infrastructure. &amp; audit cloud.</p>"
                }
            </script>
        </head>
        <body>
            <h1>Careers at Global Corp</h1>
        </body>
        </html>
        """
        scraper = FallbackScraper()
        soup = BeautifulSoup(dirty_html, "html.parser")
        jobs = scraper._extract_json_ld(soup, "https://globalcorp.com/careers", "Global Corp")

        assert len(jobs) == 1
        assert jobs[0].title == "Lead Security Engineer"
        assert jobs[0].external_id == "SEC-909"
        assert jobs[0].is_remote is True
        assert "Austin, TX, US" in jobs[0].location
        assert "careers/sec-909" in jobs[0].url

    @pytest.mark.asyncio
    async def test_json_ld_graph_with_mixed_types(self):
        """JSON-LD with @graph array containing BreadcrumbList, WebPage, and multiple JobPostings."""
        graph_html = """
        <script type="application/ld+json">
        {
            "@context": "https://schema.org",
            "@graph": [
                {
                    "@type": "BreadcrumbList",
                    "itemListElement": []
                },
                {
                    "@type": "JobPosting",
                    "title": "Platform Engineer",
                    "identifier": "PLT-101",
                    "description": "Kubernetes platform work."
                },
                {
                    "@type": "WebPage",
                    "name": "Careers"
                },
                {
                    "@type": "JobPosting",
                    "title": "Site Reliability Engineer",
                    "identifier": "SRE-202",
                    "jobLocationType": "TELECOMMUTE"
                }
            ]
        }
        </script>
        """
        scraper = FallbackScraper()
        soup = BeautifulSoup(graph_html, "html.parser")
        jobs = scraper._extract_json_ld(soup, "https://example.com/careers", "Example")

        assert len(jobs) == 2
        titles = {j.title for j in jobs}
        assert "Platform Engineer" in titles
        assert "Site Reliability Engineer" in titles

    @pytest.mark.asyncio
    async def test_json_ld_array_with_non_dict_and_non_job_elements(self):
        """
        Adversarial test: JSON root is a list containing non-JobPosting dicts, strings, ints,
        and one valid JobPosting.
        """
        adversarial_json_html = """
        <script type="application/ld+json">
        [
            {"@type": "Organization", "name": "Root Org"},
            {"@type": "JobPosting", "title": "Data Scientist", "identifier": "DS-55"},
            {"@type": "Article", "title": "Why Work Here"}
        ]
        </script>
        """
        scraper = FallbackScraper()
        soup = BeautifulSoup(adversarial_json_html, "html.parser")
        jobs = scraper._extract_json_ld(soup, "https://example.com/careers", "Example")

        # Only JobPosting items should be extracted. Non-job items (Article, Organization) must not become jobs.
        job_titles = [j.title for j in jobs]
        assert "Data Scientist" in job_titles
        # Check if Article was mistakenly extracted
        assert "Why Work Here" not in job_titles, "Article was erroneously extracted as a JobListing"

    @pytest.mark.asyncio
    async def test_json_ld_scalar_and_malformed_structures(self):
        """
        Adversarial test: script tags returning scalars or primitive lists like [1, 2, 3] or "hello".
        Should not crash with unhandled AttributeError or TypeError.
        """
        html_payload = """
        <script type="application/ld+json">[1, 2, "unexpected", null]</script>
        <script type="application/ld+json">"raw string instead of json object"</script>
        <script type="application/ld+json">12345</script>
        <script type="application/ld+json">null</script>
        <script type="application/ld+json">
            {"@type": "JobPosting", "title": "Embedded Engineer", "identifier": "EMB-1"}
        </script>
        """
        scraper = FallbackScraper()
        soup = BeautifulSoup(html_payload, "html.parser")
        # Must not raise unhandled exception
        jobs = scraper._extract_json_ld(soup, "https://example.com", "Example")
        assert len(jobs) == 1
        assert jobs[0].title == "Embedded Engineer"

    @pytest.mark.asyncio
    async def test_json_ld_missing_or_null_fields(self):
        """
        JobPosting where optional fields are explicitly None / null / missing.
        """
        html_payload = """
        <script type="application/ld+json">
        {
            "@type": "JobPosting",
            "title": "Systems Specialist",
            "description": null,
            "jobLocation": null,
            "identifier": null,
            "datePosted": null,
            "applicantLocationRequirements": null
        }
        </script>
        """
        scraper = FallbackScraper()
        soup = BeautifulSoup(html_payload, "html.parser")
        jobs = scraper._extract_json_ld(soup, "https://example.com/careers", "Example")
        assert len(jobs) == 1
        assert jobs[0].title == "Systems Specialist"
        assert jobs[0].description_text == ""
        assert jobs[0].location == ""
        assert jobs[0].published_at is None

    @pytest.mark.asyncio
    async def test_json_ld_title_is_none_or_non_string(self):
        """
        Adversarial test: 'title' key explicitly present with value null or int in JSON-LD.
        e.g. {"@type": "JobPosting", "title": null}
        Code must not crash on item.get('title', '').strip()!
        """
        html_payload = """
        <script type="application/ld+json">
        {
            "@type": "JobPosting",
            "title": null,
            "identifier": "NULL-TITLE"
        }
        </script>
        <script type="application/ld+json">
        {
            "@type": "JobPosting",
            "title": 404,
            "identifier": "INT-TITLE"
        }
        </script>
        """
        scraper = FallbackScraper()
        soup = BeautifulSoup(html_payload, "html.parser")
        # Should not crash with AttributeError: 'NoneType' object has no attribute 'strip'
        jobs = scraper._extract_json_ld(soup, "https://example.com", "Example")
        # Since titles are empty/invalid, they should be skipped gracefully
        assert len(jobs) == 0

    @pytest.mark.asyncio
    async def test_json_ld_type_as_list_or_schema_url(self):
        """
        Schema.org permits @type to be a list, e.g. ["JobPosting", "Thing"]
        or a fully-qualified URI, e.g. "https://schema.org/JobPosting".
        """
        html_payload = """
        <script type="application/ld+json">
        {
            "@context": "https://schema.org",
            "@type": ["JobPosting", "Thing"],
            "title": "Cloud Architect",
            "identifier": "CLOUD-1"
        }
        </script>
        <script type="application/ld+json">
        {
            "@context": "https://schema.org",
            "@type": "https://schema.org/JobPosting",
            "title": "Security Analyst",
            "identifier": "SEC-1"
        }
        </script>
        """
        scraper = FallbackScraper()
        soup = BeautifulSoup(html_payload, "html.parser")
        jobs = scraper._extract_json_ld(soup, "https://example.com", "Example")
        extracted_titles = [j.title for j in jobs]
        assert "Cloud Architect" in extracted_titles
        assert "Security Analyst" in extracted_titles



# ============================================================================
# 3. LEVER PAGINATION TERMINATION CONDITIONS
# ============================================================================

class TestLeverPaginationTermination:
    """Stress test Lever pagination termination conditions."""

    @pytest.mark.asyncio
    async def test_lever_empty_array_terminates_immediately(self):
        """First page returns [] -> terminates with 0 jobs and exactly 1 request."""
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(200, json=[])

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            adapter = LeverAdapter(client=client)
            jobs = await adapter.fetch_jobs("testcompany")

            assert len(jobs) == 0
            assert call_count == 1

    @pytest.mark.asyncio
    async def test_lever_single_item_terminates_immediately(self):
        """First page returns 1 item (< limit of 100) -> terminates with 1 job in 1 request."""
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(
                200,
                json=[
                    {
                        "id": "lever-single-1",
                        "text": "Lead Architect",
                        "hostedUrl": "https://jobs.lever.co/testcompany/lever-single-1",
                        "categories": {"location": "Remote"},
                    }
                ],
            )

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            adapter = LeverAdapter(client=client)
            jobs = await adapter.fetch_jobs("testcompany")

            assert len(jobs) == 1
            assert jobs[0].external_id == "lever-single-1"
            assert jobs[0].title == "Lead Architect"
            assert call_count == 1

    @pytest.mark.asyncio
    async def test_lever_less_than_limit_terminates_immediately(self):
        """First page returns 42 items (< limit of 100) -> terminates with 42 jobs in 1 request."""
        call_count = 0
        items_payload = [
            {
                "id": f"job-{i}",
                "text": f"Software Engineer {i}",
                "hostedUrl": f"https://jobs.lever.co/testcompany/job-{i}",
            }
            for i in range(42)
        ]

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(200, json=items_payload)

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            adapter = LeverAdapter(client=client)
            jobs = await adapter.fetch_jobs("testcompany")

            assert len(jobs) == 42
            assert call_count == 1

    @pytest.mark.asyncio
    async def test_lever_multi_page_termination(self):
        """
        Page 1: exactly 100 items (limit reached).
        Page 2: exactly 25 items (< limit).
        Total jobs = 125, total requests = 2.
        """
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            skip = int(request.url.params.get("skip", 0))
            if skip == 0:
                page_items = [
                    {"id": f"p1-job-{i}", "text": f"Title P1 {i}"}
                    for i in range(100)
                ]
                return httpx.Response(200, json=page_items)
            elif skip == 100:
                page_items = [
                    {"id": f"p2-job-{i}", "text": f"Title P2 {i}"}
                    for i in range(25)
                ]
                return httpx.Response(200, json=page_items)
            return httpx.Response(200, json=[])

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            adapter = LeverAdapter(client=client)
            jobs = await adapter.fetch_jobs("testcompany")

            assert len(jobs) == 125
            assert call_count == 2
            assert jobs[0].external_id == "p1-job-0"
            assert jobs[124].external_id == "p2-job-24"

    @pytest.mark.asyncio
    async def test_lever_page_with_non_dict_or_unexpected_response(self):
        """API returns non-list response (e.g. error JSON dictionary or 404)."""
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(200, json={"message": "ok", "items": []})

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            adapter = LeverAdapter(client=client)
            jobs = await adapter.fetch_jobs("testcompany")

            assert len(jobs) == 0
            assert call_count == 1

    @pytest.mark.asyncio
    async def test_lever_items_with_null_text_or_non_dict(self):
        """
        Adversarial test: Lever items array contains an item with text=null or a non-dict entry.
        """
        payload = [
            {"id": "lev-1", "text": "Valid Title"},
            {"id": "lev-2", "text": None},  # Null text
            None,  # Null entry in list
        ]

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=payload)

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            adapter = LeverAdapter(client=client)
            # Check whether it crashes or gracefully filters
            jobs = await adapter.fetch_jobs("testcompany")
            assert len(jobs) >= 1

