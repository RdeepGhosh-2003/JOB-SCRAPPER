"""
Unit tests for CareerPulse Job Matching & Filtering Engine (Milestone 2).
"""

import pytest
from career_pulse.core.matching import (
    JobMatcher,
    build_boundary_pattern,
    strip_html_tags,
)
from career_pulse.core.models import FilterResult, JobFilterConfig, JobListing


def test_build_boundary_pattern_symbol_languages():
    """Verify symbol-laden technologies match with lookaround regex without \\b failures."""
    cpp_pat = build_boundary_pattern("C++")
    assert cpp_pat.search("Modern C++ Engineer") is not None
    assert cpp_pat.search("C++20 Developer") is not None
    assert cpp_pat.search("Kernel Developer in C++") is not None
    assert cpp_pat.search("Objective-C Developer") is None

    csharp_pat = build_boundary_pattern("C#")
    assert csharp_pat.search("Senior C# Developer") is not None
    assert csharp_pat.search("Building services in C#") is not None
    assert csharp_pat.search("C Developer") is None

    dotnet_pat = build_boundary_pattern(".NET")
    assert dotnet_pat.search("ASP.NET Core Specialist") is not None
    assert dotnet_pat.search("Expert in .NET 8") is not None
    assert dotnet_pat.search("Network Analyst") is None


def test_build_boundary_pattern_go_vs_good_and_governance():
    """Verify 'Go' matches language name but never prefixes like 'Good' or 'Governance'."""
    go_pat = build_boundary_pattern("Go")
    assert go_pat.search("Go Systems Engineer") is not None
    assert go_pat.search("Backend Developer (Go)") is not None
    assert go_pat.search("Proficient in Go, Python") is not None
    assert go_pat.search("Good Software Engineer") is None
    assert go_pat.search("Governance Risk Officer") is None
    assert go_pat.search("Google Cloud Architect") is None


def test_build_boundary_pattern_intern_vs_internal_and_international():
    """Verify negative 'intern' matches student roles but preserves 'Internal' and 'International'."""
    intern_pat = build_boundary_pattern("intern")
    assert intern_pat.search("Software Engineering Intern") is not None
    assert intern_pat.search("Summer Intern 2026") is not None
    assert intern_pat.search("Co-op Intern") is not None
    assert intern_pat.search("Internal Tools Engineer") is None
    assert intern_pat.search("International Business Lead") is None
    assert intern_pat.search("Internet Infrastructure Engineer") is None


def test_strip_html_tags_and_entities():
    """Verify HTML markup stripping and entity unescaping."""
    raw = "<p>Join <strong>Acme Corp</strong> &amp; write &lt;FastAPI&gt; services with &#39;Python&#39;!</p>"
    cleaned = strip_html_tags(raw)
    assert "<p>" not in cleaned
    assert "<strong>" not in cleaned
    assert "Acme Corp & write <FastAPI> services with 'Python'!" in cleaned

    assert strip_html_tags("") == ""
    assert strip_html_tags(None) == ""


def test_positive_title_matching():
    """Verify target titles match accurately using lookaround patterns."""
    config = JobFilterConfig(
        target_titles=["Software Engineer", "Backend Developer", "Full Stack Developer"],
        required_skills=["Python"],
        skills_match_mode="any",
    )
    matcher = JobMatcher(config)

    job1 = JobListing(
        external_id="101",
        company_name="Acme",
        title="Software Engineer, Backend",
        location="Remote",
        is_remote=True,
        url="https://example.com/jobs/101",
        description_text="Python API development",
    )
    res1 = matcher.evaluate(job1)
    assert res1.matched is True
    assert res1.matched_title is not None
    assert res1.match_score >= 3.0

    job2 = JobListing(
        external_id="102",
        company_name="Acme",
        title="Data Analyst",
        location="Remote",
        is_remote=True,
        url="https://example.com/jobs/102",
        description_text="SQL and data warehouse reporting",
    )
    res2 = matcher.evaluate(job2)
    assert res2.matched is False
    assert "Title did not match any target titles" in (res2.rejection_reason or "")


