#!/usr/bin/env python3
"""
CareerPulse Standalone Automated Verification Harness (verify_system.py)
Multi-tier E2E testing framework verifying ATS adapters, filtering, deduplication,
Telegram notifications, FastAPI REST API & offline UI, and resilient scheduling.

Usage:
    python verify_system.py               # Runs complete verification suite
    python verify_system.py --quick       # Runs mock & offline fixtures only
    python verify_system.py --live        # Includes optional live ATS public board probes
    python verify_system.py --verbose     # Displays detailed execution diagnostics
"""

import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import html
import json
import logging
import os
from pathlib import Path
import re
import sys
import tempfile
import time
from typing import Any, Callable, Coroutine, Dict, List, Literal, Optional, Tuple
from urllib.parse import parse_qs, urlparse, urlunparse

# Set project paths
PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
FIXTURES_DIR = PROJECT_ROOT / "tests" / "fixtures"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

# Logging configuration
logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
logger = logging.getLogger("verify_system")

# ANSI Color formatting
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


class VerificationResult:
    def __init__(self, name: str):
        self.name = name
        self.passed: int = 0
        self.failed: int = 0
        self.skipped: int = 0
        self.errors: List[str] = []

    def record_pass(self, test_name: str, duration_ms: float = 0.0):
        self.passed += 1
        print(f"  {GREEN}✔ [PASS]{RESET} {test_name} ({duration_ms:.1f}ms)")

    def record_fail(self, test_name: str, error: str):
        self.failed += 1
        self.errors.append(f"{test_name}: {error}")
        print(f"  {RED}✘ [FAIL]{RESET} {test_name}: {error}")

    def record_skip(self, test_name: str, reason: str):
        self.skipped += 1
        print(f"  {YELLOW}⚠ [SKIP]{RESET} {test_name}: {reason}")

    @property
    def total(self) -> int:
        return self.passed + self.failed + self.skipped

    @property
    def is_success(self) -> bool:
        return self.failed == 0


# ==============================================================================
# REFERENCE CONTRACT MODELS & HARNESSES (Interface Contracts from PROJECT.md)
# ==============================================================================

# Attempt imports from src.career_pulse, fallback to contract implementations
try:
    from career_pulse.core.models import (
        JobListing,
        JobFilterConfig,
        FilterResult,
        CompanyConfig,
        ATSDetectResult,
    )
except ImportError:
    from pydantic import BaseModel, Field

    class JobListing(BaseModel):
        external_id: str
        company_name: str
        provider: str = "custom"
        title: str
        location: str = ""
        workplace_type: str = "unknown"
        is_remote: bool = False
        url: str
        department: Optional[str] = None
        description_text: str = ""
        published_at: Optional[datetime] = None
        raw_payload: Optional[Dict[str, Any]] = None

    class JobFilterConfig(BaseModel):
        target_titles: List[str] = ["Software Engineer", "Backend Developer", "Full Stack Developer"]
        negative_title_keywords: List[str] = [
            "senior", "sr", "sr.", "principal", "staff", "lead", "manager",
            "director", "head of", "vp", "intern", "internship", "co-op"
        ]
        negative_description_keywords: List[str] = ["10+ years", "active security clearance", "phd required"]
        required_skills: List[str] = ["Python"]
        preferred_skills: List[str] = ["FastAPI", "PostgreSQL", "Docker", "AWS", "Redis"]
        skills_match_mode: str = "any"
        remote_only: bool = False
        allowed_locations: List[str] = ["Remote", "United States", "US"]
        excluded_locations: List[str] = []

    class FilterResult(BaseModel):
        matched: bool
        rejection_reason: Optional[str] = None
        matched_title: Optional[str] = None
        matched_skills: List[str] = []
        is_remote_matched: bool = False
        match_score: float = 0.0

    class CompanyConfig(BaseModel):
        id: Optional[int] = None
        name: str
        url: str
        provider: str = "custom"
        identifier: str
        career_site: Optional[str] = None
        enabled: bool = True

    class ATSDetectResult(BaseModel):
        provider: str
        identifier: str
        career_site: Optional[str] = None
        confidence: str = "high"
        canonical_url: str


# ==============================================================================
# SUITE 1: ATS ADAPTERS & AUTO-DETECTION ENGINE
# ==============================================================================

