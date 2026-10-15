# Original User Request

## 2026-10-09T14:58:29Z

CareerPulse: A lightweight local career portal job tracker and Telegram alert bot that monitors company career sites directly (via Greenhouse, Lever, Ashby, and Workday APIs, with a Playwright fallback for custom portals) and pushes instant notifications with direct application links.

Working directory: C:\Users\KIIT\.gemini\antigravity\scratch\career_pulse
Integrity mode: development

## Requirements

### R1. Fast ATS Adapters & Web Scraping Engine
The engine must fetch open job listings directly from major ATS platforms (Greenhouse, Lever, Ashby, Workday) using their public structured JSON APIs without browser overhead. For proprietary corporate career pages, provide a Playwright headless scraper fallback to extract job titles, locations, and application URLs.

### R2. Job Matching, Filtering & Deduplication Engine
Filter discovered jobs against configurable target job titles, required skill/tech stack keywords, and preferred locations/remote tags, while strictly excluding negative keywords (e.g., Senior, Principal, Staff, Manager, Intern). Maintain a SQLite database to track seen jobs by unique identifier/URL to guarantee zero duplicate alerts.

### R3. Telegram Notification Service
Deliver formatted push alerts to the user's Telegram chat containing company name, job title, location, matched keywords, and a direct link to the application page. Include a test mechanism to verify Telegram bot credentials and chat delivery.

### R4. Local Web Management Dashboard & REST API
Provide a clean local web dashboard (FastAPI backend + responsive web UI) running on localhost. The dashboard must allow adding and editing target companies (with auto-detection of ATS type from URL), updating search filters, inspecting scraped job history, triggering an on-demand scan, and configuring Telegram bot settings.

### R5. Background Scheduler & Sleep/Wake Resilience
Implement an async scheduling loop that runs periodic checks (configurable 60–90 minute interval). Ensure the scheduler handles laptop sleep and wake cycles cleanly without freezing, crashing, or triggering duplicate runs.

## Acceptance Criteria

### Core Functionality
- [ ] Running a scan against test companies on Greenhouse, Lever, and Ashby successfully returns real, parsed job listings.
- [ ] Filtering logic accurately matches target titles/skills and excludes jobs containing negative keywords.
- [ ] Previously seen jobs are stored in SQLite and omitted from subsequent notification runs.
- [ ] Telegram alert service successfully sends a formatted message with a clickable direct application link.
- [ ] Local web interface (FastAPI + HTML/CSS/JS) starts on localhost and provides company management, filter settings, and manual scan triggers.

### Robustness & Verification
- [ ] Programmatic automated verification script (`verify_system.py`) executes end-to-end tests for ATS fetching, filtering, SQLite deduplication, and mock Telegram dispatch.
- [ ] System handles offline/sleep periods gracefully and resumes scheduled scans when active.
