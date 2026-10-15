"""
Companion Pytest E2E Suite for CareerPulse.
Exercises verification suites across all tiers:
- Tier 1: ATS Adapters & Auto-Detection
- Tier 2: Job Matching, Scoring & Strict Negative Exclusions
- Tier 3: SQLite Storage, WAL Mode & Zero Duplicate Alert Deduplication
- Tier 4: Telegram Push Notification Service & Mock Sink
- Tier 5: Adversarial Boundary Symbols & Sleep/Wake Resilience
"""

import asyncio
from pathlib import Path
import re
import sys
import pytest

# Ensure project root and src are on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from verify_system import (
    run_suite_1_ats_adapters,
    run_suite_2_job_matching,
    run_suite_3_sqlite_dedup,
    run_suite_4_telegram,
    run_suite_5_fastapi_and_offline_ui,
    run_suite_6_resilient_scheduler,
    build_boundary_pattern,
    strip_html_tags,
    StandaloneJobMatcher,
    StandaloneDatabase,
    StandaloneTelegramNotifier,
    StandaloneMockTelegramSink,
    StandaloneResilientScheduler,
    JobFilterConfig,
    JobListing,
    FilterResult,
)


@pytest.mark.asyncio
async def test_suite_1_ats_adapters_and_detection():
    """Verify all ATS adapters (Greenhouse, Lever, Ashby, Workday, Fallback) and auto-detection."""
    result = await run_suite_1_ats_adapters(verbose=False, live=False)
    assert result.is_success, f"Suite 1 failed with errors: {result.errors}"
    assert result.passed >= 6


@pytest.mark.asyncio
async def test_suite_2_job_matching_and_negative_exclusions():
    """Verify lookaround regex matching, scoring, and negative keyword exclusions."""
    result = await run_suite_2_job_matching(verbose=False)
    assert result.is_success, f"Suite 2 failed with errors: {result.errors}"
    assert result.passed >= 6


@pytest.mark.asyncio
async def test_suite_3_sqlite_wal_and_deduplication():
    """Verify SQLite WAL mode, schema, atomic reservation, and zero duplicate alerts."""
    result = await run_suite_3_sqlite_dedup(verbose=False)
    assert result.is_success, f"Suite 3 failed with errors: {result.errors}"
    assert result.passed >= 5


@pytest.mark.asyncio
async def test_suite_4_telegram_notification_service():
    """Verify HTML escaping, direct links, MockTelegramSink, and length bounds."""
    result = await run_suite_4_telegram(verbose=False)
    assert result.is_success, f"Suite 4 failed with errors: {result.errors}"
    assert result.passed >= 4


@pytest.mark.asyncio
async def test_suite_5_fastapi_rest_and_offline_ui():
    """Verify FastAPI REST endpoints and 100% offline UI asset compliance."""
    result = await run_suite_5_fastapi_and_offline_ui(verbose=False)
    assert result.is_success, f"Suite 5 failed with errors: {result.errors}"
    assert result.passed >= 4


@pytest.mark.asyncio
async def test_suite_6_resilient_scheduler_and_time_jump():
    """Verify wall-clock UTC checks, 3-hour leap wake catchup, and concurrency locks."""
    result = await run_suite_6_resilient_scheduler(verbose=False)
    assert result.is_success, f"Suite 6 failed with errors: {result.errors}"
    assert result.passed >= 3


# ==============================================================================
# GRANULAR ADVERSARIAL & BOUNDARY TESTS (Tier 5)
# ==============================================================================

def test_adversarial_word_boundary_symbols():
    """Verify boundary patterns correctly match C++, C#, .NET without standard \\b failures."""
    cpp_pat = build_boundary_pattern("C++")
    assert cpp_pat.search("Senior C++ Developer") is not None
    assert cpp_pat.search("Modern C++20") is not None

    csharp_pat = build_boundary_pattern("C#")
    assert csharp_pat.search("C# Backend Engineer") is not None

    dotnet_pat = build_boundary_pattern(".NET")
    assert dotnet_pat.search("ASP.NET Core Developer") is not None


def test_adversarial_word_boundary_go_vs_good():
    """Verify 'Go' keyword matches the programming language but never 'Good'."""
    go_pat = build_boundary_pattern("Go")
    assert go_pat.search("Go Developer") is not None
    assert go_pat.search("Developer in Go") is not None
    assert go_pat.search("Good Developer") is None
    assert go_pat.search("Governance Analyst") is None


def test_adversarial_intern_vs_internal_and_international():
    """Verify negative keyword 'intern' rejects internships but keeps internal/international roles."""
    intern_pat = build_boundary_pattern("intern")
    assert intern_pat.search("Software Engineering Intern") is not None
    assert intern_pat.search("Summer Intern 2026") is not None
    assert intern_pat.search("Internal Tools Engineer") is None
    assert intern_pat.search("International Business Development") is None


def test_html_stripping_and_escaping():
    """Verify HTML stripping handles complex tags, attributes, and unescapes entities."""
    raw = "<p>Join <b>Acme</b> &amp; build microservices with &lt;Python&gt;.</p>"
    clean = strip_html_tags(raw)
    assert "<p>" not in clean
    assert "<b>" not in clean
    assert "Acme & build microservices with <Python>." in clean


def test_offline_ui_zero_external_cdn_strict():
    """Strict test verifying that no static or template files load remote CDNs."""
    web_dir = SRC_DIR / "career_pulse" / "web"
    if not web_dir.exists():
        pytest.skip("web directory not yet created by M4")

    files = list(web_dir.rglob("*.html")) + list(web_dir.rglob("*.css")) + list(web_dir.rglob("*.js"))
    cdn_regex = re.compile(r"https?://(?:fonts\.googleapis\.com|cdnjs\.cloudflare\.com|unpkg\.com|cdn\.jsdelivr\.net)", re.I)

    for f in files:
        content = f.read_text(encoding="utf-8", errors="ignore")
        match = cdn_regex.search(content)
        assert match is None, f"Remote CDN detected in {f.name}: {match.group(0)}"
