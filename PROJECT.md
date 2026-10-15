# Project: CareerPulse

## Architecture
CareerPulse is a modular, lightweight local career portal job tracker and Telegram alert bot. It monitors company career sites directly (via Greenhouse, Lever, Ashby, and Workday APIs, with a Playwright fallback for custom portals) and pushes instant notifications with direct application links.

### System Components & Data Flow
```
                                  [Target Companies]
                                          │
                                          ▼
                      ┌──────────────────────────────────────┐
                      │          Fast ATS Adapters           │
                      │ (Greenhouse, Lever, Ashby, Workday)  │
                      │       + Playwright Scraper           │
                      └──────────────────┬───────────────────┘
                                         │ Normalized JobListing
                                         ▼
                      ┌──────────────────────────────────────┐
                      │    Job Matching & Filter Engine      │
                      │  - Target title lookaround regex     │
                      │  - Required & preferred skills       │
                      │  - Strict negative keyword filter    │
                      │  - Location & Remote/Hybrid logic    │
                      └──────────────────┬───────────────────┘
                                         │ FilterResult (matched=True)
                                         ▼
                      ┌──────────────────────────────────────┐
                      │    SQLite DB & Deduplication         │
                      │  - Atomic reservation ON CONFLICT    │
                      │  - Canonical URL & unique key hash   │
                      │  - Zero duplicate alert guarantee    │
                      └──────────────────┬───────────────────┘
                                         │ New un-alerted job
                                         ▼
                      ┌──────────────────────────────────────┐
                      │     Telegram Notification Service    │
                      │  - HTML formatted alert messages     │
                      │  - Direct 1-click apply links        │
                      │  - Credential verification & Mock    │
                      └──────────────────────────────────────┘
                                         ▲
                                         │ Scheduled Scan Trigger
                      ┌──────────────────┴───────────────────┐
                      │   Resilient Sleep/Wake Scheduler     │
                      │  - Wall-clock UTC timestamp checks   │
                      │  - 5-second tick loop (no freeze)    │
                      │  - Forward reschedule (no run storm) │
                      └──────────────────┬───────────────────┘
                                         │ Status & Triggers
                                         ▼
                      ┌──────────────────────────────────────┐
                      │     FastAPI Backend & REST API       │
                      │  - Company CRUD & ATS auto-detect    │
                      │  - Filter config & Telegram settings │
                      │  - Job history & manual scan trigger │
                      │  - 100% Offline Responsive SPA UI    │
                      └──────────────────────────────────────┘
```

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| F1 | Greenhouse Adapter | Unauthenticated public JSON board API (`/v1/boards/{token}/jobs?content=true`) returning normalized jobs | M1 | ORIGINAL_REQUEST R1 |
| F2 | Lever Adapter | Unauthenticated public JSON postings API (`/v0/postings/{company}?mode=json`) with pagination | M1 | ORIGINAL_REQUEST R1 |
| F3 | Ashby Adapter | Keyless public posting API (`/posting-api/job-board/{org}`) with compensation and remote tags | M1 | ORIGINAL_REQUEST R1 |
| F4 | Workday CXS Adapter | Candidate Experience Services POST API (`/wday/cxs/.../jobs`) with offset loop & pagination | M1 | ORIGINAL_REQUEST R1 |
| F5 | Fallback Scraper | Headless Playwright scraper with Schema.org JSON-LD parsing and DOM card extraction | M1 | ORIGINAL_REQUEST R1 |
| F6 | ATS Auto-Detector | Regex matcher + HTTP probe for automatic ATS identification from career page URL | M1 | ORIGINAL_REQUEST R4 |
| F7 | Positive Title Matching | Word boundary lookaround regex `(?<!\w)...(?!\w)` for target titles | M2 | ORIGINAL_REQUEST R2 |
| F8 | Tech Stack & Skill Matcher | Required skills (`any`/`all`) and preferred skills with score computation | M2 | ORIGINAL_REQUEST R2 |
| F9 | Strict Negative Keyword Filter | Title negative exclusions (Senior, Principal, Staff, Manager, Intern) decoupled from description | M2 | ORIGINAL_REQUEST R2 |
| F10 | Location & Remote Filtering | Explicit remote flag, location regex patterns, allowed/excluded location lists | M2 | ORIGINAL_REQUEST R2 |
| F11 | SQLite Schema & WAL Storage | SQLite tables for `companies`, `jobs`, `alerts_history`, `settings` with WAL mode & indexes | M2 | ORIGINAL_REQUEST R2 |
| F12 | Zero Duplicate Deduplication | Composite unique keys (`{provider}:{company_id}:{external_id}`) + atomic reservation | M2 | ORIGINAL_REQUEST R2 |
| F13 | Telegram Notification Service | HTML formatted push alerts with direct apply link, company, title, location, and tags | M3 | ORIGINAL_REQUEST R3 |
| F14 | Telegram Credential Test & Mock | `verify_credentials` endpoint + `MockTelegramSink` for offline verification | M3 | ORIGINAL_REQUEST R3 |
| F15 | FastAPI Backend REST API | Complete REST endpoints for companies, settings, filters, jobs, scan, and telegram | M4 | ORIGINAL_REQUEST R4 |
| F16 | 100% Offline Web Dashboard | Single-page responsive UI with pure CSS/JS/SVG and zero external CDN dependencies | M4 | ORIGINAL_REQUEST R4 |
| F17 | Sleep/Wake Resilient Scheduler | Async loop with 5s tick, wall-clock UTC comparisons, forward reschedule, and concurrency lock | M5 | ORIGINAL_REQUEST R5 |
| F18 | System Pipeline Integration | Unified scan pipeline connecting adapters, matcher, deduplication, and notification | M5 | ORIGINAL_REQUEST R1-R5 |
| F19 | Automated Verification Suite | Standalone `verify_system.py` test harness executing end-to-end multi-tier verification | M6 | ORIGINAL_REQUEST Verification |
| F20 | Adversarial Hardening (Tier 5) | Comprehensive adversarial test cases, edge cases, symbol keywords, and concurrency audits | M6 | Teamwork Project Pattern |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| E2E | E2E Testing Track | Requirement-driven test harness, mock fixtures, multi-tier test suites, publish `TEST_READY.md` | none | DONE |
| M1 | Fast ATS Adapters & Scraping | Greenhouse, Lever, Ashby, Workday CXS adapters, Playwright fallback, ATS detector, standardized Job models | none | DONE |
| M2 | Filtering & SQLite Deduplication | Lookaround regex matcher, negative keyword filter, SQLite schema (WAL), atomic deduplication reservation | M1 | DONE |
| M3 | Telegram Notification Service | HTML formatted alerts, direct application links, credential validation, MockTelegramSink | M2 | READY |
| M4 | FastAPI Backend & Local UI | REST API routes, company CRUD, ATS auto-detection, filter config, 100% offline responsive SPA UI | M2, M3 | PLANNED |
| M5 | Resilient Scheduler & Integration | Resilient async loop with wall-clock ticks, lock management, end-to-end scan pipeline runner | M1, M2, M3, M4 | PLANNED |
| M6 | Final Verification & Hardening | Pass 100% E2E tests (Tiers 1-4) + `verify_system.py`, followed by Phase 2 Tier 5 Adversarial Hardening | M5, E2E | PLANNED |

