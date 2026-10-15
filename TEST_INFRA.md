# CareerPulse Test Infrastructure (`TEST_INFRA.md`)

## 1. Overview & Architecture

CareerPulse provides a comprehensive, multi-tiered test infrastructure designed to guarantee end-to-end correctness, zero duplicate alerts, strict negative keyword exclusion, and resilient background scheduling.

The test infrastructure operates under a **Dual-Track Agile Model**:
- **Track A (E2E Verification Track)**: Requirement-driven, contract-based verification harness (`verify_system.py`), comprehensive mock response fixtures (`tests/fixtures/`), and Pytest test suites (`tests/test_verify_e2e.py`).
- **Track B (Implementation Track)**: Modular milestones implementing ATS Adapters (M1), Filtering & Deduplication (M2), Telegram Alerts (M3), FastAPI Dashboard & Offline UI (M4), and Resilient Scheduler (M5).

The verification harness is designed for **Progressive Testability**: it provides authoritative reference contract harnesses that test system specifications and interface contracts even while individual modules are under concurrent construction, and automatically resolves to production modules in `career_pulse` as milestones complete.

---

## 2. Directory Layout & Artifacts

```
career_pulse/
├── verify_system.py                   # Standalone CLI test harness (exit code 0/1)
├── TEST_INFRA.md                      # Test infrastructure & architecture guide
├── TEST_READY.md                      # Test readiness, test manifest & matrix report
├── tests/
│   ├── test_verify_e2e.py             # Companion Pytest E2E test suite
│   └── fixtures/                      # Realistic ATS response payloads & HTML
│       ├── greenhouse_sample.json     # Greenhouse Job Board API payload (9 jobs)
│       ├── lever_sample.json          # Lever Postings API payload (6 jobs)
│       ├── ashby_sample.json          # Ashby Job Board API payload (5 jobs)
│       ├── workday_sample.json        # Workday CXS Search API payload (4 jobs)
│       └── custom_career_page.html    # Custom career page with JSON-LD & DOM cards
```

---

## 3. Test Runners & Execution Commands

### 3.1 Standalone Verification Harness (`verify_system.py`)

Directly executable in any terminal without external testing frameworks:

```powershell
# Run full offline verification suite
python verify_system.py

# Run quick verification (mock & offline fixtures only)
python verify_system.py --quick

# Run with verbose diagnostic outputs
python verify_system.py --verbose

# Run with live public ATS endpoints (requires internet connection)
python verify_system.py --live
```

**Exit Code Contract**:
- `0`: All verification assertions passed.
- `1`: One or more assertions failed.

### 3.2 Pytest Companion Test Suite (`tests/test_verify_e2e.py`)

Integrated with the Python test ecosystem:

```powershell
# Run all E2E verification tests
pytest tests/test_verify_e2e.py -v

# Run specific suite
pytest tests/test_verify_e2e.py -k "test_suite_2_job_matching" -v

# Run adversarial boundary tests only
pytest tests/test_verify_e2e.py -k "adversarial" -v
```

---

## 4. Test Fixtures & Authoritative Oracles

Every fixture in `tests/fixtures/` represents an exact, authoritative payload captured from public documentation and real-world ATS schemas:

| Fixture File | Target Platform | Test Invariants & Covered Edge Cases |
|---|---|---|
| `greenhouse_sample.json` | Greenhouse Job Board | 9 jobs across departments; nested office/location objects; remote tag detection; HTML content description; negative titles ("Senior", "Staff", "Intern", "Lead", "Product Manager"); symbol titles ("C++ Systems Engineer", "Go Platform Developer"). |
| `lever_sample.json` | Lever Postings API | 6 jobs; `text` title field; timestamp in epoch milliseconds; `workplaceType` ("remote", "onsite", "hybrid"); description plaintext vs HTML lists; boundary title "International Business Developer"; isolation case: description mentions "report to Engineering Manager". |
| `ashby_sample.json` | Ashby Job Board API | 5 jobs; native `isRemote` boolean; compensation tier summary extraction; secondary location lists; negative titles ("VP of Engineering", "Director of Product"). |
| `workday_sample.json` | Workday CXS API | 4 jobs; `bulletFields` requisition IDs; `externalPath` fallback extraction; `locationsText` location string; pagination limit/offset structure; boundary title "Good Governance Analyst". |
| `custom_career_page.html` | Fallback Scraper & Detector | Dual extraction surface: Schema.org `@type: JobPosting` in `<script type="application/ld+json">` AND semantic HTML DOM cards (`<div class="job-card">`); embedded Greenhouse iframe for ATS auto-detection probing. |

---

## 5. Multi-Tier Test Suite Matrix (Tiers 1 to 5)

### Tier 1: ATS Adapters & Auto-Detection Engine (`Suite 1`)
- **1.1 Greenhouse Adapter**: Parses `greenhouse_sample.json` into normalized `JobListing` objects; validates title, remote flag, URL, department, and description HTML stripping.
- **1.2 Lever Adapter**: Parses `lever_sample.json`; extracts `text` as title, converts epoch milliseconds to UTC datetime, normalizes workplace types, and preserves description.
- **1.3 Ashby Adapter**: Parses `ashby_sample.json`; maps native `isRemote`, captures compensation strings, and formats direct apply URLs.
- **1.4 Workday CXS Adapter**: Parses `workday_sample.json`; extracts bulletField/path requisition codes, formats Workday deep links, and handles CXS 20-item paging.
- **1.5 Fallback Scraper**: Cascading extraction: Tier 1 JSON-LD JobPosting parsing + Tier 2 DOM job card heuristic extraction.
- **1.6 ATS Auto-Detector**: Two-phase detection: Phase 1 instant regex classification (Greenhouse, Lever, Ashby, Workday) + Phase 2 HTTP iframe/script fingerprinting.
- **1.7 Live Public Board Validation (Optional)**: Validates real HTTP calls against live boards (Cloudflare, Netflix, Linear).

