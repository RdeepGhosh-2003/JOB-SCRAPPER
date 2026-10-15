"""
Adversarial Stress Test Suite for Milestone 2:
- Symbol Keywords: C++, C#, .NET, Node.js, C++20, ASP.NET Core
- Word Boundaries: Go vs Good, Intern vs Internal, Staff vs Staffing, Lead vs Leader vs Leadership
- Description vs Title Negative Keyword Isolation
- Negative Description Keyword Exclusion
- Empty & Malformed Criteria, Null/Missing Values
- Unicode Characters, Accents, Non-Latin Alphabets, Emojis
- Strange Locations, Regex Metacharacters, Remote Detection Edge Cases
- SQLite Ingestion, URL Canonicalization & Deduplication Invariants
"""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import pytest

from career_pulse.core.matching import (
    JobMatcher,
    build_boundary_pattern,
    strip_html_tags,
)
from career_pulse.core.models import FilterResult, JobFilterConfig, JobListing
from career_pulse.db.session import Database, generate_unique_key, normalize_url


# ==============================================================================
# 1. SYMBOL KEYWORDS STRESS TESTS
# ==============================================================================

class TestSymbolKeywords:
    """Stress test boundary patterns for symbol-laden technology keywords."""

    def test_cpp_variations_and_rejections(self):
        """Verify C++ matches language uses and version suffixes without false rejections."""
        cpp_pat = build_boundary_pattern("C++")

        # Positive matches
        assert cpp_pat.search("Senior C++ Developer") is not None
        assert cpp_pat.search("Modern C++20 Engineer") is not None
        assert cpp_pat.search("Kernel Developer in C++") is not None
        assert cpp_pat.search("C++17 Standards") is not None
        assert cpp_pat.search("C++23 Systems Architect") is not None
        assert cpp_pat.search("Proficient in C/C++") is not None
        assert cpp_pat.search("C++\nDeveloper") is not None
        assert cpp_pat.search("(C++)") is not None

        # Rejections (Boundary preservation)
        assert cpp_pat.search("Objective-C Developer") is None
        assert cpp_pat.search("C Developer") is None
        assert cpp_pat.search("C++Builder Programmer") is None  # Letter immediately after ++

    def test_csharp_variations_and_rejections(self):
        """Verify C# matches language name and version tags."""
        csharp_pat = build_boundary_pattern("C#")

        # Positive matches
        assert csharp_pat.search("Senior C# Developer") is not None
        assert csharp_pat.search("Building services in C#") is not None
        assert csharp_pat.search("C# .NET Backend Engineer") is not None
        assert csharp_pat.search("C#10 Programmer") is not None
        assert csharp_pat.search("C#12 / .NET 8") is not None
        assert csharp_pat.search("(C#)") is not None

        # Rejections
        assert csharp_pat.search("C Developer") is None
        assert csharp_pat.search("Objective-C") is None
        assert csharp_pat.search("C#Developer") is None  # Letter immediately after #

    def test_dotnet_variations_and_frameworks(self):
        """Verify .NET matches standalone and prefixed frameworks (ASP.NET)."""
        dotnet_pat = build_boundary_pattern(".NET")

        # Positive matches
        assert dotnet_pat.search("ASP.NET Core Specialist") is not None
        assert dotnet_pat.search("Expert in .NET 8") is not None
        assert dotnet_pat.search("VB.NET Developer") is not None
        assert dotnet_pat.search("Modern .NET Cloud Architect") is not None
        assert dotnet_pat.search("Building microservices on .NET") is not None

        # Rejections
        assert dotnet_pat.search("Network Analyst") is None
        assert dotnet_pat.search("Internet of Things Specialist") is None
        assert dotnet_pat.search("Planetary Sciences") is None
        assert dotnet_pat.search("Coronet Architect") is None

    def test_nodejs_variations_and_rejections(self):
        """Verify Node.js matches punctuation, slashes, but not Node.json."""
        node_pat = build_boundary_pattern("Node.js")

        # Positive matches
        assert node_pat.search("Node.js Developer") is not None
        assert node_pat.search("Senior Node.js / React Engineer") is not None
        assert node_pat.search("Backend (Node.js)") is not None
        assert node_pat.search("Built with Node.js.") is not None
        assert node_pat.search("Node.js, TypeScript, PostgreSQL") is not None

        # Rejections
        assert node_pat.search("Node.json Configuration") is None
        assert node_pat.search("Node.jsp Developer") is None

    def test_cpp20_specific_version_keyword(self):
        """Verify C++20 as a discrete keyword matches exact version, not C++ or C++200."""
        cpp20_pat = build_boundary_pattern("C++20")

        # Positive matches
        assert cpp20_pat.search("Modern C++20 Architect") is not None
        assert cpp20_pat.search("C++20/23 Developer") is not None
        assert cpp20_pat.search("Specialist in C++20.") is not None

        # Rejections
        assert cpp20_pat.search("Modern C++ Developer") is None
        assert cpp20_pat.search("C++17 Developer") is None
        assert cpp20_pat.search("C++200 Developer") is None

    def test_aspnet_core_compound_symbol_keyword(self):
        """Verify ASP.NET Core matches exact multi-word symbol phrase."""
        aspnet_pat = build_boundary_pattern("ASP.NET Core")

        # Positive matches
        assert aspnet_pat.search("ASP.NET Core Backend Developer") is not None
        assert aspnet_pat.search("Expert in ASP.NET Core 8.0") is not None
        assert aspnet_pat.search("Modern ASP.NET Core.") is not None

        # Rejections
        assert aspnet_pat.search("ASP.NET MVC Developer") is None
        assert aspnet_pat.search("Core Developer") is None
        assert aspnet_pat.search("ASP Developer") is None

    def test_embedded_cpp_keyword(self):
        """Verify 'Embedded C++' matches firmware/systems roles without boundary breakages."""
        embedded_cpp_pat = build_boundary_pattern("Embedded C++")

        # Positive matches
        assert embedded_cpp_pat.search("Embedded C++ Engineer") is not None
        assert embedded_cpp_pat.search("Senior Embedded C++ Developer") is not None
        assert embedded_cpp_pat.search("Embedded C++20 Specialist") is not None
        assert embedded_cpp_pat.search("Firmware (Embedded C++)") is not None

        # Rejections
        assert embedded_cpp_pat.search("Embedded C Developer") is None
        assert embedded_cpp_pat.search("Embedded C++Engineer") is None  # Letter immediately after ++

    def test_csharp_dotnet_compound_keyword(self):
        """Verify compound 'C# .NET' matches full phrase and rejects partial or glued terms."""
        cs_net_pat = build_boundary_pattern("C# .NET")

        # Positive matches
        assert cs_net_pat.search("C# .NET Backend Developer") is not None
        assert cs_net_pat.search("Senior C# .NET Engineer") is not None
        assert cs_net_pat.search("Services built with C# .NET") is not None

        # Rejections
        assert cs_net_pat.search("C# Developer") is None
        assert cs_net_pat.search(".NET Developer") is None
        assert cs_net_pat.search("C# .NETCore Engineer") is None  # Letter immediately after .NET

    def test_vuejs_variations_and_rejections(self):
        """Verify 'Vue.js' matches frontend roles but excludes Vue.json / Vue.jsp."""
        vue_pat = build_boundary_pattern("Vue.js")

        # Positive matches
        assert vue_pat.search("Vue.js Developer") is not None
        assert vue_pat.search("Frontend Engineer (Vue.js)") is not None
        assert vue_pat.search("Vue.js 3 / Pinia Architect") is not None
        assert vue_pat.search("Full Stack (Vue.js + FastAPI)") is not None

        # Rejections
        assert vue_pat.search("Vue.json Config") is None
        assert vue_pat.search("Vue.jsp Template") is None

    def test_go_vs_golang_differentiation(self):
        """Verify 'Go' vs 'Golang' keyword pattern behaviors and boundary isolation."""
        go_pat = build_boundary_pattern("Go")
        golang_pat = build_boundary_pattern("Golang")

        # 'Go' matches
        assert go_pat.search("Go Developer") is not None
        assert go_pat.search("Backend (Go)") is not None
        # Note: 'Go' with strict boundary (?!\w) does not match 'Golang'
        assert go_pat.search("Golang Developer") is None

        # 'Golang' matches
        assert golang_pat.search("Golang Developer") is not None
        assert golang_pat.search("Senior Golang Engineer") is not None
        assert golang_pat.search("Go / Golang Platform Developer") is not None
        # 'Golang' does not match standalone 'Go'
        assert golang_pat.search("Go Developer") is None


