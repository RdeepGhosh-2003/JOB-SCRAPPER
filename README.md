# CareerPulse — Direct Career Portal Job Tracker & Telegram Alert Bot

CareerPulse monitors target company career sites directly (via **Greenhouse**, **Lever**, **Ashby**, and **Workday** public JSON APIs, with an intelligent HTML fallback for custom portals) and delivers instant notifications with direct application links whenever matching openings are discovered.

---

## Key Features

1. **Direct ATS API Ingestion**: Fetches open listings without heavy browser overhead or scraping bans from:
   - Greenhouse (`boards.greenhouse.io/<company>`)
   - Lever (`jobs.lever.co/<company>`)
   - Ashby (`jobs.ashbyhq.com/<org>`)
   - Workday CXS (`<tenant>.myworkdayjobs.com/...`)
   - Custom Portal fallback (Schema.org JSON-LD & DOM extraction)
2. **ATS Auto-Detector**: Paste any career page URL and CareerPulse automatically detects the underlying ATS provider and company identifier.
3. **Smart Matching & Negative Filtering**:
   - Strict negative keywords (immediately skips *Senior, Staff, Principal, Manager, Lead, Intern*, etc.)
   - Lookaround boundary regex (`(?<!\w)...(?!\w)`) for symbol safety (`C++`, `C#`, `.NET`, `Go` vs `Good`)
   - Required & preferred skill keywords, remote & location filters.
4. **SQLite Zero-Duplicate Deduplication**:
   - Canonical URL normalization (cleans tracking parameters).
   - Atomic reservation on conflict ensures you never get duplicate alerts.
5. **Instant Telegram Alerts**:
   - Clean HTML alerts with company name, job title, matched tags, and a 1-click apply link.
   - Built-in credential test and offline mock sink.
6. **Sleep/Wake Resilient Scheduler**:
   - Configurable time windows matching your laptop hours (e.g. 10:00 AM – 6:30 PM & 7:00 PM – 2:00 AM).
   - Wall-clock RTC comparisons prevent execution storms or freezes when the laptop goes to sleep.
7. **Local Web Management Dashboard**:
   - 100% offline, responsive SPA running on `http://127.0.0.1:8000`.

---

## Quickstart

### 1. Set PYTHONPATH
In PowerShell:
```powershell
$env:PYTHONPATH="src"
```

### 2. Launch the Web Dashboard
```powershell
python -m career_pulse.cli serve
```
Open **[http://127.0.0.1:8000](http://127.0.0.1:8000)** in your browser. From here you can:
- Add target companies (with instant auto-detect).
- Run on-demand scans with one click.
- Configure search filters and negative keywords.
- Set up your Telegram Bot credentials and test messages.
- View discovered jobs and click direct apply links.

---

## CLI Usage

You can also run all actions directly from the command line:

```powershell
# Add a company career portal (auto-detects ATS)
python -m career_pulse.cli add Stripe https://boards.greenhouse.io/stripe
python -m career_pulse.cli add Linear https://jobs.ashbyhq.com/linear

# List all monitored companies
python -m career_pulse.cli list

# Run a scan right now across all monitored companies
python -m career_pulse.cli scan

# View discovered jobs in terminal
python -m career_pulse.cli jobs --limit 20

# Test Telegram alerts (in mock mode or with live bot credentials)
python -m career_pulse.cli test-telegram

# Start the background resilient scheduler
python -m career_pulse.cli schedule
```

---

## Running Tests

Run the test suite using pytest:
```powershell
$env:PYTHONPATH="src"
pytest tests/
```