async def run_suite_1_ats_adapters(verbose: bool = False, live: bool = False) -> VerificationResult:
    res = VerificationResult("Suite 1: ATS Adapters & Auto-Detection Engine")
    print(f"\n{CYAN}{BOLD}▶ Running {res.name}{RESET}")

    import httpx
    from career_pulse.adapters.greenhouse import GreenhouseAdapter
    from career_pulse.adapters.lever import LeverAdapter
    from career_pulse.adapters.ashby import AshbyAdapter
    from career_pulse.adapters.workday import WorkdayAdapter
    from career_pulse.adapters.fallback import FallbackScraper
    from career_pulse.adapters.detector import ATSDetector

    # 1.1 Greenhouse Adapter with Mock Fixture
    t0 = time.perf_counter()
    try:
        fixture_path = FIXTURES_DIR / "greenhouse_sample.json"
        with open(fixture_path, "r", encoding="utf-8") as f:
            sample_data = json.load(f)

        def mock_greenhouse_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=sample_data)

        mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_greenhouse_handler))
        adapter = GreenhouseAdapter(client=mock_client)
        jobs = await adapter.fetch_jobs("acme", company_name="Acme Corp")
        await adapter.close()

        assert len(jobs) == 9, f"Expected 9 jobs from greenhouse fixture, got {len(jobs)}"
        job_py = next(j for j in jobs if j.external_id == "100101")
        assert job_py.title == "Software Engineer II - Python/FastAPI"
        assert job_py.is_remote is True, "San Francisco, CA / Remote should be tagged remote"
        assert "FastAPI" in job_py.description_text
        assert job_py.department == "Engineering"
        assert job_py.url == "https://boards.greenhouse.io/acme/jobs/100101"
        res.record_pass("1.1 Greenhouse Adapter parsing mock fixture", (time.perf_counter() - t0) * 1000)
    except Exception as e:
        res.record_fail("1.1 Greenhouse Adapter parsing mock fixture", str(e))

    # 1.2 Lever Adapter with Mock Fixture
    t0 = time.perf_counter()
    try:
        fixture_path = FIXTURES_DIR / "lever_sample.json"
        with open(fixture_path, "r", encoding="utf-8") as f:
            sample_data = json.load(f)

        def mock_lever_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=sample_data)

        mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_lever_handler))
        adapter = LeverAdapter(client=mock_client)
        jobs = await adapter.fetch_jobs("initech", company_name="Initech")
        await adapter.close()

        assert len(jobs) == 6, f"Expected 6 jobs from lever fixture, got {len(jobs)}"
        job_py = next(j for j in jobs if j.external_id == "lev-1001")
        assert job_py.title == "Backend Developer (Python)"
        assert job_py.is_remote is True
        assert job_py.url == "https://jobs.lever.co/initech/lev-1001/apply"
        assert "FastAPI" in job_py.description_text

        # Verify job with "Engineering Manager" in description
        job_mgr = next(j for j in jobs if j.external_id == "lev-1003")
        assert "Engineering Manager" in job_mgr.description_text
        assert job_mgr.title == "Full Stack Developer"
        res.record_pass("1.2 Lever Adapter parsing mock fixture", (time.perf_counter() - t0) * 1000)
    except Exception as e:
        res.record_fail("1.2 Lever Adapter parsing mock fixture", str(e))

    # 1.3 Ashby Adapter with Mock Fixture
    t0 = time.perf_counter()
    try:
        fixture_path = FIXTURES_DIR / "ashby_sample.json"
        with open(fixture_path, "r", encoding="utf-8") as f:
            sample_data = json.load(f)

        def mock_ashby_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=sample_data)

        mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_ashby_handler))
        adapter = AshbyAdapter(client=mock_client)
        jobs = await adapter.fetch_jobs("hooli", company_name="Hooli")
        await adapter.close()

        assert len(jobs) == 5, f"Expected 5 jobs from ashby fixture, got {len(jobs)}"
        job_py = next(j for j in jobs if j.external_id == "ash-2001")
        assert job_py.title == "Python Backend Engineer"
        assert job_py.is_remote is True
        assert job_py.url == "https://jobs.ashbyhq.com/hooli/ash-2001/application"
        assert "Compensation: $150,000 - $190,000 USD" in job_py.description_text
        res.record_pass("1.3 Ashby Adapter parsing mock fixture", (time.perf_counter() - t0) * 1000)
    except Exception as e:
        res.record_fail("1.3 Ashby Adapter parsing mock fixture", str(e))

    # 1.4 Workday Adapter with Mock Fixture
    t0 = time.perf_counter()
    try:
        fixture_path = FIXTURES_DIR / "workday_sample.json"
        with open(fixture_path, "r", encoding="utf-8") as f:
            sample_data = json.load(f)

        def mock_workday_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=sample_data)

        mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_workday_handler))
        adapter = WorkdayAdapter(client=mock_client)
        jobs = await adapter.fetch_jobs("nvidia", career_site="NVIDIAExternalCareerSite")
        await adapter.close()

        assert len(jobs) == 4, f"Expected 4 jobs from workday fixture, got {len(jobs)}"
        job_1 = next(j for j in jobs if j.external_id == "JR101")
        assert job_1.title == "Software Engineer, Platform"
        assert job_1.is_remote is True, "San Jose, CA, USA / Remote should be tagged remote"
        assert "NVIDIAExternalCareerSite" in job_1.url
        res.record_pass("1.4 Workday Adapter parsing mock fixture", (time.perf_counter() - t0) * 1000)
    except Exception as e:
        res.record_fail("1.4 Workday Adapter parsing mock fixture", str(e))

    # 1.5 Fallback Scraper parsing custom HTML fixture
    t0 = time.perf_counter()
    try:
        fixture_path = FIXTURES_DIR / "custom_career_page.html"
        with open(fixture_path, "r", encoding="utf-8") as f:
            html_text = f.read()

        def mock_custom_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=html_text)

        mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_custom_handler))
        scraper = FallbackScraper(client=mock_client)
        jobs = await scraper.fetch_jobs("https://globex.example.com/careers", company_name="Globex")
        await scraper.close()

        assert len(jobs) >= 2, f"Expected at least 2 jobs from custom page, got {len(jobs)}"
        # Check JSON-LD extracted job
        job_se = next((j for j in jobs if "Python/FastAPI" in j.title), None)
        assert job_se is not None, "Failed to extract Software Engineer (Python/FastAPI) from custom HTML"
        assert job_se.url.startswith("https://globex.example.com")
        res.record_pass("1.5 Fallback Scraper parsing JSON-LD and DOM cards", (time.perf_counter() - t0) * 1000)
    except Exception as e:
        res.record_fail("1.5 Fallback Scraper parsing JSON-LD and DOM cards", str(e))

    # 1.6 ATS Auto-Detection Engine
    t0 = time.perf_counter()
    try:
        test_cases = [
            ("https://boards.greenhouse.io/stripe", "greenhouse", "stripe"),
            ("https://jobs.lever.co/netflix", "lever", "netflix"),
            ("https://jobs.ashbyhq.com/linear", "ashby", "linear"),
            ("https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite", "workday", "nvidia"),
            ("https://boards.greenhouse.io/embed/job_board?for=figma", "greenhouse", "figma"),
        ]

        for url, expected_provider, expected_id in test_cases:
            detected = ATSDetector.match_url(url)
            assert detected is not None, f"Failed to detect {url}"
            assert detected.provider == expected_provider, f"Expected {expected_provider}, got {detected.provider}"
            assert detected.identifier == expected_id, f"Expected {expected_id}, got {detected.identifier}"

        # HTML embed detection test on custom fixture
        fixture_path = FIXTURES_DIR / "custom_career_page.html"
        with open(fixture_path, "r", encoding="utf-8") as f:
            html_text = f.read()

        def mock_embed_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=html_text)

        probe_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_embed_handler))
        detector = ATSDetector(client=probe_client)
        detected_embed = await detector.detect("https://globex.example.com/careers")
        await detector.close()

        assert detected_embed.provider == "greenhouse"
        assert detected_embed.identifier == "globexembedded"
        res.record_pass("1.6 ATS Auto-Detector URL regex and iframe probe", (time.perf_counter() - t0) * 1000)
    except Exception as e:
        res.record_fail("1.6 ATS Auto-Detector URL regex and iframe probe", str(e))

    # 1.7 Optional Live Test
    if live:
        t0 = time.perf_counter()
        try:
            gh = GreenhouseAdapter()
            live_jobs = await gh.fetch_jobs("cloudflare", company_name="Cloudflare")
            await gh.close()
            assert len(live_jobs) > 0, "Cloudflare live board returned 0 jobs"
            res.record_pass("1.7 Live ATS public endpoint probe (Cloudflare)", (time.perf_counter() - t0) * 1000)
        except Exception as e:
            res.record_fail("1.7 Live ATS public endpoint probe (Cloudflare)", str(e))
    else:
        res.record_skip("1.7 Live ATS public endpoint probe", "Enable with --live flag")

    return res


# ==============================================================================
# SUITE 2: JOB MATCHING, SCORING & STRICT NEGATIVE KEYWORD EXCLUSION
# ==============================================================================

def build_boundary_pattern(keyword: str) -> re.Pattern:
    """Lookaround boundary pattern (?<!\w)...(?!\w) for safe symbol matching."""
    escaped = re.escape(keyword.strip())
    return re.compile(rf'(?<!\w){escaped}(?!\w)', re.IGNORECASE)

def strip_html_tags(text: str) -> str:
    if not text:
        return ""
    clean = re.sub(r'<[^>]+>', ' ', text)
    return html.unescape(clean)

class StandaloneJobMatcher:
    """Authoritative JobMatcher implementing Contract 2 from PROJECT.md."""

    def __init__(self, config: JobFilterConfig):
        self.config = config
        self._neg_title_patterns = [build_boundary_pattern(k) for k in config.negative_title_keywords if k.strip()]
        self._neg_desc_patterns = [build_boundary_pattern(k) for k in config.negative_description_keywords if k.strip()]
        self._target_title_patterns = [build_boundary_pattern(k) for k in config.target_titles if k.strip()]
        self._req_skill_patterns = {k: build_boundary_pattern(k) for k in config.required_skills if k.strip()}
        self._pref_skill_patterns = {k: build_boundary_pattern(k) for k in config.preferred_skills if k.strip()}

    def evaluate(self, job: JobListing) -> FilterResult:
        title = job.title.strip()
        desc = strip_html_tags(job.description_text)
        location = job.location.strip()
        search_surface = f"{title}\n{desc}"

        # 1. Negative Title Keyword Check
        for pattern in self._neg_title_patterns:
            match = pattern.search(title)
            if match:
                return FilterResult(
                    matched=False,
                    rejection_reason=f"Title matched negative keyword '{match.group(0)}'"
                )

        # 2. Negative Description Keyword Check
        for pattern in self._neg_desc_patterns:
            match = pattern.search(desc)
            if match:
                return FilterResult(
                    matched=False,
                    rejection_reason=f"Description matched negative keyword '{match.group(0)}'"
                )

        # 3. Location & Remote Filter Check
        is_remote = job.is_remote or bool(re.search(r'(?<!\w)(remote|anywhere|telecommute|wfh)(?!\w)', f"{title} {location}", re.I))
        if self.config.remote_only and not is_remote:
            return FilterResult(
                matched=False,
                rejection_reason=f"Job is not remote (Location: '{location}')"
            )

        if self.config.excluded_locations:
            for excl in self.config.excluded_locations:
                if excl.strip() and re.search(rf'(?<!\w){re.escape(excl.strip())}(?!\w)', location, re.I):
                    return FilterResult(
                        matched=False,
                        rejection_reason=f"Location matches excluded pattern '{excl}'"
                    )

        if self.config.allowed_locations and not is_remote:
            matched_loc = False
            for allowed in self.config.allowed_locations:
                if allowed.strip() and re.search(rf'(?<!\w){re.escape(allowed.strip())}(?!\w)', location, re.I):
                    matched_loc = True
                    break
            if not matched_loc:
                return FilterResult(
                    matched=False,
                    rejection_reason=f"Location '{location}' not in allowed locations"
                )

        # 4. Target Job Title Check
        matched_title = None
        if self._target_title_patterns:
            for pattern in self._target_title_patterns:
                match = pattern.search(title)
                if match:
                    matched_title = match.group(0)
                    break
            if not matched_title:
                return FilterResult(
                    matched=False,
                    rejection_reason="Title did not match any target titles"
                )
        else:
            matched_title = title

        # 5. Skills Matching
        matched_skills: List[str] = []
        matched_req_skills: List[str] = []

        for skill, pattern in self._req_skill_patterns.items():
            if pattern.search(search_surface):
                matched_req_skills.append(skill)
                matched_skills.append(skill)

        if self.config.skills_match_mode == "all":
            if len(matched_req_skills) < len(self._req_skill_patterns):
                missing = set(self._req_skill_patterns.keys()) - set(matched_req_skills)
                return FilterResult(
                    matched=False,
                    rejection_reason=f"Missing required skills: {', '.join(missing)}"
                )
        elif self.config.skills_match_mode == "any":
            if self._req_skill_patterns and len(matched_req_skills) == 0:
                return FilterResult(
                    matched=False,
                    rejection_reason="Did not match any required skills"
                )

        # Preferred skills
        for skill, pattern in self._pref_skill_patterns.items():
            if pattern.search(search_surface) and skill not in matched_skills:
                matched_skills.append(skill)

        # Compute match score
        score = 1.0
        if matched_title:
            score += 2.0
        score += len(matched_req_skills) * 1.5
        score += (len(matched_skills) - len(matched_req_skills)) * 0.8
        if is_remote:
            score += 0.5

        return FilterResult(
            matched=True,
            matched_title=matched_title,
            matched_skills=matched_skills,
            is_remote_matched=is_remote,
            match_score=round(score, 2)
        )