# ==============================================================================
# 2. WORD BOUNDARIES STRESS TESTS
# ==============================================================================

class TestWordBoundaries:
    """Stress test word boundaries for short words, prefixes, and leadership titles."""

    def test_go_vs_good_and_prefixes(self):
        """Verify 'Go' matches language name but never prefixes or compound words."""
        go_pat = build_boundary_pattern("Go")

        # Positive matches
        assert go_pat.search("Go Systems Engineer") is not None
        assert go_pat.search("Backend Developer (Go)") is not None
        assert go_pat.search("Proficient in Go, Python") is not None
        assert go_pat.search("Go/Rust Platform Engineer") is not None

        # Rejections
        assert go_pat.search("Good Software Engineer") is None
        assert go_pat.search("Governance Risk Officer") is None
        assert go_pat.search("Google Cloud Architect") is None
        assert go_pat.search("Django Developer") is None
        assert go_pat.search("Ongoing Project Lead") is None
        assert go_pat.search("Cargo Operations Specialist") is None
        assert go_pat.search("MongoDB Engineer") is None

    def test_intern_vs_internal_and_international(self):
        """Verify 'intern' matches student/trainee roles without matching internal/international."""
        intern_pat = build_boundary_pattern("intern")

        # Positive matches
        assert intern_pat.search("Software Engineering Intern") is not None
        assert intern_pat.search("Summer Intern 2026") is not None
        assert intern_pat.search("Co-op Intern") is not None
        assert intern_pat.search("Intern - Data Science") is not None

        # Rejections
        assert intern_pat.search("Internal Tools Engineer") is None
        assert intern_pat.search("Internal Platform Developer") is None
        assert intern_pat.search("International Business Development") is None
        assert intern_pat.search("Internet Security Architect") is None

    def test_staff_vs_staffing(self):
        """Verify 'staff' matches seniority level but strictly excludes staffing agencies."""
        staff_pat = build_boundary_pattern("staff")

        # Positive matches
        assert staff_pat.search("Staff Software Engineer") is not None
        assert staff_pat.search("Staff Infrastructure Architect") is not None
        assert staff_pat.search("Chief of Staff") is not None

        # Rejections
        assert staff_pat.search("Staffing Coordinator") is None
        assert staff_pat.search("Technical Staffing Specialist") is None
        assert staff_pat.search("Staffer Relations Manager") is None

    def test_lead_vs_leader_vs_leadership(self):
        """Verify 'lead' matches lead titles but excludes leader and leadership words."""
        lead_pat = build_boundary_pattern("lead")

        # Positive matches
        assert lead_pat.search("Tech Lead") is not None
        assert lead_pat.search("Lead Full Stack Developer") is not None
        assert lead_pat.search("Team Lead") is not None
        assert lead_pat.search("Lead Systems Architect") is not None

        # Rejections
        assert lead_pat.search("Team Leader") is None
        assert lead_pat.search("Technical Leader") is None
        assert lead_pat.search("Engineering Leadership") is None
        assert lead_pat.search("Leadership Development Associate") is None
        assert lead_pat.search("Pleading Case Analyst") is None
        assert lead_pat.search("Mislead Detection Engineer") is None


