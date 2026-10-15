"""
Job Matching & Filtering Engine for CareerPulse.

Implements boundary lookaround regex matching (?<!\\w)...(?!\\w) to safely handle
symbol-laden tech keywords (C++, C#, .NET) and word boundaries (Go vs Good, Intern vs Internal).
Provides strict negative keyword exclusions decoupled between job titles and descriptions.
"""

import html
import re
from typing import List, Optional

from .models import FilterResult, JobFilterConfig, JobListing


def build_boundary_pattern(keyword: str) -> re.Pattern:
    """
    Build a regex pattern using lookarounds (?<!\\w)...(?!\\w).

    Correctly matches symbols like C++, C#, .NET, and handles word boundaries
    without standard \\b edge case failures on punctuation or surrounding characters.
    - If keyword starts with a symbol (like .NET), it matches even when preceded by text (e.g. ASP.NET).
    - If keyword ends with a symbol (like C++, C#), it allows version suffixes (e.g. C++20).
    - For regular words (like Go, intern), strict \\w boundaries prevent false matches (Good, Internal).
    """
    kw = keyword.strip()
    escaped = re.escape(kw)

    # Prefix boundary: If keyword starts with alphanumeric, enforce (?<!\w)
    prefix = r'(?<!\w)' if re.match(r'^\w', kw) else r''

    # Suffix boundary: If keyword ends with non-alphanumeric (like C++, C#), allow version numbers (C++20)
    suffix = r'(?!\w)' if re.search(r'\w$', kw) else r'(?![a-zA-Z])'

    return re.compile(rf'{prefix}{escaped}{suffix}', re.IGNORECASE)


def strip_html_tags(text: str) -> str:
    """Remove HTML tags, unescape entities, and collapse excess whitespace."""
    if not text:
        return ""
    clean = re.sub(r'<[^>]+>', ' ', text)
    clean = html.unescape(clean)
    return re.sub(r'\s+', ' ', clean).strip()


class JobMatcher:
    """
    Evaluates JobListing instances against configurable JobFilterConfig rules.

    Enforces:
    1. Fast negative title rejection short-circuit.
    2. Optional negative description rejection.
    3. Location and remote workplace constraints.
    4. Target job title matching.
    5. Required and preferred tech stack skills matching ('any', 'all', 'none').
    6. Match relevance scoring.
    """

    def __init__(self, config: JobFilterConfig):
        self.config = config
        self._neg_title_patterns = [
            build_boundary_pattern(k) for k in config.negative_title_keywords if k and k.strip()
        ]
        self._neg_desc_patterns = [
            build_boundary_pattern(k) for k in config.negative_description_keywords if k and k.strip()
        ]
        self._target_title_patterns = [
            build_boundary_pattern(k) for k in config.target_titles if k and k.strip()
        ]
        self._req_skill_patterns = {
            k: build_boundary_pattern(k) for k in config.required_skills if k and k.strip()
        }
        self._pref_skill_patterns = {
            k: build_boundary_pattern(k) for k in config.preferred_skills if k and k.strip()
        }

    def evaluate(self, job: JobListing) -> FilterResult:
        """
        Evaluate a single job listing against filter configuration.

        Returns FilterResult with matched boolean, rejection_reason if False,
        and matched details + score if True.
        """
        title = (job.title or "").strip()
        desc = strip_html_tags(job.description_text or "")
        location = (job.location or "").strip()
        search_surface = f"{title}\n{desc}"

        # 1. Negative Title Keyword Check (Strict Exclusion on Title Only)
        for pattern in self._neg_title_patterns:
            match = pattern.search(title)
            if match:
                return FilterResult(
                    matched=False,
                    rejection_reason=f"Title matched negative keyword '{match.group(0)}'"
                )

        # 2. Negative Description Keyword Check (if configured)
        for pattern in self._neg_desc_patterns:
            match = pattern.search(desc)
            if match:
                return FilterResult(
                    matched=False,
                    rejection_reason=f"Description matched negative keyword '{match.group(0)}'"
                )

        # 3. Location & Remote Filter Check
        is_remote = bool(job.is_remote) or bool(
            re.search(r'(?<!\w)(remote|anywhere|telecommute|wfh)(?!\w)', f"{title} {location}", re.IGNORECASE)
        )

        if self.config.remote_only and not is_remote:
            return FilterResult(
                matched=False,
                rejection_reason=f"Job is not remote (Location: '{location}')"
            )

        if self.config.excluded_locations:
            for excl in self.config.excluded_locations:
                if excl.strip() and re.search(rf'(?<!\w){re.escape(excl.strip())}(?!\w)', location, re.IGNORECASE):
                    return FilterResult(
                        matched=False,
                        rejection_reason=f"Location matches excluded pattern '{excl}'"
                    )

        if self.config.allowed_locations and not is_remote:
            matched_loc = False
            for allowed in self.config.allowed_locations:
                if allowed.strip() and re.search(rf'(?<!\w){re.escape(allowed.strip())}(?!\w)', location, re.IGNORECASE):
                    matched_loc = True
                    break
            if not matched_loc:
                return FilterResult(
                    matched=False,
                    rejection_reason=f"Location '{location}' not in allowed locations"
                )

        # 4. Target Job Title Check
        matched_title: Optional[str] = None
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
            matched_title = title if title else "Untitled"

        # 5. Skills Matching (Required & Preferred)
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
                    rejection_reason=f"Missing required skills: {', '.join(sorted(missing))}"
                )
        elif self.config.skills_match_mode == "any":
            if self._req_skill_patterns and len(matched_req_skills) == 0:
                return FilterResult(
                    matched=False,
                    rejection_reason="Did not match any required skills"
                )

        # Preferred skills (used for scoring and highlights)
        for skill, pattern in self._pref_skill_patterns.items():
            if pattern.search(search_surface) and skill not in matched_skills:
                matched_skills.append(skill)

        # 6. Match Relevance Scoring
        score = 1.0  # Base match baseline
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
            match_score=round(score, 2),
        )