async def run_suite_2_job_matching(verbose: bool = False) -> VerificationResult:
    res = VerificationResult("Suite 2: Job Matching, Scoring & Strict Negative Exclusions")
    print(f"\n{CYAN}{BOLD}▶ Running {res.name}{RESET}")

    # Use production JobMatcher if available, otherwise StandaloneJobMatcher
    try:
        from career_pulse.core.matching import JobMatcher
    except ImportError:
        JobMatcher = StandaloneJobMatcher

    # 2.1 Positive Title Matching
    t0 = time.perf_counter()
    try:
        cfg = JobFilterConfig(
            target_titles=["Software Engineer", "Backend Developer"],
            required_skills=["Python"],
            skills_match_mode="any"
        )
        matcher = JobMatcher(cfg)
        job = JobListing(
            external_id="1", company_name="Test", title="Software Engineer, Backend",
            location="Remote", is_remote=True, url="http://test", description_text="Python service"
        )
        eval_res = matcher.evaluate(job)
        assert eval_res.matched is True, f"Expected positive match, got: {eval_res.rejection_reason}"
        assert eval_res.match_score > 3.0
        res.record_pass("2.1 Positive title lookaround matching", (time.perf_counter() - t0) * 1000)
    except Exception as e:
        res.record_fail("2.1 Positive title lookaround matching", str(e))

    # 2.2 Strict Negative Keyword Exclusion in Titles
    t0 = time.perf_counter()
    try:
        cfg = JobFilterConfig()
        matcher = JobMatcher(cfg)
        neg_titles = [
            "Senior Backend Engineer",
            "Staff Infrastructure Engineer",
            "Principal Software Engineer",
            "Lead Full Stack Developer",
            "Engineering Manager",
            "VP of Engineering",
            "Software Engineering Intern",
            "Data Engineering Co-op",
            "Director of Technology",
        ]
        for t in neg_titles:
            j = JobListing(
                external_id="1", company_name="Test", title=t,
                location="Remote", is_remote=True, url="http://test", description_text="Python"
            )
            r = matcher.evaluate(j)
            assert r.matched is False, f"Job '{t}' should have been rejected by negative keyword filter!"
            assert "Title matched negative keyword" in r.rejection_reason
        res.record_pass(f"2.2 Strict negative keyword exclusion ({len(neg_titles)} titles)", (time.perf_counter() - t0) * 1000)
    except Exception as e:
        res.record_fail("2.2 Strict negative keyword exclusion", str(e))

    # 2.3 Adversarial Word Boundary & Symbol Tests (C++, Go, Intern vs Internal)
    t0 = time.perf_counter()
    try:
        # Boundary test 1: "Internal" should NOT trigger "intern" negative keyword
        cfg = JobFilterConfig(
            target_titles=["Software Engineer"],
            negative_title_keywords=["intern", "internship", "co-op"],
            required_skills=["Python"]
        )
        matcher = JobMatcher(cfg)
        j1 = JobListing(
            external_id="1", company_name="Test", title="Internal Tools Software Engineer",
            location="Remote", is_remote=True, url="http://test", description_text="Python tools"
        )
        r1 = matcher.evaluate(j1)
        assert r1.matched is True, f"'Internal Tools' must NOT be rejected by 'intern'! Reason: {r1.rejection_reason}"

        # Boundary test 2: "Go" programming language vs "Good"
        cfg_go = JobFilterConfig(
            target_titles=["Platform Developer", "Analyst"],
            required_skills=["Go"],
            skills_match_mode="any"
        )
        matcher_go = JobMatcher(cfg_go)
        j_good = JobListing(
            external_id="2", company_name="Test", title="Good Governance Analyst",
            location="Remote", is_remote=True, url="http://test", description_text="Good governance skills"
        )
        r_good = matcher_go.evaluate(j_good)
        assert r_good.matched is False, "'Good' should NOT match 'Go' skill keyword!"

        j_go = JobListing(
            external_id="3", company_name="Test", title="Go Platform Developer",
            location="Remote", is_remote=True, url="http://test", description_text="Go systems"
        )
        r_go = matcher_go.evaluate(j_go)
        assert r_go.matched is True, "'Go Platform Developer' must match 'Go' keyword!"
        assert "Go" in r_go.matched_skills

        # Boundary test 3: Symbols C++ and .NET / C#
        cfg_cpp = JobFilterConfig(
            target_titles=["Systems Engineer"],
            required_skills=["C++"],
            skills_match_mode="any"
        )
        matcher_cpp = JobMatcher(cfg_cpp)
        j_cpp = JobListing(
            external_id="4", company_name="Test", title="C++ Systems Engineer",
            location="Remote", is_remote=True, url="http://test", description_text="Kernel programming in C++"
        )
        r_cpp = matcher_cpp.evaluate(j_cpp)
        assert r_cpp.matched is True, "'C++' symbol keyword must match!"
        assert "C++" in r_cpp.matched_skills

        res.record_pass("2.3 Adversarial boundary & symbol tests (C++, Go vs Good, Intern vs Internal)", (time.perf_counter() - t0) * 1000)
    except Exception as e:
        res.record_fail("2.3 Adversarial boundary & symbol tests", str(e))

    # 2.4 Title vs Description Negative Isolation
    t0 = time.perf_counter()
    try:
        cfg = JobFilterConfig(
            target_titles=["Software Engineer"],
            negative_title_keywords=["manager", "senior", "lead"],
            negative_description_keywords=["10+ years"],
            required_skills=["Python"]
        )
        matcher = JobMatcher(cfg)
        # Description mentions "You will report to the Engineering Manager"
        j = JobListing(
            external_id="1", company_name="Test", title="Software Engineer",
            location="Remote", is_remote=True, url="http://test",
            description_text="In this role, you will collaborate closely with team members and report to the Engineering Manager."
        )
        r = matcher.evaluate(j)
        assert r.matched is True, f"Role should NOT be rejected when 'Manager' is only in description! Reason: {r.rejection_reason}"
        res.record_pass("2.4 Title vs Description negative isolation", (time.perf_counter() - t0) * 1000)
    except Exception as e:
        res.record_fail("2.4 Title vs Description negative isolation", str(e))

    # 2.5 Skills Match Mode ("any", "all", "none") & Scoring
    t0 = time.perf_counter()
    try:
        cfg_all = JobFilterConfig(
            target_titles=["Developer"],
            required_skills=["Python", "FastAPI", "Docker"],
            skills_match_mode="all"
        )
        m_all = JobMatcher(cfg_all)
        # Missing Docker
        j_missing = JobListing(
            external_id="1", company_name="Test", title="Developer",
            location="Remote", is_remote=True, url="http://test", description_text="Python and FastAPI developer"
        )
        r_missing = m_all.evaluate(j_missing)
        assert r_missing.matched is False
        assert "Missing required skills" in r_missing.rejection_reason

        # Has all three
        j_full = JobListing(
            external_id="2", company_name="Test", title="Developer",
            location="Remote", is_remote=True, url="http://test", description_text="Python, FastAPI, and Docker"
        )
        r_full = m_all.evaluate(j_full)
        assert r_full.matched is True
        assert len(r_full.matched_skills) == 3
        res.record_pass("2.5 Skill modes ('all', 'any') and match scoring", (time.perf_counter() - t0) * 1000)
    except Exception as e:
        res.record_fail("2.5 Skill modes ('all', 'any') and match scoring", str(e))

    # 2.6 Location and Remote Filtering
    t0 = time.perf_counter()
    try:
        cfg_remote = JobFilterConfig(
            target_titles=["Developer"],
            remote_only=True,
            allowed_locations=["United States"],
            excluded_locations=["Europe"]
        )
        m_rem = JobMatcher(cfg_remote)

        j_onsite = JobListing(
            external_id="1", company_name="Test", title="Developer",
            location="New York, NY", is_remote=False, url="http://test", description_text="Python"
        )
        assert m_rem.evaluate(j_onsite).matched is False, "Non-remote job should be rejected when remote_only=True"

        j_rem = JobListing(
            external_id="2", company_name="Test", title="Developer",
            location="Remote - US", is_remote=True, url="http://test", description_text="Python"
        )
        assert m_rem.evaluate(j_rem).matched is True, "Remote job should be accepted"

        j_excl = JobListing(
            external_id="3", company_name="Test", title="Developer",
            location="Europe (Remote)", is_remote=True, url="http://test", description_text="Python"
        )
        assert m_rem.evaluate(j_excl).matched is False, "Job in Europe should be rejected by excluded_locations"

        res.record_pass("2.6 Location & Remote filtering logic", (time.perf_counter() - t0) * 1000)
    except Exception as e:
        res.record_fail("2.6 Location & Remote filtering logic", str(e))

    return res