## Code Layout
```
C:\Users\KIIT\.gemini\antigravity\scratch\career_pulse/
├── pyproject.toml                     # Build and packaging configuration
├── requirements.txt                   # Direct requirements list
├── README.md                          # Documentation and quickstart guide
├── verify_system.py                   # Automated standalone verification harness
├── src/
│   └── career_pulse/
│       ├── __init__.py
│       ├── config.py                  # Global settings, paths, defaults
│       ├── core/
│       │   ├── __init__.py
│       │   ├── models.py              # Pydantic models: JobListing, JobFilterConfig, FilterResult, etc.
│       │   ├── matching.py            # JobMatcher with lookaround regex and negative exclusions
│       │   └── pipeline.py            # Unified scan orchestrator coordinating adapters, DB, and alerts
│       ├── db/
│       │   ├── __init__.py
│       │   ├── schema.sql             # SQLite DDL with WAL mode, tables, indexes, constraints
│       │   └── session.py             # Async database manager (aiosqlite) with atomic deduplication
│       ├── adapters/
│       │   ├── __init__.py
│       │   ├── base.py                # BaseATSAdapter abstract class
│       │   ├── greenhouse.py          # Greenhouse public JSON API adapter
│       │   ├── lever.py               # Lever public JSON API adapter
│       │   ├── ashby.py               # Ashby public JSON API adapter
│       │   ├── workday.py             # Workday CXS public JSON API adapter
│       │   ├── fallback.py            # BeautifulSoup + Playwright fallback scraper
│       │   └── detector.py            # URL regex & HTML probe auto-detector
│       ├── services/
│       │   ├── __init__.py
│       │   └── telegram.py            # TelegramNotifier, HTML formatter, test verify, MockTelegramSink
│       ├── scheduler/
│       │   ├── __init__.py
│       │   └── resilient.py           # ResilientScheduler with 5s tick loop and wall-clock RTC tracking
│       └── web/
│           ├── __init__.py
│           ├── app.py                 # FastAPI application, lifespan context, CORS, static mounts
│           ├── routes/
│           │   ├── __init__.py
│           │   ├── companies.py       # Company management CRUD and ATS detection endpoint
│           │   ├── filters.py         # Filter configuration GET/PUT
│           │   ├── jobs.py            # Paginated job history and search
│           │   ├── scan.py            # On-demand scan trigger and status
│           │   ├── telegram.py        # Telegram settings and live test message endpoint
│           │   └── scheduler.py       # Scheduler status and interval config
│           ├── static/
│           │   ├── app.css            # 100% offline pure CSS styles (Dark/Light mode, responsive)
│           │   └── app.js             # 100% offline vanilla JavaScript SPA logic
│           └── templates/
│               └── index.html         # HTML dashboard shell with embedded inline SVG icons
└── tests/
    ├── conftest.py                    # Test fixtures, mock HTTP clients, sample ATS payloads
    ├── test_adapters.py               # Unit tests for all ATS adapters & detector
    ├── test_matching.py               # Unit tests for title matching, negative filtering, skill scoring
    ├── test_database.py               # Tests for SQLite schema, WAL mode, atomic deduplication
    ├── test_telegram.py               # Tests for message formatting, escaping, credential verification
    ├── test_api.py                    # Tests for FastAPI REST endpoints and offline asset checks
    └── test_scheduler.py              # Tests for sleep/wake resilience, time jumps, and locking
```