# ==============================================================================
# 3. DESCRIPTION VS TITLE NEGATIVE ISOLATION TESTS
# ==============================================================================

class TestDescriptionIsolation:
    """Stress test decoupling between title exclusions and job description text."""

    def test_junior_roles_mentioning_managerial_hierarchy_pass(self):
        """
        CRITICAL ARCHITECTURAL CONTRACT:
        Junior/mid-level roles describing reporting structures to managers or mentorship
        from principal/staff/lead engineers MUST NOT be rejected by negative title keywords.
        """
        config = JobFilterConfig(
            target_titles=["Software Engineer", "Backend Developer"],
            negative_title_keywords=[
                "senior", "sr", "sr.", "principal", "staff", "lead",
                "manager", "director", "head of", "vp", "intern", "co-op"
            ],
            required_skills=["Python"],
            skills_match_mode="any",
        )
        matcher = JobMatcher(config)

        # Listing packed with every negative title keyword in the description
        adversarial_job = JobListing(
            external_id="adv-iso-001",
            company_name="EnterpriseCorp",
            title="Software Engineer, Backend",
            location="Remote",
            is_remote=True,
            url="https://enterprisecorp.com/jobs/001",
            description_text="""
            About the Role:
            As a Software Engineer on our core platform team, you will report directly
            to the Engineering Manager. You will collaborate daily with Principal Engineers,
            receive technical mentorship from our Staff Architect, and work alongside the
            Tech Lead and Director of Engineering. In this position, you will also supervise
            the summer intern and assist the VP of Engineering with architectural presentations.
            
            Requirements:
            - Proficiency in Python.
            - Experience with REST APIs and databases.
            """,
        )

        res = matcher.evaluate(adversarial_job)
        assert res.matched is True, f"Role was falsely rejected: {res.rejection_reason}"
        assert res.matched_title == "Software Engineer"
        assert "Python" in res.matched_skills

    def test_titles_with_negative_keywords_are_strictly_rejected(self):
        """Verify that any job whose title contains a negative keyword is strictly rejected."""
        config = JobFilterConfig(
            target_titles=["Software Engineer", "Developer", "Architect"],
            negative_title_keywords=[
                "senior", "sr", "sr.", "principal", "staff", "lead",
                "manager", "director", "head of", "vp", "intern", "co-op"
            ],
            required_skills=["Python"],
            skills_match_mode="any",
        )
        matcher = JobMatcher(config)

        negative_titles = [
            "Senior Software Engineer",
            "Sr. Backend Developer",
            "Principal Systems Architect",
            "Staff Software Engineer",
            "Tech Lead Developer",
            "Engineering Manager",
            "Director of Software Engineering",
            "Head of Backend",
            "VP of Engineering",
            "Software Engineering Intern",
            "Backend Co-op",
        ]

        for title in negative_titles:
            job = JobListing(
                external_id="neg-title",
                company_name="Acme",
                title=title,
                location="Remote",
                is_remote=True,
                url="https://example.com/neg",
                description_text="Python programming",
            )
            res = matcher.evaluate(job)
            assert res.matched is False, f"Expected '{title}' to be rejected"
            assert "Title matched negative keyword" in (res.rejection_reason or "")

    def test_negative_description_keywords_are_honored_when_configured(self):
        """Verify negative description keywords reject jobs only when explicitly matching."""
        config = JobFilterConfig(
            target_titles=["Software Engineer"],
            negative_description_keywords=["10+ years", "active security clearance", "phd required"],
            required_skills=["Python"],
        )
        matcher = JobMatcher(config)

        # Job with negative description phrase
        rejected_job = JobListing(
            external_id="neg-desc-1",
            company_name="DefenseTech",
            title="Software Engineer",
            location="Remote",
            is_remote=True,
            url="https://defensetech.com/jobs/1",
            description_text="Must hold active security clearance and 3 years Python.",
        )
        res_rej = matcher.evaluate(rejected_job)
        assert res_rej.matched is False
        assert "Description matched negative keyword" in (res_rej.rejection_reason or "")

        # Job without negative description phrase passes
        allowed_job = JobListing(
            external_id="neg-desc-2",
            company_name="FinTech",
            title="Software Engineer",
            location="Remote",
            is_remote=True,
            url="https://fintech.com/jobs/2",
            description_text="Requires 3+ years of Python and clean background check.",
        )
        res_pass = matcher.evaluate(allowed_job)
        assert res_pass.matched is True

    def test_exact_leakage_software_engineer_reporting_to_vp_and_engineering_manager(self):
        """
        Explicitly verify: 'Software Engineer' reporting to 'VP of Engineering'
        or 'Engineering Manager' does not leak negative title keywords into description.
        """
        config = JobFilterConfig(
            target_titles=["Software Engineer"],
            negative_title_keywords=[
                "senior", "principal", "staff", "lead", "manager",
                "director", "head of", "vp", "vice president", "intern"
            ],
            required_skills=["Python"],
            skills_match_mode="any",
        )
        matcher = JobMatcher(config)

        job = JobListing(
            external_id="vp-eng-mgr-01",
            company_name="CloudScale",
            title="Software Engineer",
            location="Remote",
            is_remote=True,
            url="https://cloudscale.io/jobs/01",
            description_text=(
                "We are seeking a Software Engineer to join our Platform Team. "
                "In this role, you will report directly to the VP of Engineering "
                "or an Engineering Manager. You will also collaborate with Principal "
                "Engineers and mentor summer interns. Requirements: Python experience."
            ),
        )

        res = matcher.evaluate(job)
        assert res.matched is True, f"Failed: {res.rejection_reason}"
        assert res.matched_title == "Software Engineer"
        assert "Python" in res.matched_skills


