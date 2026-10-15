# CareerPulse Test Readiness Report (`TEST_READY.md`)

**Date**: 2026-10-09  
**Agent**: `test_writer_e2e_1` (`teamwork_preview_test_writer`)  
**Status**: `TEST_READY` (All Tiers 1-5 test fixtures, test harness, and companion E2E test suites created and verified)

---

## 1. Executive Test Readiness Declaration

The end-to-end verification framework for CareerPulse is fully implemented, verified, and operational.
The test infrastructure consists of:
1. **Standalone Verification Harness (`verify_system.py`)**: Directly executable CLI harness implementing 6 comprehensive verification suites with exit code 0/1 semantics.
2. **Pytest Companion Suite (`tests/test_verify_e2e.py`)**: Automated async test suite for standard pytest runners and CI/CD pipelines.
3. **Comprehensive ATS Test Fixtures (`tests/fixtures/`)**: Authoritative mock response payloads for Greenhouse, Lever, Ashby, Workday CXS, and Fallback HTML scraping.
4. **Architectural Test Documentation (`TEST_INFRA.md`)**: Complete guide covering runner commands, test tiers, oracles, invariants, and failure modes.

---

## 2. Test Manifest & Verification Inventory (Tiers 1 to 5)

| Suite | Test ID | Description | Input / Condition | Authoritative Expected Output Derivation | Readiness Status |
|---|---|---|---|---|---|
| **Suite 1** | T1.1 | Greenhouse Adapter Mock Parsing | `tests/fixtures/greenhouse_sample.json` | Greenhouse API specification; extracts 9 jobs, verifies title, remote flag, URL, department, HTML stripping. | **READY** |
| **Suite 1** | T1.2 | Lever Adapter Mock Parsing | `tests/fixtures/lever_sample.json` | Lever Postings API specification; extracts 6 jobs, converts epoch ms timestamp, normalizes remote workplace type. | **READY** |
| **Suite 1** | T1.3 | Ashby Adapter Mock Parsing | `tests/fixtures/ashby_sample.json` | Ashby API specification; extracts 5 jobs, maps `isRemote` boolean, extracts compensation tier summary. | **READY** |
| **Suite 1** | T1.4 | Workday CXS Adapter Mock Parsing | `tests/fixtures/workday_sample.json` | Workday CXS specification; extracts 4 jobs, parses `bulletFields` requisition IDs, constructs deep links. | **READY** |
| **Suite 1** | T1.5 | Fallback Scraper JSON-LD & DOM Parsing | `tests/fixtures/custom_career_page.html` | Schema.org JobPosting specification & DOM card heuristics; parses jobs from both JSON-LD and semantic HTML cards. | **READY** |
| **Suite 1** | T1.6 | ATS Auto-Detector Heuristics | URLs for Greenhouse, Lever, Ashby, Workday & custom iframe | Regex patterns and HTML fingerprinting specified in `explorer_survey_1`; verifies instant detection and iframe probe. | **READY** |
| **Suite 1** | T1.7 | Live Public Board Probes (Optional) | `--live` flag with public boards | Live HTTP responses from public boards (Cloudflare, Netflix, Linear). | **READY** |
| **Suite 2** | T2.1 | Positive Title Lookaround Matching | Titles: "Software Engineer, Backend", "Python Developer" | Regex specification `(?<!\w)...(?!\w)`; matched=True, match_score > 3.0. | **READY** |
| **Suite 2** | T2.2 | Strict Negative Keyword Exclusion | Titles with Senior, Principal, Staff, Lead, Manager, Intern, Co-op | R2 requirement; matched=False with exact rejection reason citing matched negative keyword. | **READY** |
| **Suite 2** | T2.3a | Word Boundary Safety (Intern vs Internal) | Title: "Internal Tools Software Engineer" | Lookaround boundary math; must NOT match negative keyword "intern"; matched=True. | **READY** |
| **Suite 2** | T2.3b | Boundary Safety (Go vs Good) | Titles: "Good Governance Analyst" vs "Go Platform Developer" | Lookaround boundary math; "Good" does not match "Go"; "Go" matches "Go". | **READY** |
| **Suite 2** | T2.3c | Symbol Keyword Matching (C++, .NET, C#) | Titles: "C++ Systems Engineer", ".NET / C# Backend" | Lookaround regex escaping; symbols match properly without standard `\b` failure. | **READY** |
| **Suite 2** | T2.4 | Title vs Description Negative Isolation | Title "Software Engineer", desc: "report to Engineering Manager" | Specification requirement: negative title keywords do not reject description occurrences. | **READY** |
| **Suite 2** | T2.5 | Tech Stack Matching & Scoring Modes | Skills match modes "any", "all", "none"; preferred skills | Scoring formula: base + title + required * 1.5 + preferred * 0.8; verifies pass/reject criteria. | **READY** |
| **Suite 2** | T2.6 | Location & Remote Filtering | Job locations vs `remote_only`, allowed and excluded lists | Boolean logic; remote jobs pass remote check; excluded locations strictly rejected. | **READY** |
| **Suite 3** | T3.1 | SQLite WAL Mode & Schema Init | DDL execution with `PRAGMA journal_mode = WAL` | SQLite PRAGMA specification; journal_mode == "wal", foreign_keys == 1. | **READY** |
| **Suite 3** | T3.2 | First Run Ingestion & Atomic Slot Reservation | 5 initial jobs ingested into fresh DB | Database contract; all 5 return `is_new=True`; `reserve_alert_slot` returns `True`. | **READY** |
| **Suite 3** | T3.3 | Subsequent Scan Deduplication (Zero Duplicate Alerts) | Same 5 jobs re-ingested in second scan | Deduplication contract; all 5 return `is_new=False`; `reserve_alert_slot` returns `False` (0 duplicates). | **READY** |
| **Suite 3** | T3.4 | Incremental Batch Ingestion | 5 existing + 2 new jobs | Deduplication contract; exactly 2 return `is_new=True` and acquire alert reservation. | **READY** |
| **Suite 3** | T3.5 | Atomic Reservation Concurrency Stress Test | 10 concurrent async tasks attempting reservation on same job | SQLite `ON CONFLICT DO NOTHING` ACID guarantee; exactly 1 task returns `True`, 9 return `False`. | **READY** |
| **Suite 4** | T4.1 | Telegram HTML Escaping & Formatting | Fields containing `<`, `>`, `&`, `"` | Telegram Bot API HTML parse mode specification; all meta-characters properly escaped. | **READY** |
| **Suite 4** | T4.2 | Direct Clickable Application Link | Job URL | HTML link template `<a href="..."><b>👉 Apply Directly on Company Site</b></a>`. | **READY** |
| **Suite 4** | T4.3 | Message Length Boundary Check | Formatted message with 100 preferred skills | Telegram API limit (4,096 UTF-8 characters); verifies length < 4096. | **READY** |
| **Suite 4** | T4.4 | MockTelegramSink Delivery & Verification | In-memory message dispatch | Mock sink contract; message stored in `sent_messages` with chat_id, text, and HTML parse mode. | **READY** |
| **Suite 4** | T4.5 | Credential Verification Mock Response | `verify_credentials()` call | Contract specification; returns `{"valid": True, "mock": True}`. | **READY** |
| **Suite 5** | T5.1 | REST API Health Check Endpoint | `GET /api/health` | HTTP 200 OK with `status: ok` and UTC timestamp. | **READY** |
| **Suite 5** | T5.2 | Company CRUD REST Lifecycle | POST, GET, PUT, DELETE `/api/companies` | REST contract; creates, lists, retrieves, and deletes company records. | **READY** |
| **Suite 5** | T5.3 | Filter Settings REST Endpoints | GET and PUT `/api/settings/filters` | REST contract; reads and persists search filter configurations. | **READY** |
| **Suite 5** | T5.4 | 100% Offline UI Compliance Verification | Static and template files (`.html`, `.css`, `.js`) | R4 requirement; ZERO references to remote CDNs (`fonts.googleapis.com`, `cdnjs`, `unpkg`, `jsdelivr`). | **READY** |
| **Suite 6** | T6.1 | Wall-Clock RTC Timestamp Initialization | Scheduler instantiation with 60 min interval | UTC RTC time contract; `next_run_at` calculated forward from current UTC wall-clock time. | **READY** |
| **Suite 6** | T6.2 | Sleep/Wake 3-Hour Leap Simulation | Advance wall clock 3 hours while scheduler is asleep | R5 requirement; wakes up, detects time lag, triggers immediate catch-up scan. | **READY** |
| **Suite 6** | T6.3 | Forward Reschedule Invariant (Zero Run Storm) | Post-wake execution state | Reschedule formula `now + interval`; total scans = 1, NO duplicate burst. | **READY** |
| **Suite 6** | T6.4 | Concurrency Lock & Parallel Collision Prevention | Simultaneous manual trigger during active scan | Async lock contract; second trigger returns `status: in_progress`. | **READY** |
| **Suite 6** | T6.5 | Fast Graceful Cancellation | `stop()` called on running scheduler | Async event cancel; exits tick loop in < 100ms without thread or event loop leaks. | **READY** |

---

## 3. How to Run the Verification Suite

### Standard CLI Run:
```powershell
python verify_system.py --verbose
```

### Pytest Execution:
```powershell
pytest tests/test_verify_e2e.py -v
```

---

## 4. Observations & Notes for Implementing Agents

1. **ATS Adapters (M1)**:
   - `GreenhouseAdapter`, `LeverAdapter`, `AshbyAdapter`, `WorkdayAdapter`, `FallbackScraper`, and `ATSDetector` are implemented in `src/career_pulse/adapters/` and conform directly to the interface contracts.
2. **Filtering & Negative Keywords (M2)**:
   - Ensure the `negative_title_keywords` are strictly matched against `job.title` only and NEVER against `job.description_text`. Matching negative keywords against descriptions causes false positive rejections of standard engineering roles that mention "reporting to the Engineering Manager".
   - Use lookaround regular expression patterns `(?<!\w)...(?!\w)` instead of standard `\b` so that tech keywords like `C++`, `.NET`, `C#`, and short words like `Go` do not suffer from word boundary edge case failures.
3. **SQLite Deduplication (M2)**:
   - Tables must be initialized with `PRAGMA journal_mode = WAL;`, `PRAGMA foreign_keys = ON;`, and `PRAGMA busy_timeout = 5000;`.
   - The atomic alert reservation query `INSERT INTO alerts_history (job_id, channel, status) VALUES (?, 'telegram', 'pending') ON CONFLICT(job_id, channel) DO NOTHING;` is essential for 100% ACID zero duplicate alert guarantees.
4. **Telegram Service (M3)**:
   - Telegram messages must strictly use HTML parse mode (`parse_mode="HTML"`) with `html.escape()`. Do not use `MarkdownV2` because unescaped punctuation characters in job descriptions or titles trigger HTTP 400 Bad Request errors.
   - Maintain `MockTelegramSink` for zero-network testing.
5. **Local Web UI (M4)**:
   - Strict 100% offline rule: Do NOT include any remote CDN stylesheets, external Google Fonts, or third-party JS scripts in HTML templates. Use native CSS variables, system font stacks, and embedded inline SVGs.
6. **Resilient Scheduler (M5)**:
   - Always compare wall-clock UTC time (`datetime.now(timezone.utc) >= self.next_run_at`) rather than `asyncio.sleep(interval)`.
   - Reschedule forward from the current awake time (`self.next_run_at = datetime.now(timezone.utc) + timedelta(minutes=self.interval_minutes)`) to prevent duplicate run storms upon laptop wake.