def test_strict_negative_title_exclusion():
    """Verify strict exclusion on seniority and management negative keywords in titles."""
    config = JobFilterConfig(
        target_titles=["Software Engineer", "Developer", "Architect"],
        negative_title_keywords=[
            "senior", "sr", "sr.", "principal", "staff", "lead",
            "manager", "director", "head of", "vp", "intern", "co-op"
        ],
    )
    matcher = JobMatcher(config)

    rejected_titles = [
        "Senior Software Engineer",
        "Sr Software Engineer",
        "Sr. Backend Developer",
        "Principal Systems Architect",
        "Staff Software Engineer",
        "Lead Full Stack Developer",
        "Engineering Manager",
        "Director of Software Engineering",
        "Head of Engineering",
        "VP of Technology",
        "Software Engineering Intern",
        "Engineering Co-op",
    ]

    for title in rejected_titles:
        job = JobListing(
            external_id="neg",
            company_name="Acme",
            title=title,
            location="Remote",
            is_remote=True,
            url="https://example.com/neg",
            description_text="Python development",
        )
        res = matcher.evaluate(job)
        assert res.matched is False, f"Expected '{title}' to be rejected"
        assert "Title matched negative keyword" in (res.rejection_reason or "")


def test_description_isolation_from_negative_title_keywords():
    """
    CRITICAL ARCHITECTURE REQUIREMENT:
    Negative title keywords like 'Manager' or 'Senior' MUST NOT cause false rejections
    when appearing only in description body (e.g. 'reports to Engineering Manager').
    """
    config = JobFilterConfig(
        target_titles=["Software Engineer"],
        negative_title_keywords=["manager", "senior", "lead", "director"],
        negative_description_keywords=["10+ years", "active security clearance"],
        required_skills=["Python"],
    )
    matcher = JobMatcher(config)

    job = JobListing(
        external_id="iso-1",
        company_name="Acme",
        title="Software Engineer",
        location="Remote",
        is_remote=True,
        url="https://example.com/iso-1",
        description_text=(
            "As a Software Engineer on our team, you will report directly to the "
            "Engineering Manager and collaborate closely with senior engineers, "
            "the team lead, and our director of engineering. Tech stack: Python."
        ),
    )

    res = matcher.evaluate(job)
    assert res.matched is True, f"Job was unexpectedly rejected: {res.rejection_reason}"
    assert "Python" in res.matched_skills


def test_negative_description_keyword_exclusion():
    """Verify negative description keywords reject jobs when specified."""
    config = JobFilterConfig(
        target_titles=["Software Engineer"],
        negative_description_keywords=["10+ years", "active security clearance"],
        required_skills=["Python"],
    )
    matcher = JobMatcher(config)

    job = JobListing(
        external_id="neg-desc-1",
        company_name="DefenseCorp",
        title="Software Engineer",
        location="Remote",
        is_remote=True,
        url="https://example.com/neg-desc-1",
        description_text="Requires active security clearance and 5 years of Python.",
    )

    res = matcher.evaluate(job)
    assert res.matched is False
    assert "Description matched negative keyword" in (res.rejection_reason or "")


def test_skills_match_mode_all():
    """Verify 'all' mode requires every required skill to be present."""
    config = JobFilterConfig(
        target_titles=["Backend Developer"],
        required_skills=["Python", "FastAPI", "Docker"],
        skills_match_mode="all",
    )
    matcher = JobMatcher(config)

    # Missing Docker
    job_partial = JobListing(
        external_id="sk-1",
        company_name="Acme",
        title="Backend Developer",
        location="Remote",
        is_remote=True,
        url="https://example.com/sk-1",
        description_text="We use Python and FastAPI for microservices.",
    )
    res_partial = matcher.evaluate(job_partial)
    assert res_partial.matched is False
    assert "Missing required skills" in (res_partial.rejection_reason or "")
    assert "Docker" in (res_partial.rejection_reason or "")

    # Has all three
    job_complete = JobListing(
        external_id="sk-2",
        company_name="Acme",
        title="Backend Developer",
        location="Remote",
        is_remote=True,
        url="https://example.com/sk-2",
        description_text="We use Python, FastAPI, and Docker in production.",
    )
    res_complete = matcher.evaluate(job_complete)
    assert res_complete.matched is True
    assert set(res_complete.matched_skills) >= {"Python", "FastAPI", "Docker"}