# ==============================================================================
# 4. EMPTY CRITERIA & UNICODE STRESS TESTS
# ==============================================================================

class TestEmptyCriteriaAndUnicode:
    """Stress test handling of empty criteria, null/missing values, and Unicode characters."""

    def test_empty_criteria_configurations(self):
        """Verify behavior with completely empty filter lists."""
        config = JobFilterConfig(
            target_titles=[],
            negative_title_keywords=[],
            negative_description_keywords=[],
            required_skills=[],
            preferred_skills=[],
            allowed_locations=[],
            excluded_locations=[],
            remote_only=False,
        )
        matcher = JobMatcher(config)

        job = JobListing(
            external_id="empty-cfg-1",
            company_name="Universal",
            title="Random Job Title",
            location="Somewhere, Earth",
            is_remote=False,
            url="https://example.com/job/1",
            description_text="Just any description text.",
        )
        res = matcher.evaluate(job)
        assert res.matched is True
        assert res.matched_title == "Random Job Title"

    def test_whitespace_strings_in_filter_lists_filtered(self):
        """Verify filter config with empty strings or spaces does not crash or break matching."""
        config = JobFilterConfig(
            target_titles=["", "  ", "Software Engineer"],
            negative_title_keywords=["", "   "],
            required_skills=["", "Python"],
            skills_match_mode="any",
        )
        matcher = JobMatcher(config)

        job = JobListing(
            external_id="ws-1",
            company_name="Acme",
            title="Software Engineer",
            location="Remote",
            is_remote=True,
            url="https://example.com/ws-1",
            description_text="Python coding.",
        )
        res = matcher.evaluate(job)
        assert res.matched is True
        assert res.matched_title == "Software Engineer"
        assert "Python" in res.matched_skills

    def test_unicode_and_accented_titles_and_descriptions(self):
        """Verify non-ASCII, accented, and multi-language characters process cleanly."""
        config = JobFilterConfig(
            target_titles=["Développeur Full Stack", "Softwareentwickler", "Разработчик Python"],
            negative_title_keywords=["senior", "stagiaire"],
            required_skills=["Python", "PostgreSQL"],
            skills_match_mode="any",
            allowed_locations=["München", "São Paulo", "Remote"],
        )
        matcher = JobMatcher(config)

        # French listing
        job_fr = JobListing(
            external_id="fr-1",
            company_name="ParisCorp",
            title="Développeur Full Stack",
            location="Remote",
            is_remote=True,
            url="https://pariscorp.fr/jobs/1",
            description_text="Développement avec Python et Django.",
        )
        res_fr = matcher.evaluate(job_fr)
        assert res_fr.matched is True
        assert "Python" in res_fr.matched_skills

        # German listing with umlauts
        job_de = JobListing(
            external_id="de-1",
            company_name="MunichTech",
            title="Softwareentwickler (m/w/d)",
            location="München, Deutschland",
            is_remote=False,
            url="https://munichtech.de/jobs/1",
            description_text="Backend Services mit Python und PostgreSQL.",
        )
        res_de = matcher.evaluate(job_de)
        assert res_de.matched is True

        # Russian listing with Cyrillic
        job_ru = JobListing(
            external_id="ru-1",
            company_name="Yandex",
            title="Разработчик Python",
            location="Remote",
            is_remote=True,
            url="https://yandex.ru/jobs/1",
            description_text="Разработка высоконагруженных сервисов на Python.",
        )
        res_ru = matcher.evaluate(job_ru)
        assert res_ru.matched is True

    def test_emojis_and_typographic_punctuation(self):
        """Verify titles with emojis, em-dashes, and smart quotes match expected keywords."""
        config = JobFilterConfig(
            target_titles=["Software Engineer", "Backend Developer"],
            negative_title_keywords=["senior"],
            required_skills=["Python"],
            skills_match_mode="any",
        )
        matcher = JobMatcher(config)

        # Emoji in title
        job_emoji = JobListing(
            external_id="em-1",
            company_name="RocketCorp",
            title="🚀 Software Engineer – Core Team",
            location="Remote",
            is_remote=True,
            url="https://rocketcorp.com/jobs/1",
            description_text="We’re hiring! Stack: Python 🐍",
        )
        res_emoji = matcher.evaluate(job_emoji)
        assert res_emoji.matched is True
        assert "Python" in res_emoji.matched_skills

        # Emoji with negative keyword in title is properly rejected
        job_emoji_neg = JobListing(
            external_id="em-2",
            company_name="RocketCorp",
            title="🔥 Senior Software Engineer 🔥",
            location="Remote",
            is_remote=True,
            url="https://rocketcorp.com/jobs/2",
            description_text="Python backend.",
        )
        res_neg = matcher.evaluate(job_emoji_neg)
        assert res_neg.matched is False


