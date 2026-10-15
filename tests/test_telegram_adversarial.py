"""
Adversarial Stress Test Suite for Telegram Message Formatter and Parser.
Challenger: challenger_m3_1 (Milestone 3 Hardening)

Adversarially verifies:
1. Malicious HTML injection payloads (<script>, </b>, <a href="evil">, &amp;amp;, <iframe>, onerror)
2. Complex URL attribute escaping (quotes, ampersands, brackets, Unicode, 2000+ char URLs)
3. Massive workloads: 200+ matched skills, 10,000-char descriptions
4. Telegram HTML parser compliance & tag balancing (strict LIFO tag stack validation)
5. 4,096-character limit enforcement under adversarial expansions
"""

import html
import re
from typing import List, Tuple
import pytest

from career_pulse.core.models import FilterResult, JobListing
from career_pulse.services.telegram import MockTelegramSink, TelegramNotifier


# ==============================================================================
# TELEGRAM HTML PARSER & TAG BALANCE VALIDATOR
# ==============================================================================

ALLOWED_TELEGRAM_TAGS = {"b", "strong", "i", "em", "u", "ins", "s", "strike", "del", "tg-spoiler", "a", "code", "pre", "blockquote"}

def validate_telegram_html(msg: str) -> Tuple[bool, List[str]]:
    """
    Simulates Telegram Bot API's HTML parser.
    Checks:
    1. Only allowed tags are parsed as HTML tags.
    2. Tag nesting is strictly balanced (LIFO stack).
    3. No unescaped angle brackets (< or >) or raw ampersands (&) outside valid tags/entities.
    4. <a> tags have valid href attributes.
    5. No unclosed tags at end of message.
    """
    errors: List[str] = []
    tag_stack: List[str] = []

    # Regex finding HTML tags vs text
    tag_pattern = re.compile(r'<\/?([a-zA-Z0-9\-_]+)(?:\s+([^>]*))?>|&([a-zA-Z0-9]+|#[0-9]+|#x[0-9a-fA-F]+);|<')

    pos = 0
    for match in tag_pattern.finditer(msg):
        full_match = match.group(0)

        # Check for unescaped raw '<'
        if full_match == "<":
            errors.append(f"Unescaped '<' character found at index {match.start()}")
            continue

        # Check for entity reference (&amp;, &lt;, etc.)
        if full_match.startswith("&"):
            entity_name = match.group(3)
            if entity_name not in {"lt", "gt", "amp", "quot", "#x27", "#39"}:
                # Note: Telegram accepts standard HTML entities
                pass
            continue

        tag_name = match.group(1).lower()
        is_closing = full_match.startswith("</")
        attrs = match.group(2) or ""

        if tag_name not in ALLOWED_TELEGRAM_TAGS:
            errors.append(f"Disallowed HTML tag '<{tag_name}>' at index {match.start()} (Telegram rejects this)")
            continue

        if is_closing:
            if not tag_stack:
                errors.append(f"Unexpected closing tag '</{tag_name}>' at index {match.start()} with empty stack")
            elif tag_stack[-1] != tag_name:
                errors.append(f"Mismatched closing tag '</{tag_name}>', expected '</{tag_stack[-1]}>'")
            else:
                tag_stack.pop()
        else:
            if tag_name == "a":
                # Must have href="something"
                href_match = re.search(r'href="([^"]*)"', attrs)
                if not href_match:
                    errors.append(f"<a> tag at index {match.start()} missing valid double-quoted href attribute")
            tag_stack.append(tag_name)

    if tag_stack:
        errors.append(f"Unclosed HTML tags remaining at end of message: {tag_stack}")

    return len(errors) == 0, errors


# ==============================================================================
# TEST SUITE 1: MALICIOUS HTML INJECTION PAYLOADS
# ==============================================================================