def test_skills_match_mode_any():
    """Verify 'any' mode accepts a job if at least 1 required skill matches."""
    config = JobFilterConfig(
        target_titles=["Backend Developer"],
        required_skills=["Python", "Go", "Rust"],
        skills_match_mode="any",
    )
    matcher = JobMatcher(config)

    job_one = JobListing(
        external_id="sk-any-1",
        company_name="Acme",
        title="Backend Developer",
        location="Remote",
        is_remote=True,
        url="https://example.com/sk-any-1",
        description_text="Modern Go backend services.",
    )
    res_one = matcher.evaluate(job_one)
    assert res_one.matched is True
    assert "Go" in res_one.matched_skills

    job_none = JobListing(
        external_id="sk-any-2",
        company_name="Acme",
        title="Backend Developer",
        location="Remote",
        is_remote=True,
        url="https://example.com/sk-any-2",
        description_text="PHP and Ruby on Rails stack.",
    )
    res_none = matcher.evaluate(job_none)
    assert res_none.matched is False
    assert "Did not match any required skills" in (res_none.rejection_reason or "")


def test_skills_match_mode_none():
    """Verify 'none' mode bypasses required skill checks."""
    config = JobFilterConfig(
        target_titles=["Developer"],
        required_skills=["Haskell", "Fortran"],
        skills_match_mode="none",
    )
    matcher = JobMatcher(config)

    job = JobListing(
        external_id="sk-none",
        company_name="Acme",
        title="Developer",
        location="Remote",
        is_remote=True,
        url="https://example.com/sk-none",
        description_text="General software engineering.",
    )
    res = matcher.evaluate(job)
    assert res.matched is True


def test_preferred_skills_and_match_scoring():
    """Verify preferred skills increase the match score."""
    config = JobFilterConfig(
        target_titles=["Software Engineer"],
        required_skills=["Python"],
        preferred_skills=["FastAPI", "PostgreSQL", "Docker", "AWS"],
        skills_match_mode="any",
    )
    matcher = JobMatcher(config)

    job_basic = JobListing(
        external_id="score-1",
        company_name="Acme",
        title="Software Engineer",
        location="San Francisco, CA",
        is_remote=False,
        url="https://example.com/score-1",
        description_text="Python coding.",
    )
    score_basic = matcher.evaluate(job_basic).match_score

    job_boosted = JobListing(
        external_id="score-2",
        company_name="Acme",
        title="Software Engineer",
        location="Remote",
        is_remote=True,
        url="https://example.com/score-2",
        description_text="Python with FastAPI, PostgreSQL, Docker, and AWS.",
    )
    res_boosted = matcher.evaluate(job_boosted)
    assert res_boosted.matched is True
    assert res_boosted.match_score > score_basic
    assert len(res_boosted.matched_skills) == 5


def test_location_and_remote_filtering():
    """Verify remote-only, allowed locations, and excluded locations filtering."""
    config = JobFilterConfig(
        target_titles=["Developer"],
        remote_only=True,
        allowed_locations=["United States", "US"],
        excluded_locations=["Europe", "London"],
    )
    matcher = JobMatcher(config)

    # 1. On-site job rejected when remote_only=True
    job_onsite = JobListing(
        external_id="loc-1",
        company_name="Acme",
        title="Developer",
        location="New York, NY",
        is_remote=False,
        url="https://example.com/loc-1",
        description_text="Python",
    )
    assert matcher.evaluate(job_onsite).matched is False

    # 2. Remote job in allowed location accepted
    job_remote = JobListing(
        external_id="loc-2",
        company_name="Acme",
        title="Developer",
        location="Remote - US",
        is_remote=True,
        url="https://example.com/loc-2",
        description_text="Python",
    )
    assert matcher.evaluate(job_remote).matched is True

    # 3. Remote job in excluded location rejected
    job_excluded = JobListing(
        external_id="loc-3",
        company_name="Acme",
        title="Developer",
        location="London, Europe (Remote)",
        is_remote=True,
        url="https://example.com/loc-3",
        description_text="Python",
    )
    res_excl = matcher.evaluate(job_excluded)
    assert res_excl.matched is False
    assert "Location matches excluded pattern" in (res_excl.rejection_reason or "")


def test_empty_target_titles_allows_all_non_negative():
    """When target_titles is empty, all jobs passing negative filter should be accepted."""
    config = JobFilterConfig(
        target_titles=[],
        required_skills=["Python"],
        skills_match_mode="any",
    )
    matcher = JobMatcher(config)

    job = JobListing(
        external_id="any-title",
        company_name="Acme",
        title="Solutions Architect",
        location="Remote",
        is_remote=True,
        url="https://example.com/any-title",
        description_text="Python integrations",
    )
    res = matcher.evaluate(job)
    assert res.matched is True
    assert res.matched_title == "Solutions Architect"