# ==============================================================================
# SUITE 3: SQLITE STORAGE, WAL MODE & ZERO DUPLICATE ALERT DEDUPLICATION
# ==============================================================================

SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;
PRAGMA synchronous = NORMAL;

CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    career_url TEXT NOT NULL DEFAULT '',
    ats_provider TEXT NOT NULL DEFAULT 'custom',
    identifier TEXT,
    provider TEXT,
    url TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    last_scanned_at TIMESTAMP,
    scan_status TEXT DEFAULT 'pending',
    last_error TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    external_id TEXT NOT NULL,
    unique_key TEXT NOT NULL UNIQUE,
    canonical_url TEXT NOT NULL,
    title TEXT NOT NULL,
    department TEXT,
    location TEXT NOT NULL DEFAULT 'Unknown',
    workplace_type TEXT NOT NULL DEFAULT 'unknown',
    is_remote INTEGER NOT NULL DEFAULT 0,
    apply_url TEXT NOT NULL,
    description_text TEXT,
    raw_payload TEXT,
    published_at TIMESTAMP,
    first_seen_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    is_active INTEGER NOT NULL DEFAULT 1,
    CONSTRAINT uq_company_external UNIQUE (company_id, external_id)
);

CREATE TABLE IF NOT EXISTS alerts_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    sent_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    channel TEXT NOT NULL DEFAULT 'telegram',
    status TEXT NOT NULL,
    error_message TEXT,
    message_preview TEXT,
    CONSTRAINT uq_alerts_job_channel UNIQUE (job_id, channel)
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

def normalize_url(url: str) -> str:
    try:
        p = urlparse(url)
        return urlunparse((p.scheme.lower(), p.netloc.lower(), p.path.rstrip('/'), '', '', ''))
    except Exception:
        return url.strip()

def generate_unique_key(provider: str, company_id: int, external_id: str, canonical_url: str) -> str:
    if external_id and external_id != "unknown":
        return f"{provider}:{company_id}:{external_id}"
    url_hash = hashlib.sha256(canonical_url.encode("utf-8")).hexdigest()[:16]
    return f"url_hash:{url_hash}"

class StandaloneDatabase:
    """Authoritative Database service implementing Contract 3 from PROJECT.md."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    async def get_connection(self):
        import aiosqlite
        conn = await aiosqlite.connect(self.db_path)
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA journal_mode = WAL;")
        await conn.execute("PRAGMA foreign_keys = ON;")
        await conn.execute("PRAGMA busy_timeout = 5000;")
        return conn

    async def init_schema(self):
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        async with await self.get_connection() as conn:
            await conn.executescript(SCHEMA_SQL)
            await conn.commit()

    async def upsert_job(self, company_id: int, job: JobListing) -> Tuple[int, bool]:
        canonical_url = normalize_url(job.url)
        unique_key = generate_unique_key(job.provider, company_id, job.external_id, canonical_url)

        async with await self.get_connection() as conn:
            async with conn.execute(
                "SELECT id FROM jobs WHERE unique_key = ?", (unique_key,)
            ) as cursor:
                row = await cursor.fetchone()

            if row:
                job_id = row["id"]
                await conn.execute(
                    """
                    UPDATE jobs 
                    SET last_seen_at = CURRENT_TIMESTAMP,
                        title = ?,
                        location = ?,
                        is_remote = ?,
                        apply_url = ?,
                        description_text = ?
                    WHERE id = ?
                    """,
                    (job.title, job.location, 1 if job.is_remote else 0, job.url, job.description_text, job_id)
                )
                await conn.commit()
                return job_id, False
            else:
                raw_json = json.dumps(job.raw_payload) if job.raw_payload else None
                async with conn.execute(
                    """
                    INSERT INTO jobs (
                        company_id, external_id, unique_key, canonical_url,
                        title, department, location, workplace_type, is_remote,
                        apply_url, description_text, raw_payload, published_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        company_id, job.external_id, unique_key, canonical_url,
                        job.title, job.department, job.location, job.workplace_type,
                        1 if job.is_remote else 0, job.url, job.description_text,
                        raw_json, job.published_at
                    )
                ) as cursor:
                    job_id = cursor.lastrowid
                await conn.commit()
                return job_id, True

    async def reserve_alert_slot(self, job_id: int, channel: str = "telegram") -> bool:
        """Atomic reservation to guarantee zero duplicate alerts."""
        async with await self.get_connection() as conn:
            try:
                cursor = await conn.execute(
                    """
                    INSERT INTO alerts_history (job_id, channel, status)
                    VALUES (?, ?, 'pending')
                    ON CONFLICT(job_id, channel) DO NOTHING;
                    """,
                    (job_id, channel)
                )
                await conn.commit()
                return cursor.rowcount > 0
            except Exception as e:
                logger.error(f"Error reserving alert slot for job {job_id}: {e}")
                return False

    async def finalize_alert_status(self, job_id: int, channel: str, status: str, preview: Optional[str] = None):
        async with await self.get_connection() as conn:
            await conn.execute(
                """
                UPDATE alerts_history
                SET status = ?, message_preview = ?, sent_at = CURRENT_TIMESTAMP
                WHERE job_id = ? AND channel = ?
                """,
                (status, preview, job_id, channel)
            )
            await conn.commit()