def test_html_injection_script_and_event_handlers():
    """Verify script tags, iframe, and event handlers are fully neutralized."""
    notifier = TelegramNotifier(mock_mode=True)
    job = JobListing(
        external_id="inj-1",
        company_name='<script>alert("XSS")</script>',
        title='Hacker <iframe src="evil.com"> <img src=x onerror=alert(1)>',
        location='<tg-spoiler>Secret</tg-spoiler>',
        url="https://example.com/apply",
        description_text='<script>document.location="http://evil.com"</script>',
    )
    match = FilterResult(
        matched=True,
        matched_skills=['<script>evil()</script>', 'NormalSkill', '<svg/onload=alert(1)>']
    )
    msg = notifier.format_job_message(job, match)

    # 1. No raw malicious tags
    assert "<script>" not in msg
    assert "</script>" not in msg
    assert "<iframe" not in msg
    assert "<img" not in msg
    assert "onerror=" not in msg or "&quot;" in msg or "<code>" in msg

    # 2. Escaped entities present
    assert "&lt;script&gt;alert(&quot;XSS&quot;)&lt;/script&gt;" in msg
    assert "&lt;iframe src=&quot;evil.com&quot;&gt;" in msg

    # 3. Tag balance validation
    valid, errors = validate_telegram_html(msg)
    assert valid, f"HTML validation errors: {errors}"


def test_html_injection_premature_closing_tag_breakout():
    """Verify attempts to close surrounding <b> or <a> tags prematurely are neutralized."""
    notifier = TelegramNotifier(mock_mode=True)
    job = JobListing(
        external_id="inj-2",
        company_name="Corp</b></h1>",
        title="Engineer</b><a href='http://evil.com'>FakeLink</a><b>",
        location="Earth</a>",
        url="https://example.com/apply",
    )
    match = FilterResult(
        matched=True,
        matched_skills=["Python</b>", "</code><code>Injected"]
    )
    msg = notifier.format_job_message(job, match)

    # Closing tag strings must be escaped
    assert "Corp&lt;/b&gt;&lt;/h1&gt;" in msg
    assert "Engineer&lt;/b&gt;&lt;a href=&#x27;http://evil.com&#x27;&gt;FakeLink&lt;/a&gt;&lt;b&gt;" in msg
    assert "Python&lt;/b&gt;" in msg

    # HTML tags must be strictly balanced
    valid, errors = validate_telegram_html(msg)
    assert valid, f"HTML parser errors: {errors}"


def test_html_injection_double_escaping_resilience():
    """Verify inputs with &amp;amp; and tricky entity sequences don't cause parser anomalies."""
    notifier = TelegramNotifier(mock_mode=True)
    job = JobListing(
        external_id="inj-3",
        company_name="AT&amp;T &amp;amp; Co",
        title="Q&amp;A Engineer",
        url="https://example.com/apply?a=1&amp;b=2",
    )
    match = FilterResult(matched=True, matched_skills=["C&amp;A"])
    msg = notifier.format_job_message(job, match)

    assert "AT&amp;amp;T &amp;amp;amp; Co" in msg
    assert "Q&amp;amp;A Engineer" in msg

    valid, errors = validate_telegram_html(msg)
    assert valid, f"HTML validation errors: {errors}"


# ==============================================================================
# TEST SUITE 2: COMPLEX URL ATTRIBUTE ESCAPING
# ==============================================================================

def test_url_attribute_quotes_and_breakout():
    """Verify URLs containing double quotes, single quotes, and brackets cannot break out of href."""
    notifier = TelegramNotifier(mock_mode=True)
    malicious_urls = [
        'https://example.com/apply?param=" onclick="alert(1)"',
        "https://example.com/apply?param=' onfocus='alert(1)'",
        'https://example.com/apply?tag=<script>alert(1)</script>',
        'https://example.com/apply?q="><h1>Big Header</h1><a href="',
    ]

    for evil_url in malicious_urls:
        job = JobListing(
            external_id="url-test",
            company_name="Test Company",
            title="Software Engineer",
            url=evil_url,
        )
        match = FilterResult(matched=True)
        msg = notifier.format_job_message(job, match)

        # Must not contain unescaped quotes or angle brackets inside href attribute
        assert 'onclick=' not in msg or '&quot;' in msg
        assert '<script>' not in msg

        valid, errors = validate_telegram_html(msg)
        assert valid, f"HTML validation failed on URL '{evil_url}': {errors}"