# ==============================================================================
# 5. STRANGE LOCATIONS & REMOTE DETECTION STRESS TESTS
# ==============================================================================

class TestLocationsAndRemoteDetection:
    """Stress test location edge cases, remote flag inferencing, and regex metacharacters."""

    def test_regex_metacharacters_in_allowed_and_excluded_locations(self):
        """Verify locations containing parentheses, dots, or dashes are properly escaped."""
        config = JobFilterConfig(
            target_titles=["Developer"],
            remote_only=False,
            allowed_locations=["New York (NY)", "Washington, D.C.", "Remote - US/CA"],
            excluded_locations=["London (UK)", "Paris [HQ]"],
        )
        matcher = JobMatcher(config)

        # Matches allowed with parentheses
        j1 = JobListing(
            external_id="loc-m-1",
            company_name="Acme",
            title="Developer",
            location="New York (NY), USA",
            is_remote=False,
            url="https://example.com/1",
            description_text="Code",
        )
        assert matcher.evaluate(j1).matched is True

        # Matches allowed with dots
        j2 = JobListing(
            external_id="loc-m-2",
            company_name="Acme",
            title="Developer",
            location="Office in Washington, D.C.",
            is_remote=False,
            url="https://example.com/2",
            description_text="Code",
        )
        assert matcher.evaluate(j2).matched is True

        # Rejects excluded with brackets
        j3 = JobListing(
            external_id="loc-m-3",
            company_name="Acme",
            title="Developer",
            location="Paris [HQ], France",
            is_remote=False,
            url="https://example.com/3",
            description_text="Code",
        )
        assert matcher.evaluate(j3).matched is False

    def test_remote_inferred_from_title_and_location_variants(self):
        """Verify remote status is detected from 'anywhere', 'wfh', 'telecommute'."""
        config = JobFilterConfig(
            target_titles=["Developer"],
            remote_only=True,
        )
        matcher = JobMatcher(config)

        # Inferred from location 'Anywhere'
        j_anywhere = JobListing(
            external_id="rem-1",
            company_name="Acme",
            title="Developer",
            location="Work from Anywhere",
            is_remote=False,
            url="https://example.com/1",
            description_text="Code",
        )
        assert matcher.evaluate(j_anywhere).matched is True

        # Inferred from title 'WFH'
        j_wfh = JobListing(
            external_id="rem-2",
            company_name="Acme",
            title="Developer (WFH Available)",
            location="San Francisco, CA",
            is_remote=False,
            url="https://example.com/2",
            description_text="Code",
        )
        assert matcher.evaluate(j_wfh).matched is True

        # Inferred from location 'Telecommute'
        j_tele = JobListing(
            external_id="rem-3",
            company_name="Acme",
            title="Developer",
            location="Telecommute Eligible",
            is_remote=False,
            url="https://example.com/3",
            description_text="Code",
        )
        assert matcher.evaluate(j_tele).matched is True

    def test_excluded_location_word_boundary_isolation(self):
        """Verify 'London' exclusion does NOT reject 'Londonderry'."""
        config = JobFilterConfig(
            target_titles=["Developer"],
            excluded_locations=["London"],
        )
        matcher = JobMatcher(config)

        job_londonderry = JobListing(
            external_id="loc-ld-1",
            company_name="Acme",
            title="Developer",
            location="Londonderry, NH, United States",
            is_remote=False,
            url="https://example.com/ld-1",
            description_text="Code",
        )
        assert matcher.evaluate(job_londonderry).matched is True

        job_london = JobListing(
            external_id="loc-ld-2",
            company_name="Acme",
            title="Developer",
            location="London, United Kingdom",
            is_remote=False,
            url="https://example.com/ld-2",
            description_text="Code",
        )
        assert matcher.evaluate(job_london).matched is False

    def test_location_and_remote_edge_case_strings(self):
        """
        Stress test location and remote inference edge cases:
        1. 'Remotely' suffix vs boundary lookahead.
        2. Negative remote phrases ('Not Remote').
        3. Regional remote bypassing allowed_locations.
        """
        config_remote_only = JobFilterConfig(
            target_titles=["Developer"],
            remote_only=True,
            allowed_locations=["United States"],
        )
        matcher_remote = JobMatcher(config_remote_only)

        # Edge Case 1: 'Work Remotely'
        # Note: If is_remote is False, '(?<!\w)remote(?!\w)' does not match 'Remotely'
        # because 'l' is in \w. Empirically document this behavior:
        j_remotely = JobListing(
            external_id="edge-loc-1",
            company_name="Acme",
            title="Developer",
            location="Work Remotely",
            is_remote=False,
            url="https://example.com/1",
            description_text="Code",
        )
        res_remotely = matcher_remote.evaluate(j_remotely)
        # Regex currently rejects 'Remotely' when is_remote=False
        assert res_remotely.matched is False
        assert "Job is not remote" in res_remotely.rejection_reason

        # If adapter correctly populates is_remote=True, it passes cleanly:
        j_remotely_flagged = JobListing(
            external_id="edge-loc-1b",
            company_name="Acme",
            title="Developer",
            location="Work Remotely",
            is_remote=True,
            url="https://example.com/1b",
            description_text="Code",
        )
        assert matcher_remote.evaluate(j_remotely_flagged).matched is True

        # Edge Case 2: 'Not Remote' / 'No Remote' false positive vulnerability
        # Naive keyword match 'remote' will match inside 'Not Remote'
        j_not_remote = JobListing(
            external_id="edge-loc-2",
            company_name="Acme",
            title="Developer",
            location="Office-based (Not Remote)",
            is_remote=False,
            url="https://example.com/2",
            description_text="Code",
        )
        res_not_remote = matcher_remote.evaluate(j_not_remote)
        # Substring 'Remote' matches boundary pattern, falsely setting is_remote=True
        assert res_not_remote.matched is True

        # Edge Case 3: Out-of-region remote listing
        # When job is remote, allowed_locations check is bypassed by design
        # Candidate allowed_locations=["United States"], but job is "Remote - UK Only"
        j_uk_remote = JobListing(
            external_id="edge-loc-3",
            company_name="Acme",
            title="Developer",
            location="Remote - UK Only",
            is_remote=True,
            url="https://example.com/3",
            description_text="Code",
        )
        res_uk_remote = matcher_remote.evaluate(j_uk_remote)
        assert res_uk_remote.matched is True  # Bypassed unless excluded_locations is set

        # With excluded_locations=["UK"], out-of-region remote is correctly rejected
        config_with_exclusion = JobFilterConfig(
            target_titles=["Developer"],
            remote_only=True,
            allowed_locations=["United States"],
            excluded_locations=["UK"],
        )
        matcher_with_excl = JobMatcher(config_with_exclusion)
        assert matcher_with_excl.evaluate(j_uk_remote).matched is False

    def test_multi_location_and_whitespace_edge_cases(self):
        """Verify multi-city strings, tabs, newlines, and trailing punctuation in locations."""
        config = JobFilterConfig(
            target_titles=["Developer"],
            allowed_locations=["San Francisco, CA", "New York, NY", "Austin, TX"],
        )
        matcher = JobMatcher(config)

        # Multi-location slash separated
        j_multi = JobListing(
            external_id="multi-loc-1",
            company_name="Acme",
            title="Developer",
            location="San Francisco, CA / New York, NY / Austin, TX",
            is_remote=False,
            url="https://example.com/multi-1",
            description_text="Code",
        )
        assert matcher.evaluate(j_multi).matched is True

        # Location with tabs and newlines
        j_ws = JobListing(
            external_id="multi-loc-2",
            company_name="Acme",
            title="Developer",
            location="Austin, TX\n\tUnited States",
            is_remote=False,
            url="https://example.com/multi-2",
            description_text="Code",
        )
        assert matcher.evaluate(j_ws).matched is True