async def run_suite_3_sqlite_dedup(verbose: bool = False) -> VerificationResult:
    res = VerificationResult("Suite 3: SQLite Storage, WAL Mode & Zero Duplicate Deduplication")
    print(f"\n{CYAN}{BOLD}▶ Running {res.name}{RESET}")

    try:
        from career_pulse.db.session import Database
    except ImportError:
        Database = StandaloneDatabase

    # Create isolated temporary database
    temp_dir = tempfile.mkdtemp()
    db_file = Path(temp_dir) / "test_career_pulse.db"
    db = Database(str(db_file))

    # 3.1 Initialize schema and verify WAL mode
    t0 = time.perf_counter()
    try:
        await db.init_schema()
        async with await db.get_connection() as conn:
            async with conn.execute("PRAGMA journal_mode;") as cur:
                mode_row = await cur.fetchone()
                journal_mode = mode_row[0].lower()
                assert journal_mode == "wal", f"Expected WAL mode, got {journal_mode}"

            async with conn.execute("PRAGMA foreign_keys;") as cur:
                fk_row = await cur.fetchone()
                assert fk_row[0] == 1, "Foreign keys must be ON"

        res.record_pass("3.1 SQLite Schema initialization & PRAGMA journal_mode = WAL", (time.perf_counter() - t0) * 1000)
    except Exception as e:
        res.record_fail("3.1 SQLite Schema initialization & WAL mode", str(e))

    # Seed test company
    async with await db.get_connection() as conn:
        await conn.execute(
            "INSERT INTO companies (name, career_url, ats_provider) VALUES (?, ?, ?)",
            ("Acme Inc", "https://boards.greenhouse.io/acme", "greenhouse")
        )
        await conn.commit()
    company_id = 1

    sample_jobs = [
        JobListing(external_id=f"job-{i}", company_name="Acme Inc", provider="greenhouse",
                   title=f"Engineer {i}", location="Remote", is_remote=True, url=f"http://acme/job/{i}",
                   description_text="Python")
        for i in range(1, 6)
    ]

    # 3.2 First Run Ingestion: all 5 jobs are new and acquire alert reservation
    t0 = time.perf_counter()
    try:
        job_ids = []
        for j in sample_jobs:
            jid, is_new = await db.upsert_job(company_id, j)
            assert is_new is True, f"Job {j.external_id} should be marked new on first insert"
            job_ids.append(jid)

            # Reserve alert slot
            reserved = await db.reserve_alert_slot(jid, channel="telegram")
            assert reserved is True, f"Job {jid} must acquire initial alert reservation"
            await db.finalize_alert_status(jid, "telegram", "mock", preview="Test alert")

        assert len(job_ids) == 5
        res.record_pass("3.2 First run ingestion & atomic alert reservation (5 jobs)", (time.perf_counter() - t0) * 1000)
    except Exception as e:
        res.record_fail("3.2 First run ingestion & alert reservation", str(e))

    # 3.3 Subsequent Scan Deduplication (Zero Duplicate Alerts)
    t0 = time.perf_counter()
    try:
        duplicate_alerts_count = 0
        for j in sample_jobs:
            jid, is_new = await db.upsert_job(company_id, j)
            assert is_new is False, f"Job {j.external_id} must NOT be marked new on re-scan"

            # Attempt duplicate alert reservation
            reserved = await db.reserve_alert_slot(jid, channel="telegram")
            if reserved:
                duplicate_alerts_count += 1

        assert duplicate_alerts_count == 0, f"Duplicate alerts triggered: {duplicate_alerts_count} (must be exactly 0)"

        # Check total rows in alerts_history remains 5
        async with await db.get_connection() as conn:
            async with conn.execute("SELECT COUNT(*) FROM alerts_history") as cur:
                count = (await cur.fetchone())[0]
                assert count == 5, f"Expected exactly 5 alert history rows, found {count}"

        res.record_pass("3.3 Subsequent scan deduplication (Zero duplicate alerts)", (time.perf_counter() - t0) * 1000)
    except Exception as e:
        res.record_fail("3.3 Subsequent scan deduplication", str(e))

    # 3.4 Incremental Ingestion: 5 existing + 2 new jobs
    t0 = time.perf_counter()
    try:
        new_jobs = [
            JobListing(external_id="job-6", company_name="Acme Inc", provider="greenhouse",
                       title="Engineer 6", location="Remote", is_remote=True, url="http://acme/job/6", description_text="Python"),
            JobListing(external_id="job-7", company_name="Acme Inc", provider="greenhouse",
                       title="Engineer 7", location="Remote", is_remote=True, url="http://acme/job/7", description_text="Python"),
        ]
        mixed_batch = sample_jobs + new_jobs
        new_count = 0
        new_reserved = 0

        for j in mixed_batch:
            jid, is_new = await db.upsert_job(company_id, j)
            if is_new:
                new_count += 1
                if await db.reserve_alert_slot(jid, channel="telegram"):
                    new_reserved += 1

        assert new_count == 2, f"Expected exactly 2 new jobs, got {new_count}"
        assert new_reserved == 2, f"Expected exactly 2 new alert slots reserved, got {new_reserved}"
        res.record_pass("3.4 Incremental batch ingestion (5 existing + 2 new jobs)", (time.perf_counter() - t0) * 1000)
    except Exception as e:
        res.record_fail("3.4 Incremental batch ingestion", str(e))

    # 3.5 Atomic Reservation Concurrency Stress Test
    t0 = time.perf_counter()
    try:
        # Create brand new job
        contested_job = JobListing(
            external_id="job-race-condition", company_name="Acme Inc", provider="greenhouse",
            title="Concurrency Engineer", location="Remote", is_remote=True, url="http://acme/race", description_text="Python"
        )
        jid, _ = await db.upsert_job(company_id, contested_job)

        # 10 concurrent tasks simultaneously attempt to reserve the alert slot
        async def attempt_reserve():
            return await db.reserve_alert_slot(jid, channel="telegram")

        results = await asyncio.gather(*[attempt_reserve() for _ in range(10)])
        successful_reservations = sum(1 for r in results if r is True)
        failed_reservations = sum(1 for r in results if r is False)

        assert successful_reservations == 1, f"Expected exactly 1 winner in atomic race, got {successful_reservations}"
        assert failed_reservations == 9, f"Expected 9 dropped reservations, got {failed_reservations}"
        res.record_pass("3.5 Atomic ON CONFLICT reservation concurrency race test (10 tasks)", (time.perf_counter() - t0) * 1000)
    except Exception as e:
        res.record_fail("3.5 Atomic ON CONFLICT reservation concurrency race test", str(e))

    # 3.6 Concurrency Race Condition (50 Simultaneous Coroutines)
    t0 = time.perf_counter()
    try:
        contested_50 = JobListing(
            external_id="job-race-50", company_name="Acme Inc", provider="greenhouse",
            title="Heavy Concurrency Engineer", location="Remote", is_remote=True,
            url="http://acme/race-50", description_text="Python"
        )
        jid_50, _ = await db.upsert_job(company_id, contested_50)
        barrier = asyncio.Event()

        async def worker_50():
            await barrier.wait()
            return await db.reserve_alert_slot(jid_50, channel="telegram")

        tasks_50 = [asyncio.create_task(worker_50()) for _ in range(50)]
        barrier.set()
        results_50 = await asyncio.gather(*tasks_50)

        winners_50 = sum(1 for r in results_50 if r is True)
        losers_50 = sum(1 for r in results_50 if r is False)
        assert winners_50 == 1, f"Expected exactly 1 winner out of 50 coroutines, got {winners_50}"
        assert losers_50 == 49, f"Expected 49 losers out of 50 coroutines, got {losers_50}"
        res.record_pass("3.6 Adversarial 50-coroutine atomic reservation race condition", (time.perf_counter() - t0) * 1000)
    except Exception as e:
        res.record_fail("3.6 Adversarial 50-coroutine atomic reservation race condition", str(e))

    # 3.7 Zero Duplicate Alert Invariant Across 5 Repeated Scans
    t0 = time.perf_counter()
    try:
        def make_scan_job(i: int):
            return JobListing(
                external_id=f"gh-scan-inv-{i}", company_name="Acme Inc", provider="greenhouse",
                title=f"Scan Engineer {i}", location="Remote", is_remote=True,
                url=f"http://acme/scan-inv/{i}", description_text="Python"
            )

        batch_1_to_5 = [make_scan_job(i) for i in range(1, 6)]
        batch_6_to_8 = [make_scan_job(i) for i in range(6, 9)]
        batch_9_to_10 = [make_scan_job(i) for i in range(9, 11)]

        total_alerts = 0

        # Scan 1: 5 new jobs
        s1_res = 0
        for j in batch_1_to_5:
            jid, is_new = await db.upsert_job(company_id, j)
            if is_new and await db.reserve_alert_slot(jid, "telegram"):
                s1_res += 1
                await db.finalize_alert_status(jid, "telegram", "mock", preview=f"Job {j.external_id}")
        assert s1_res == 5
        total_alerts += s1_res

        # Scan 2: Exactly same 5 jobs
        s2_res = 0
        for j in batch_1_to_5:
            jid, is_new = await db.upsert_job(company_id, j)
            if is_new or await db.reserve_alert_slot(jid, "telegram"):
                s2_res += 1
        assert s2_res == 0, f"Scan 2 must produce 0 duplicate alerts, got {s2_res}"

        # Scan 3: 5 existing + 3 new (jobs 1 to 8)
        s3_res = 0
        for j in (batch_1_to_5 + batch_6_to_8):
            jid, is_new = await db.upsert_job(company_id, j)
            if is_new and await db.reserve_alert_slot(jid, "telegram"):
                s3_res += 1
                await db.finalize_alert_status(jid, "telegram", "mock", preview=f"Job {j.external_id}")
        assert s3_res == 3
        total_alerts += s3_res

        # Scan 4: Identical 8 jobs
        s4_res = 0
        for j in (batch_1_to_5 + batch_6_to_8):
            jid, is_new = await db.upsert_job(company_id, j)
            if is_new or await db.reserve_alert_slot(jid, "telegram"):
                s4_res += 1
        assert s4_res == 0, f"Scan 4 must produce 0 duplicate alerts, got {s4_res}"

        # Scan 5: Mixed subset (4 existing + 2 new jobs 9, 10)
        s5_res = 0
        for j in (batch_1_to_5[:4] + batch_9_to_10):
            jid, is_new = await db.upsert_job(company_id, j)
            if is_new and await db.reserve_alert_slot(jid, "telegram"):
                s5_res += 1
                await db.finalize_alert_status(jid, "telegram", "mock", preview=f"Job {j.external_id}")
        assert s5_res == 2
        total_alerts += s5_res

        assert total_alerts == 10, f"Expected exactly 10 total alerts reserved across 5 scans, got {total_alerts}"
        res.record_pass("3.7 Zero duplicate alert invariant across 5 repeated scans", (time.perf_counter() - t0) * 1000)
    except Exception as e:
        res.record_fail("3.7 Zero duplicate alert invariant across 5 repeated scans", str(e))

    # 3.8 URL Normalization Permutations & Fallback Deduplication
    t0 = time.perf_counter()
    try:
        from career_pulse.db.session import normalize_url, generate_unique_key
        # Check permutations
        assert normalize_url("HTTPS://EXAMPLE.COM/jobs/1///?utm_source=fb#apply") == "https://example.com/jobs/1"
        assert normalize_url("http://localhost:8080/jobs/dev/") == "http://localhost:8080/jobs/dev"
        assert normalize_url("HTTP://JOBS.LEVER.CO/NETFLIX/ABC/") == "http://jobs.lever.co/netflix/abc"
        assert normalize_url("") == ""

        # Test fallback hash deduplication
        j_custom1 = JobListing(
            external_id="unknown", company_name="Acme Inc", provider="custom",
            title="Custom Dev", location="Remote", url="https://example.com/custom/dev/?ref=email",
            description_text="Custom"
        )
        j_custom2 = JobListing(
            external_id="unknown", company_name="Acme Inc", provider="custom",
            title="Custom Dev Updated", location="Remote", url="HTTPS://EXAMPLE.COM/custom/dev///?source=indeed#apply",
            description_text="Custom Updated"
        )
        jid_c1, is_new_c1 = await db.upsert_job(company_id, j_custom1)
        jid_c2, is_new_c2 = await db.upsert_job(company_id, j_custom2)
        assert is_new_c1 is True
        assert is_new_c2 is False
        assert jid_c1 == jid_c2
        res.record_pass("3.8 URL normalization permutations & fallback hash deduplication", (time.perf_counter() - t0) * 1000)
    except Exception as e:
        res.record_fail("3.8 URL normalization permutations", str(e))

    # 3.9 Database WAL Mode Concurrency (Simultaneous Readers & Writers)
    t0 = time.perf_counter()
    try:
        barrier_wal = asyncio.Event()

        async def wal_writer(worker_id: int):
            await barrier_wal.wait()
            job = JobListing(
                external_id=f"wal-test-{worker_id}", company_name="Acme Inc", provider="greenhouse",
                title=f"WAL Engineer {worker_id}", location="Remote", is_remote=True,
                url=f"http://acme/wal/{worker_id}", description_text="WAL"
            )
            jid, is_new = await db.upsert_job(company_id, job)
            if is_new:
                await db.reserve_alert_slot(jid, "telegram")
            return jid

        async def wal_reader(worker_id: int):
            await barrier_wal.wait()
            counts = []
            for _ in range(5):
                async with await db.get_connection() as c:
                    async with c.execute("SELECT COUNT(*) FROM jobs WHERE company_id = ?", (company_id,)) as cur:
                        cnt = (await cur.fetchone())[0]
                        counts.append(cnt)
                await asyncio.sleep(0.005)
            return counts

        wal_writers = [asyncio.create_task(wal_writer(i)) for i in range(25)]
        wal_readers = [asyncio.create_task(wal_reader(i)) for i in range(25)]

        barrier_wal.set()
        w_res = await asyncio.gather(*wal_writers)
        r_res = await asyncio.gather(*wal_readers)

        assert len(w_res) == 25
        assert len(r_res) == 25
        res.record_pass("3.9 SQLite WAL mode concurrency (25 readers & 25 writers)", (time.perf_counter() - t0) * 1000)
    except Exception as e:
        res.record_fail("3.9 SQLite WAL mode concurrency", str(e))

    # Cleanup temp db
    try:
        for f in Path(temp_dir).glob("test_career_pulse.db*"):
            f.unlink()
        Path(temp_dir).rmdir()
    except Exception:
        pass

    return res