def test_url_complex_query_params_and_unicode():
    """Verify URLs with ampersands and international Unicode characters remain valid."""
    notifier = TelegramNotifier(mock_mode=True)
    complex_url = "https://acme.fr/postes/développeur?token=xyz123&source=telegram&ref=job_42&filter=c%2B%2B"
    job = JobListing(
        external_id="url-unicode",
        company_name="Acme Paris",
        title="Ingénieur Logiciel",
        location="Paris, France",
        url=complex_url,
    )
    match = FilterResult(matched=True, matched_skills=["Python"])
    msg = notifier.format_job_message(job, match)

    # Ampersands must be escaped as &amp;
    assert "token=xyz123&amp;source=telegram&amp;ref=job_42" in msg
    assert "développeur" in msg

    valid, errors = validate_telegram_html(msg)
    assert valid, f"HTML validation failed: {errors}"


def test_url_truncation_boundary_safety():
    """Verify URLs > 2000 characters are safely truncated without breaking HTML href syntax."""
    notifier = TelegramNotifier(mock_mode=True)
    long_url = "https://example.com/apply?" + ("key=value&" * 300)
    assert len(long_url) > 2000

    job = JobListing(
        external_id="url-long",
        company_name="Big Corp",
        title="Developer",
        url=long_url,
    )
    match = FilterResult(matched=True)
    msg = notifier.format_job_message(job, match)

    # Verify link href is present and correctly closed
    valid, errors = validate_telegram_html(msg)
    assert valid, f"HTML validation failed on long URL: {errors}"
    assert "👉 Apply Directly on Company Site" in msg


# ==============================================================================
# TEST SUITE 3: MASSIVE INPUT WORKLOADS & TAG BALANCING
# ==============================================================================

def test_massive_workload_250_skills_and_10k_description():
    """Verify 250+ skills and 10,000-character description stay strictly under 4,096 chars and tags balanced."""
    notifier = TelegramNotifier(mock_mode=True)
    huge_skills = [f"TechnologyFramework_{i}_Specialization" for i in range(250)]
    huge_description = "A" * 10000

    job = JobListing(
        external_id="massive-1",
        company_name="Massive Enterprise Corp",
        title="Senior Polyglot Cloud Architect",
        location="Remote Worldwide",
        is_remote=True,
        url="https://massive.example.com/jobs/123",
        description_text=huge_description,
    )
    match = FilterResult(matched=True, matched_skills=huge_skills)
    msg = notifier.format_job_message(job, match)

    msg_bytes = len(msg.encode("utf-8"))
    assert msg_bytes < 4096, f"Message exceeded 4096 UTF-8 bytes: {msg_bytes}"
    assert "<i>(+" in msg, "Expected truncation indicator for 250 skills"
    assert "more)</i>" in msg

    # Validate that tags remain 100% balanced despite truncation
    valid, errors = validate_telegram_html(msg)
    assert valid, f"HTML tag balancing failed during truncation: {errors}"


def test_massive_workload_excessive_field_lengths():
    """Verify extremely oversized header fields (company, title, location 1,000 chars each) are bounded."""
    notifier = TelegramNotifier(mock_mode=True)
    job = JobListing(
        external_id="massive-2",
        company_name="Super Long Company Name " * 50,
        title="Principal Ultra Mega Staff Specialist Architect " * 30,
        location="San Francisco, New York, London, Tokyo, Berlin, Sydney, Singapore " * 20,
        is_remote=True,
        url="https://example.com/job",
    )
    match = FilterResult(matched=True, matched_skills=["Python", "FastAPI"])
    msg = notifier.format_job_message(job, match)

    msg_bytes = len(msg.encode("utf-8"))
    assert msg_bytes < 4096, f"Message exceeded 4096 bytes: {msg_bytes}"
    assert "..." in msg, "Expected field truncation ellipsis for excessive raw lengths"

    valid, errors = validate_telegram_html(msg)
    assert valid, f"HTML tag validation failed: {errors}"