## Interface Contracts

### 1. `BaseATSAdapter` ↔ `JobListing`
```python
class BaseATSAdapter(ABC):
    @abstractmethod
    async def fetch_jobs(self, company_identifier: str, **kwargs) -> List[JobListing]:
        """Fetches jobs and returns standardized JobListing instances."""
        pass
```

### 2. `JobMatcher` ↔ `FilterResult`
```python
class JobMatcher:
    def __init__(self, config: JobFilterConfig): ...
    def evaluate(self, job: JobListing) -> FilterResult:
        """Evaluates job against positive/negative titles, skills, locations.
        Returns FilterResult(matched: bool, match_score: float, matched_skills: List[str], ...)"""
```

### 3. `Database` ↔ `JobListing` (Atomic Deduplication Contract)
```python
class Database:
    async def upsert_job(self, company_id: int, job: JobListing) -> Tuple[int, bool]:
        """Returns (job_id, is_new)."""
    async def reserve_alert_slot(self, job_id: int, channel: str = "telegram") -> bool:
        """Executes INSERT INTO alerts_history ... ON CONFLICT DO NOTHING.
        Returns True if reservation was acquired (never alerted before), False otherwise."""
    async def finalize_alert_status(self, job_id: int, channel: str, status: str, preview: Optional[str] = None): ...
```

### 4. `TelegramNotifier` ↔ Notification Dispatch
```python
class TelegramNotifier:
    def format_job_message(self, job: JobListing, match: FilterResult) -> str: ...
    async def send_message(self, text: str) -> bool: ...
    async def verify_credentials(self) -> Dict[str, Any]: ...
```

### 5. `ResilientScheduler` ↔ Scan Pipeline
```python
class ResilientScheduler:
    def __init__(self, scan_coro_fn: Callable[[], Coroutine], interval_minutes: int = 60, tick_seconds: float = 5.0): ...
    def start(self): ...
    async def stop(self): ...
    async def trigger_now(self) -> dict: ...
```