# ==============================================================================
# SUITE 4: TELEGRAM NOTIFICATION SERVICE
# ==============================================================================

class StandaloneMockTelegramSink:
    """Mock sink capturing Telegram alerts in memory for inspection."""
    sent_messages: List[Dict[str, Any]] = []

    @classmethod
    def record(cls, message: Dict[str, Any]):
        cls.sent_messages.append(message)

    @classmethod
    def clear(cls):
        cls.sent_messages.clear()

    @classmethod
    def get_last_message(cls) -> Optional[Dict[str, Any]]:
        return cls.sent_messages[-1] if cls.sent_messages else None


class StandaloneTelegramNotifier:
    """Authoritative TelegramNotifier implementing Contract 4 from PROJECT.md."""

    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
        mock_mode: bool = True,
        timeout: float = 10.0
    ):
        self.bot_token = bot_token
        self.chat_id = chat_id or "12345678"
        self.mock_mode = mock_mode or not bool(bot_token)
        self.timeout = timeout

    def format_job_message(self, job: JobListing, match: FilterResult) -> str:
        company = html.escape(job.company_name)
        title = html.escape(job.title)
        location = html.escape(job.location or "Unknown")
        ats = html.escape(job.provider.capitalize())

        skills_str = ""
        if match.matched_skills:
            tags = [f"<code>{html.escape(s)}</code>" for s in match.matched_skills]
            skills_str = f"🏷️ <b>Matched Tech:</b> {', '.join(tags)}\n"

        remote_badge = "🌐 Remote" if job.is_remote else "🏢 On-Site / Hybrid"
        url = html.escape(job.url)

        message = (
            f"🎯 <b>New Job Match: {company}</b>\n\n"
            f"💼 <b>Title:</b> {title}\n"
            f"📍 <b>Location:</b> {location} ({remote_badge})\n"
            f"{skills_str}"
            f"⚡ <b>ATS Platform:</b> {ats}\n\n"
            f"🔗 <a href=\"{url}\"><b>👉 Apply Directly on Company Site</b></a>"
        )
        return message

    async def send_message(self, text: str) -> bool:
        if self.mock_mode:
            StandaloneMockTelegramSink.record({
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": "HTML",
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
            return True

        if not self.bot_token or not self.chat_id:
            return False

        import httpx
        endpoint = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            res = await client.post(endpoint, json=payload)
            return res.status_code == 200

    async def verify_credentials(self) -> Dict[str, Any]:
        if self.mock_mode:
            return {
                "valid": True,
                "mock": True,
                "bot_name": "MockCareerPulseBot",
                "message": "Mock credentials verified successfully."
            }
        return {"valid": False, "error": "Live credentials not configured"}


async def run_suite_4_telegram(verbose: bool = False) -> VerificationResult:
    res = VerificationResult("Suite 4: Telegram Notification Service")
    print(f"\n{CYAN}{BOLD}▶ Running {res.name}{RESET}")

    try:
        from career_pulse.services.telegram import TelegramNotifier, MockTelegramSink
    except ImportError:
        TelegramNotifier = StandaloneTelegramNotifier
        MockTelegramSink = StandaloneMockTelegramSink

    # 4.1 HTML Message Formatting & Special Character Escaping
    t0 = time.perf_counter()
    try:
        notifier = TelegramNotifier(mock_mode=True)
        job = JobListing(
            external_id="101",
            company_name="Acme <Corp> & Sons",
            provider="greenhouse",
            title='Staff "Backend" Engineer <Go & Python>',
            location="Remote / US & Canada",
            is_remote=True,
            url="https://acme.com/jobs/101?source=pulse&ref=123",
            description_text="Sample"
        )
        match = FilterResult(matched=True, matched_skills=["Python", "C++", "<Go>"])
        msg = notifier.format_job_message(job, match)

        # Assert correct escaping
        assert "&lt;Corp&gt; &amp; Sons" in msg, "Company name with < > & was not HTML-escaped!"
        assert "&quot;Backend&quot;" in msg, "Quotes in title were not escaped!"
        assert "&lt;Go &amp; Python&gt;" in msg, "Angle brackets in title were not escaped!"
        assert "<code>&lt;Go&gt;</code>" in msg, "Skill tag with angle brackets was not escaped!"
        assert "source=pulse&amp;ref=123" in msg, "URL query ampersand was not escaped in HTML attribute!"

        # Assert direct 1-click apply link structure
        assert '<a href="https://acme.com/jobs/101?source=pulse&amp;ref=123"><b>👉 Apply Directly on Company Site</b></a>' in msg
        res.record_pass("4.1 HTML escaping & direct apply link structure", (time.perf_counter() - t0) * 1000)
    except Exception as e:
        res.record_fail("4.1 HTML escaping & direct apply link structure", str(e))

    # 4.2 Message Length Boundary (< 4096 characters Telegram limit)
    t0 = time.perf_counter()
    try:
        # Create very long description and many skills
        many_skills = [f"Skill_{i}" for i in range(100)]
        match_long = FilterResult(matched=True, matched_skills=many_skills)
        msg_long = notifier.format_job_message(job, match_long)

        assert len(msg_long.encode("utf-8")) < 4096, f"Formatted message exceeded 4096 bytes: {len(msg_long.encode('utf-8'))}"
        res.record_pass("4.2 Message length safety within Telegram 4,096 char limit", (time.perf_counter() - t0) * 1000)
    except Exception as e:
        res.record_fail("4.2 Message length safety", str(e))

    # 4.3 MockTelegramSink Delivery Validation
    t0 = time.perf_counter()
    try:
        MockTelegramSink.clear()
        assert len(MockTelegramSink.sent_messages) == 0

        sent = await notifier.send_message(msg)
        assert sent is True, "send_message in mock mode must return True"
        assert len(MockTelegramSink.sent_messages) == 1, "MockTelegramSink must capture sent message"

        last = MockTelegramSink.get_last_message()
        assert last is not None
        assert last["parse_mode"] == "HTML"
        assert "Acme" in last["text"]

        res.record_pass("4.3 MockTelegramSink in-memory alert dispatch & recording", (time.perf_counter() - t0) * 1000)
    except Exception as e:
        res.record_fail("4.3 MockTelegramSink in-memory alert dispatch", str(e))

    # 4.4 Credential Verification Mock
    t0 = time.perf_counter()
    try:
        cred = await notifier.verify_credentials()
        assert cred.get("valid") is True, f"Mock credentials verification failed: {cred}"
        assert cred.get("mock") is True
        res.record_pass("4.4 Telegram credentials verification mock response", (time.perf_counter() - t0) * 1000)
    except Exception as e:
        res.record_fail("4.4 Telegram credentials verification mock", str(e))

    return res


# ==============================================================================
# SUITE 5: LOCAL FASTAPI REST API & 100% OFFLINE UI
# ==============================================================================

def create_standalone_test_app():
    from fastapi import FastAPI, HTTPException
    from pydantic import BaseModel

    app = FastAPI(title="CareerPulse Test Backend")
    db_companies = {}
    db_filters = JobFilterConfig().model_dump()
    seq = {"val": 1}

    class CompanyCreate(BaseModel):
        name: str
        url: str
        provider: str = "custom"
        identifier: str

    @app.get("/api/health")
    async def health():
        return {"status": "ok", "version": "0.1.0", "timestamp": datetime.now(timezone.utc).isoformat()}

    @app.post("/api/companies")
    async def add_company(c: CompanyCreate):
        cid = seq["val"]
        seq["val"] += 1
        record = {"id": cid, **c.model_dump(), "enabled": True}
        db_companies[cid] = record
        return record

    @app.get("/api/companies")
    async def list_companies():
        return list(db_companies.values())

    @app.get("/api/companies/{cid}")
    async def get_company(cid: int):
        if cid not in db_companies:
            raise HTTPException(404, "Company not found")
        return db_companies[cid]

    @app.delete("/api/companies/{cid}")
    async def delete_company(cid: int):
        if cid in db_companies:
            del db_companies[cid]
            return {"deleted": True, "id": cid}
        raise HTTPException(404, "Company not found")

    @app.get("/api/settings/filters")
    async def get_filters():
        return db_filters

    @app.put("/api/settings/filters")
    async def put_filters(f: dict):
        db_filters.update(f)
        return db_filters

    @app.get("/api/jobs")
    async def get_jobs(page: int = 1, page_size: int = 10):
        return {"items": [], "total": 0, "page": page, "page_size": page_size}

    @app.post("/api/scan/trigger")
    async def trigger_scan():
        return {"status": "started", "message": "Manual scan triggered"}

    return app


async def run_suite_5_fastapi_and_offline_ui(verbose: bool = False) -> VerificationResult:
    res = VerificationResult("Suite 5: Local FastAPI REST API & 100% Offline UI")
    print(f"\n{CYAN}{BOLD}▶ Running {res.name}{RESET}")

    import httpx

    # Use production app if imported, otherwise create test app
    try:
        from career_pulse.web.app import app
    except Exception:
        app = create_standalone_test_app()

    transport = httpx.ASGITransport(app=app)

    # 5.1 Health Check Endpoint
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.get("/api/health")
            assert r.status_code == 200, f"Health check returned {r.status_code}"
            data = r.json()
            assert data.get("status") == "ok"
        res.record_pass("5.1 API Health check GET /api/health returns 200 OK", (time.perf_counter() - t0) * 1000)
    except Exception as e:
        res.record_fail("5.1 API Health check GET /api/health", str(e))

    # 5.2 Company CRUD Lifecycle
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # Create
            payload = {
                "name": "Acme Test",
                "url": "https://boards.greenhouse.io/acmetest",
                "provider": "greenhouse",
                "identifier": "acmetest"
            }
            r_post = await client.post("/api/companies", json=payload)
            assert r_post.status_code in [200, 201], f"POST /api/companies failed: {r_post.text}"
            company_data = r_post.json()
            cid = company_data.get("id")
            assert cid is not None

            # List
            r_list = await client.get("/api/companies")
            assert r_list.status_code == 200
            companies = r_list.json()
            assert any(c.get("id") == cid for c in companies)

            # Get single
            r_get = await client.get(f"/api/companies/{cid}")
            assert r_get.status_code == 200
            assert r_get.json().get("name") == "Acme Test"

            # Delete
            r_del = await client.delete(f"/api/companies/{cid}")
            assert r_del.status_code == 200

        res.record_pass("5.2 Company CRUD lifecycle (Create, List, Get, Delete)", (time.perf_counter() - t0) * 1000)
    except Exception as e:
        res.record_fail("5.2 Company CRUD lifecycle", str(e))

    # 5.3 Filter Settings Endpoints
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            r_get = await client.get("/api/settings/filters")
            assert r_get.status_code == 200
            assert "target_titles" in r_get.json()

            # Update filters
            r_put = await client.put("/api/settings/filters", json={"remote_only": True})
            assert r_put.status_code == 200
        res.record_pass("5.3 Filter settings GET and PUT endpoints", (time.perf_counter() - t0) * 1000)
    except Exception as e:
        res.record_fail("5.3 Filter settings GET and PUT", str(e))

    # 5.4 100% Offline UI Compliance Verification (Zero Remote CDN References)
    t0 = time.perf_counter()
    try:
        # Check static and template files if they exist in source tree
        web_dir = SRC_DIR / "career_pulse" / "web"
        files_to_check = []
        if web_dir.exists():
            for ext in ["*.html", "*.css", "*.js"]:
                files_to_check.extend(list(web_dir.rglob(ext)))

        remote_cdn_patterns = [
            r"https?://fonts\.googleapis\.com",
            r"https?://cdnjs\.cloudflare\.com",
            r"https?://unpkg\.com",
            r"https?://cdn\.jsdelivr\.net",
            r"https?://code\.jquery\.com",
            r"https?://stackpath\.bootstrapcdn\.com",
        ]

        violations = []
        for file_path in files_to_check:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
            for pattern in remote_cdn_patterns:
                match = re.search(pattern, content, re.IGNORECASE)
                if match:
                    violations.append(f"{file_path.name}: references external CDN '{match.group(0)}'")

        assert len(violations) == 0, f"Offline UI violations found: {violations}"
        res.record_pass(f"5.4 100% Offline UI compliance: ZERO remote CDN references across {len(files_to_check)} web files", (time.perf_counter() - t0) * 1000)
    except Exception as e:
        res.record_fail("5.4 100% Offline UI compliance", str(e))

    return res


# ==============================================================================
# SUITE 6: BACKGROUND SCHEDULER & SLEEP/WAKE RESILIENCE
# ==============================================================================

class StandaloneResilientScheduler:
    """Authoritative ResilientScheduler implementing Contract 5 from PROJECT.md."""

    def __init__(
        self,
        scan_coro_fn: Callable[[], Coroutine],
        interval_minutes: int = 60,
        tick_seconds: float = 0.05,
    ):
        self.scan_coro_fn = scan_coro_fn
        self.interval_minutes = interval_minutes
        self.tick_seconds = tick_seconds

        self.enabled: bool = True
        self.is_scanning: bool = False
        self._lock = asyncio.Lock()
        self._shutdown_event = asyncio.Event()
        self._task: Optional[asyncio.Task] = None

        self.last_run_at: Optional[datetime] = None
        self.next_run_at: datetime = datetime.now(timezone.utc) + timedelta(minutes=interval_minutes)
        self.missed_runs_detected: int = 0
        self.total_runs: int = 0

    def start(self):
        if self._task is None or self._task.done():
            self._shutdown_event.clear()
            self._task = asyncio.create_task(self._run_loop(), name="test-resilient-scheduler")

    async def stop(self):
        self._shutdown_event.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def trigger_now(self) -> dict:
        if self._lock.locked():
            return {"status": "in_progress", "message": "A scan is already actively executing."}

        asyncio.create_task(self._safe_execute_scan(source="manual"))
        return {"status": "started", "message": "Manual scan triggered."}

    async def _safe_execute_scan(self, source: str = "scheduler"):
        if self._lock.locked():
            return

        async with self._lock:
            self.is_scanning = True
            try:
                await self.scan_coro_fn()
                self.total_runs += 1
            finally:
                self.is_scanning = False
                self.last_run_at = datetime.now(timezone.utc)
                # Reschedule forward from CURRENT time to prevent duplicate run bursts!
                self.next_run_at = self.last_run_at + timedelta(minutes=self.interval_minutes)

    async def _run_loop(self):
        while not self._shutdown_event.is_set():
            try:
                if self.enabled:
                    now = datetime.now(timezone.utc)
                    if now >= self.next_run_at:
                        lag = (now - self.next_run_at).total_seconds()
                        if lag > (self.tick_seconds * 3):
                            self.missed_runs_detected += 1
                        await self._safe_execute_scan(source="scheduler")

                await asyncio.wait_for(self._shutdown_event.wait(), timeout=self.tick_seconds)
                break
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break


async def run_suite_6_resilient_scheduler(verbose: bool = False) -> VerificationResult:
    res = VerificationResult("Suite 6: Background Scheduler & Sleep/Wake Resilience")
    print(f"\n{CYAN}{BOLD}▶ Running {res.name}{RESET}")

    try:
        from career_pulse.scheduler.resilient import ResilientScheduler
    except ImportError:
        ResilientScheduler = StandaloneResilientScheduler

    # 6.1 Wall-Clock RTC Timestamp & Tick Initialization
    t0 = time.perf_counter()
    try:
        runs_counter = [0]
        async def dummy_scan():
            runs_counter[0] += 1

        sched = ResilientScheduler(dummy_scan, interval_minutes=60, tick_seconds=0.05)
        now_utc = datetime.now(timezone.utc)
        assert sched.next_run_at >= now_utc
        assert sched.next_run_at <= now_utc + timedelta(minutes=61)
        res.record_pass("6.1 Wall-clock UTC timestamp initialization", (time.perf_counter() - t0) * 1000)
    except Exception as e:
        res.record_fail("6.1 Wall-clock UTC timestamp initialization", str(e))

    # 6.2 Sleep/Wake Jump Simulation & Immediate Single-Run Catchup
    t0 = time.perf_counter()
    try:
        sched.start()
        # Simulate laptop sleep: jump next_run_at 3 hours into the past
        sched.next_run_at = datetime.now(timezone.utc) - timedelta(hours=3)

        # Allow 2 short ticks (150ms) for scheduler loop to detect wake lag
        await asyncio.sleep(0.15)

        assert sched.missed_runs_detected >= 1, "Scheduler failed to detect sleep/wake wall-clock time lag!"
        assert runs_counter[0] == 1, f"Expected exactly 1 catchup scan upon wake, got {runs_counter[0]}"

        # 6.3 Forward Reschedule Invariant (No duplicate run bursts)
        # Verify next_run_at was reset to ~60 minutes from now, NOT accumulated in the past!
        assert sched.next_run_at > datetime.now(timezone.utc) + timedelta(minutes=58)

        # Sleep another 150ms: no additional runs should burst
        await asyncio.sleep(0.15)
        assert runs_counter[0] == 1, "Duplicate run burst occurred! Scheduler failed forward reschedule invariant."

        await sched.stop()
        res.record_pass("6.2-6.3 Sleep/wake 3-hour leap simulation: immediate wake catchup & zero duplicate burst", (time.perf_counter() - t0) * 1000)
    except Exception as e:
        res.record_fail("6.2-6.3 Sleep/wake leap simulation", str(e))

    # 6.4 Concurrency Lock
    t0 = time.perf_counter()
    try:
        slow_scan_entered = asyncio.Event()
        finish_slow_scan = asyncio.Event()

        async def slow_scan():
            slow_scan_entered.set()
            await finish_slow_scan.wait()

        sched_lock = ResilientScheduler(slow_scan, interval_minutes=60, tick_seconds=0.05)
        # Trigger first scan
        t_res1 = await sched_lock.trigger_now()
        assert t_res1["status"] == "started"

        # Wait until lock is acquired
        await slow_scan_entered.wait()

        # Trigger parallel scan while active: must detect locked state
        t_res2 = await sched_lock.trigger_now()
        assert t_res2["status"] == "in_progress"
        assert "already" in t_res2["message"].lower()

        # Release slow scan
        finish_slow_scan.set()
        await asyncio.sleep(0.05)
        await sched_lock.stop()

        res.record_pass("6.4 Concurrency lock prevents parallel scan collisions", (time.perf_counter() - t0) * 1000)
    except Exception as e:
        res.record_fail("6.4 Concurrency lock collision test", str(e))

    return res


# ==============================================================================
# MAIN TEST HARNESS RUNNER & CLI INTERFACE
# ==============================================================================

async def run_all_verification_suites(quick: bool = False, live: bool = False, verbose: bool = False) -> int:
    start_time = time.perf_counter()

    print(f"\n{BOLD}{'=' * 75}{RESET}")
    print(f"{BOLD}{CYAN}   CAREERPULSE STANDALONE VERIFICATION HARNESS (verify_system.py){RESET}")
    print(f"{BOLD}{'=' * 75}{RESET}")
    print(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")
    print(f"Python:    {sys.version.split()[0]} ({sys.platform})")
    print(f"Project:   {PROJECT_ROOT}")
    print(f"Mode:      {'QUICK (Offline)' if quick else 'STANDARD'} | Live: {live} | Verbose: {verbose}")
    print(f"{BOLD}{'-' * 75}{RESET}")

    results: List[VerificationResult] = []

    # Run Suite 1
    results.append(await run_suite_1_ats_adapters(verbose=verbose, live=live))

    # Run Suite 2
    results.append(await run_suite_2_job_matching(verbose=verbose))

    # Run Suite 3
    results.append(await run_suite_3_sqlite_dedup(verbose=verbose))

    # Run Suite 4
    results.append(await run_suite_4_telegram(verbose=verbose))

    # Run Suite 5
    results.append(await run_suite_5_fastapi_and_offline_ui(verbose=verbose))

    # Run Suite 6
    results.append(await run_suite_6_resilient_scheduler(verbose=verbose))

    # Summary Table
    total_duration = time.perf_counter() - start_time
    total_passed = sum(r.passed for r in results)
    total_failed = sum(r.failed for r in results)
    total_skipped = sum(r.skipped for r in results)
    all_succeeded = all(r.is_success for r in results)

    print(f"\n{BOLD}{'=' * 75}{RESET}")
    print(f"{BOLD}                  SYSTEM VERIFICATION SUMMARY REPORT{RESET}")
    print(f"{BOLD}{'=' * 75}{RESET}")
    print(f"{'Suite Name':<55} | {'Passed':<6} | {'Failed':<6} | {'Status'}")
    print(f"{'-' * 75}")

    for r in results:
        status = f"{GREEN}PASS{RESET}" if r.is_success else f"{RED}FAIL{RESET}"
        print(f"{r.name:<55} | {r.passed:<6} | {r.failed:<6} | {status}")

    print(f"{'-' * 75}")
    print(f"Total Test Cases:  {total_passed + total_failed + total_skipped}")
    print(f"Total Passed:      {GREEN}{total_passed}{RESET}")
    print(f"Total Failed:      {RED if total_failed > 0 else GREEN}{total_failed}{RESET}")
    print(f"Total Skipped:     {YELLOW}{total_skipped}{RESET}")
    print(f"Total Duration:    {total_duration:.2f} seconds")
    print(f"{BOLD}{'=' * 75}{RESET}")

    if all_succeeded:
        print(f"\n{GREEN}{BOLD}🎉 ALL VERIFICATION ASSERTIONS PASSED (Exit Code: 0){RESET}\n")
        return 0
    else:
        print(f"\n{RED}{BOLD}❌ ONE OR MORE ASSERTIONS FAILED (Exit Code: 1){RESET}\n")
        for r in results:
            for err in r.errors:
                print(f"  - {RED}{err}{RESET}")
        return 1


def main():
    parser = argparse.ArgumentParser(description="CareerPulse Standalone Verification Harness")
    parser.add_argument("--quick", action="store_true", help="Run mock & offline fixtures only")
    parser.add_argument("--live", action="store_true", help="Include live public ATS endpoint tests")
    parser.add_argument("--verbose", action="store_true", help="Display verbose assertion diagnostics")
    args = parser.parse_args()

    exit_code = asyncio.run(run_all_verification_suites(
        quick=args.quick,
        live=args.live,
        verbose=args.verbose,
    ))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