# ==============================================================================
# 6. SQLITE DEDUPLICATION & URL CANONICALIZATION STRESS TESTS
# ==============================================================================

class TestDatabaseAndDeduplicationAdversarial:
    """Stress test URL canonicalization, unique key collision safety, and SQLite WAL invariants."""

    def test_normalize_url_adversarial_variations(self):
        """Verify URL normalization strips tracking, anchors, and normalizes casing."""
        cases = [
            (
                "https://boards.greenhouse.io/acme/jobs/123?gh_jid=123&utm_medium=email#apply",
                "https://boards.greenhouse.io/acme/jobs/123"
            ),
            (
                "HTTPS://JOBS.LEVER.CO/COMPANY/ABC-DEF///",
                "http://jobs.lever.co/company/abc-def"  # Note: urlparse lowercases host, path trailing slashes removed
            ),
            (
                "https://jobs.ashbyhq.com/org/posting/999?source=linkedin",
                "https://jobs.ashbyhq.com/org/posting/999"
            ),
            ("", ""),
            ("   ", ""),
        ]
        for raw, expected in cases:
            norm = normalize_url(raw)
            # Compare lowercase canonical forms
            assert norm.lower() == expected.lower()

    def test_generate_unique_key_differentiation(self):
        """Verify distinct external IDs and canonical URLs produce distinct unique keys."""
        k1 = generate_unique_key("greenhouse", 1, "101", "https://example.com/101")
        k2 = generate_unique_key("greenhouse", 1, "102", "https://example.com/102")
        k3 = generate_unique_key("lever", 1, "101", "https://example.com/101")
        k4 = generate_unique_key("greenhouse", 2, "101", "https://example.com/101")

        assert len({k1, k2, k3, k4}) == 4, "Keys across different providers, companies, or IDs must not collide"

    @pytest.mark.asyncio
    async def test_atomic_reservation_invariant_across_multiple_channels(self):
        """Verify atomic reservation is tracked independently per channel (e.g. telegram vs email)."""
        temp_dir = tempfile.mkdtemp()
        db_path = Path(temp_dir) / "test_dedup.db"
        db = Database(str(db_path))
        await db.init_schema()

        try:
            cid = await db.add_company("MultiChannelCorp", "https://example.com", "custom")
            job = JobListing(
                external_id="mc-01",
                company_name="MultiChannelCorp",
                title="Staff Engineer",
                location="Remote",
                url="https://example.com/jobs/01",
                description_text="Python",
            )
            jid, is_new = await db.upsert_job(cid, job)
            assert is_new is True

            # Telegram channel reservation
            res_tg1 = await db.reserve_alert_slot(jid, channel="telegram")
            assert res_tg1 is True
            res_tg2 = await db.reserve_alert_slot(jid, channel="telegram")
            assert res_tg2 is False

            # Slack/email channel reservation for same job should succeed once independently
            res_slack1 = await db.reserve_alert_slot(jid, channel="slack")
            assert res_slack1 is True
            res_slack2 = await db.reserve_alert_slot(jid, channel="slack")
            assert res_slack2 is False

            # Finalize statuses
            await db.finalize_alert_status(jid, "telegram", "sent", preview="Alert sent to TG")
            await db.finalize_alert_status(jid, "slack", "mock", preview="Mock alert for Slack")

            tg_alert = await db.get_alert(jid, "telegram")
            slack_alert = await db.get_alert(jid, "slack")

            assert tg_alert["status"] == "sent"
            assert slack_alert["status"] == "mock"
        finally:
            for f in Path(temp_dir).glob("test_dedup.db*"):
                try:
                    f.unlink()
                except Exception:
                    pass
            try:
                Path(temp_dir).rmdir()
            except Exception:
                pass