### Tier 2: Job Matching, Scoring & Strict Negative Exclusions (`Suite 2`)
- **2.1 Positive Title Matching**: Lookaround boundary regex `(?<!\w)...(?!\w)` matching target titles without standard `\b` edge case failures.
- **2.2 Strict Negative Title Exclusion**: Immediate short-circuit rejection of Senior, Principal, Staff, Lead, Manager, Director, VP, Intern, and Co-op titles.
- **2.3 Adversarial Word Boundary & Symbol Safety**:
  - `C++` and `C#` / `.NET` matched cleanly.
  - `Go` programming language keyword matches "Go Developer" but NEVER matches "Good Developer" or "Governance".
  - Negative keyword `intern` rejects "Software Engineering Intern" but NEVER rejects "Internal Tools Software Engineer" or "International Business Development".
- **2.4 Title vs Description Negative Isolation**: Roles with title "Software Engineer" mentioning "report to Engineering Manager" in the description are strictly accepted.
- **2.5 Tech Stack & Skills Scoring**: Evaluates `skills_match_mode` (`any`, `all`, `none`), computes match relevance scores, and highlights matched skills.
- **2.6 Location & Remote Filtering**: Validates `remote_only`, allowed location substrings, and excluded locations.

### Tier 3: SQLite Storage, WAL Mode & Zero Duplicate Alert Deduplication (`Suite 3`)
- **3.1 Schema & Pragmas**: Validates `PRAGMA journal_mode = WAL`, `PRAGMA foreign_keys = ON`, and busy timeouts.
- **3.2 First-Run Ingestion**: Ingests 5 jobs; confirms all 5 receive `is_new=True` and acquire initial `reserve_alert_slot=True`.
- **3.3 Subsequent Scan Deduplication**: Re-ingests same 5 jobs; confirms `is_new=False`, zero duplicate alert slots acquired (`reserve_alert_slot=False`), and alerts table row count remains exactly 5.
- **3.4 Incremental Ingestion**: Ingests 5 existing + 2 new jobs; confirms exactly 2 new jobs receive `is_new=True` and alert reservation.
- **3.5 Atomic Reservation Concurrency Stress**: Spawns 10 parallel async tasks attempting to reserve an alert slot on the same `job_id`; verifies that exactly ONE succeeds and 9 fail via SQLite `ON CONFLICT DO NOTHING`.

### Tier 4: Telegram Push Notification Service & Mock Sink (`Suite 4`)
- **4.1 HTML Formatting & Escaping**: Verifies entity escaping of `<`, `>`, `&`, and `"` across company names, titles, and matched skills; ensures valid HTML syntax.
- **4.2 Direct 1-Click Apply Links**: Verifies clean link format: `<a href="..."><b>👉 Apply Directly on Company Site</b></a>`.
- **4.3 Message Length Safety**: Verifies that even with long descriptions and large skill lists, formatted messages stay strictly within the Telegram 4,096 character ceiling.
- **4.4 `MockTelegramSink` Recording**: Verifies in-memory alert capture for offline inspection, asserting `chat_id`, `text`, and `parse_mode="HTML"`.
- **4.5 Credential Verification**: Tests bot token validation and mock credential response.

### Tier 5: Adversarial Boundary & Stress Testing
- **5.1 100% Offline UI Compliance**: Inspects all HTML, CSS, and JS files; asserts ZERO references to external CDN domains (`fonts.googleapis.com`, `cdnjs`, `unpkg`, `jsdelivr`).
- **5.2 Sleep/Wake Resilient Scheduling (`Suite 6`)**:
  - Tests Real-Time Clock UTC timestamp comparisons.
  - Simulates 3-hour laptop sleep leap: detects wake lag, catches up immediately with exactly 1 scan.
  - Verifies Forward Reschedule Invariant: resets `next_run_at = now + interval`, preventing duplicate run storms / bursts.
  - Verifies Concurrency Lock: skips manual scan collisions while scheduled scan is active.
  - Verifies fast clean shutdown (< 100ms).

---

## 6. System Invariants Enforced by Tests

1. **Zero Duplicate Alert Invariant**: An alert for a given `(job_id, channel)` can never be dispatched or reserved more than once in the database, regardless of scan frequency or concurrent triggers.
2. **Title-Only Negative Exclusion Invariant**: A negative keyword configured for title exclusion must never trigger a rejection due to appearing in the job description body.
3. **Punctuation & Symbol Integrity Invariant**: Keywords containing symbols (`C++`, `.NET`, `C#`) or short words (`Go`) must match accurately without word boundary corruption.
4. **Offline UI Invariant**: The dashboard backend and frontend must function 100% locally with zero internet access, zero external CDN links, and zero remote font dependencies.
5. **Sleep/Wake Reschedule Forward Invariant**: Upon waking from laptop sleep or suspension, the scheduler must execute at most ONE catch-up scan and forward-reschedule the next run from the current awake time.