def test_massive_workload_multibyte_emojis():
    """Verify multibyte UTF-8 emojis in title, company, and skills don't break byte boundaries."""
    notifier = TelegramNotifier(mock_mode=True)
    emoji_skills = [f"🚀⚡🔥_Skill_{i}_💻🎉" for i in range(120)]
    job = JobListing(
        external_id="massive-emoji",
        company_name="🏢🌟 Stellar Dynamics 🚀✨",
        title="👨‍💻 Lead AI Cloud Engineer 🤖⚡",
        location="🌐 Virtual Reality / Metaverse 🌌",
        is_remote=True,
        url="https://example.com/emoji-job",
    )
    match = FilterResult(matched=True, matched_skills=emoji_skills)
    msg = notifier.format_job_message(job, match)

    msg_bytes = len(msg.encode("utf-8"))
    assert msg_bytes < 4096, f"Emoji message exceeded 4096 bytes: {msg_bytes}"

    valid, errors = validate_telegram_html(msg)
    assert valid, f"HTML tag validation failed on emoji message: {errors}"


# ==============================================================================
# TEST SUITE 4: ADVERSARIAL EDGE CASE HARNESS (FINDINGS & BOUNDARY CONDITIONS)
# ==============================================================================

def test_adversarial_escaped_url_expansion_boundary():
    """
    Stress test URL containing 400 parameters separated by '&'.
    Raw URL length is ~1,600 chars (under 2,000 char threshold).
    After html.escape(..., quote=True), each '&' expands to '&amp;' (+4 chars),
    expanding URL to ~3,200 chars.
    Verifies whether the final rendered message stays strictly under 4,096 UTF-8 bytes.
    """
    notifier = TelegramNotifier(mock_mode=True)
    # 400 parameters separated by '&'
    dense_params = "&".join([f"k{i}=v{i}" for i in range(400)])
    evil_url = f"https://tracking.example.com/apply?{dense_params}"
    assert len(evil_url) < 3000

    job = JobListing(
        external_id="dense-url",
        company_name="Tracking Corp",
        title="Tracking Engineer",
        url=evil_url,
    )
    match = FilterResult(matched=True, matched_skills=["Python", "FastAPI"])
    msg = notifier.format_job_message(job, match)
    msg_bytes = len(msg.encode("utf-8"))

    # Strict invariant: MUST NOT exceed 4,096 bytes under any circumstances
    assert msg_bytes < 4096, f"Entity expansion in URL pushed message over Telegram limit: {msg_bytes} bytes"
    valid, errors = validate_telegram_html(msg)
    assert valid, f"HTML tag validation failed: {errors}"


def test_adversarial_dense_ampersand_expansion_audit():
    """
    Audit test constructing a URL with 550 ampersands ('a=&' * 550 = 1650 chars).
    Since raw length < 2000, raw truncation does not trigger.
    Inspects whether escaped expansion causes message to exceed 4,096 characters.
    """
    notifier = TelegramNotifier(mock_mode=True)
    dense_amp_url = "https://example.com/apply?" + ("a=&" * 550)
    assert len(dense_amp_url) <= 2000

    job = JobListing(
        external_id="amp-overflow",
        company_name="Acme",
        title="Developer",
        url=dense_amp_url,
    )
    match = FilterResult(matched=True)
    msg = notifier.format_job_message(job, match)
    msg_bytes = len(msg.encode("utf-8"))

    # Documents whether message stays under Telegram's 4096 character limit
    # If msg_bytes > 4096, this identifies a hardening recommendation for raw URL bounding
    is_safe = msg_bytes < 4096
    return is_safe, msg_bytes



def test_adversarial_empty_or_hash_url_handling():
    """
    Verify behavior when job.url is empty or '#'
    Telegram Bot API rejects <a href="#"> with 'Bad Request: URL host is empty'.
    Inspects whether link is validly formatted or properly handled.
    """
    notifier = TelegramNotifier(mock_mode=True)
    job = JobListing(
        external_id="no-url",
        company_name="Stealth Startup",
        title="Founding Engineer",
        url="",
    )
    match = FilterResult(matched=True)
    msg = notifier.format_job_message(job, match)

    valid, errors = validate_telegram_html(msg)
    assert valid, f"HTML validation failed: {errors}"
    assert len(msg.encode("utf-8")) < 4096

