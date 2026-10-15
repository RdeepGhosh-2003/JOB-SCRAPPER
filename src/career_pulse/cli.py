"""
CareerPulse Command Line Interface (CLI).

Usage:
    python -m career_pulse.cli scan                      # Scan all companies now
    python -m career_pulse.cli add <name> <url>          # Add a target company
    python -m career_pulse.cli list                      # List monitored companies
    python -m career_pulse.cli jobs                      # Display discovered jobs
    python -m career_pulse.cli test-telegram             # Test Telegram notification
    python -m career_pulse.cli serve [--port 8000]       # Launch local Web Dashboard
    python -m career_pulse.cli schedule                  # Run background scheduler
"""

import argparse
import asyncio
import logging
import sys
from typing import Optional

from career_pulse.config import settings
from career_pulse.db.session import Database
from career_pulse.adapters.detector import ATSDetector
from career_pulse.core.pipeline import ScanPipeline
from career_pulse.services.telegram import get_telegram_notifier
from career_pulse.scheduler.resilient import ResilientScheduler


def setup_cli_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


async def cmd_scan(company_id: Optional[int] = None):
    print("-> Initializing CareerPulse database and scan pipeline...")
    db = Database(settings.db_path)
    await db.init_schema()
    pipeline = ScanPipeline(db=db)

    print("-> Running scan across monitored portals...")
    report = await pipeline.run_scan(company_id=company_id)

    print("\n" + "=" * 60)
    print("   CAREERPULSE SCAN REPORT")
    print("=" * 60)
    print(f"Portals Scanned:    {report.companies_scanned}")
    print(f"Total Jobs Found:   {report.total_jobs_found}")
    print(f"Matching Jobs:      {report.total_jobs_matched}")
    print(f"New Alerts Sent:    {report.new_alerts_sent}")
    print(f"Scan Duration:      {report.duration_seconds}s")
    print("-" * 60)

    for cr in report.company_results:
        status_sym = "+" if cr.status == "success" else "x"
        print(f"[{status_sym}] {cr.company_name} ({cr.provider}): {cr.total_found} jobs found, {cr.total_matched} matched, {cr.new_alerts} alerts sent")
        if cr.error:
            print(f"    Error: {cr.error}")

    print("=" * 60 + "\n")


async def cmd_add(name: str, url: str):
    db = Database(settings.db_path)
    await db.init_schema()

    print(f"-> Probing career portal: {url}")
    detected = ATSDetector.match_url(url)
    provider = detected.provider if detected else "custom"
    identifier = detected.identifier if detected else None

    if detected:
        print(f"[+] Detected ATS: {provider.upper()} (Token: {identifier})")
    else:
        print(f"[!] Custom portal detected. Will use Playwright / HTML DOM fallback.")

    async with await db.get_connection() as conn:
        try:
            cursor = await conn.execute(
                """
                INSERT INTO companies (name, career_url, ats_provider, identifier, url, provider)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET career_url = excluded.career_url, ats_provider = excluded.ats_provider
                """,
                (name.strip(), url.strip(), provider, identifier, url.strip(), provider),
            )
            await conn.commit()
            print(f"[+] Successfully registered company '{name}'!")
        except Exception as e:
            print(f"[x] Error adding company: {e}")


async def cmd_list():
    db = Database(settings.db_path)
    await db.init_schema()

    async with await db.get_connection() as conn:
        async with conn.execute(
            """
            SELECT c.*, COUNT(j.id) as job_count
            FROM companies c
            LEFT JOIN jobs j ON j.company_id = c.id
            GROUP BY c.id
            ORDER BY c.created_at DESC
            """
        ) as cur:
            rows = await cur.fetchall()

    if not rows:
        print("No monitored companies registered yet. Add one with: python -m career_pulse.cli add <name> <url>")
        return

    print(f"\n{'ID':<4} {'Company':<20} {'Provider':<14} {'Jobs':<6} {'Last Scanned':<20} Career URL")
    print("-" * 80)
    for r in rows:
        last_scan = str(r["last_scanned_at"])[:19] if r["last_scanned_at"] else "Never"
        print(f"{r['id']:<4} {r['name']:<20} {r['ats_provider']:<14} {r['job_count']:<6} {last_scan:<20} {r['career_url']}")
    print("")


async def cmd_jobs(limit: int = 20):
    db = Database(settings.db_path)
    await db.init_schema()

    async with await db.get_connection() as conn:
        async with conn.execute(
            """
            SELECT j.*, c.name as comp_name
            FROM jobs j
            JOIN companies c ON c.id = j.company_id
            ORDER BY j.first_seen_at DESC
            LIMIT ?
            """,
            (limit,),
        ) as cur:
            rows = await cur.fetchall()

    if not rows:
        print("No jobs found in database. Run a scan with: python -m career_pulse.cli scan")
        return

    print(f"\nLatest {len(rows)} Discovered Jobs:")
    print("-" * 80)
    for r in rows:
        remote_tag = "[REMOTE]" if r["is_remote"] else ""
        print(f"* {r['title']} @ {r['comp_name']} ({r['location']}) {remote_tag}")
        print(f"  Apply: {r['apply_url']}")
    print("-" * 80 + "\n")


async def cmd_test_telegram():
    print("-> Testing Telegram Alert Notification Service...")
    notifier = get_telegram_notifier()
    try:
        res = await notifier.send_test_message()
        if notifier.mock_mode or not notifier.bot_token:
            print(f"[+] [MOCK MODE] Test alert recorded successfully in memory sink.")
            print(f"  Preview:\n{res.get('text')}")
        else:
            print(f"[+] [LIVE] Test alert dispatched successfully to Telegram chat {notifier.chat_id}!")
    except Exception as e:
        print(f"[x] Telegram test failed: {e}")


def cmd_serve(host: str = "127.0.0.1", port: int = 8000, reload: bool = True):
    import uvicorn
    print(f"\n=======================================================")
    print(f"  CareerPulse Web Dashboard Starting...")
    print(f"  URL: http://{host}:{port}")
    print(f"=======================================================\n")
    uvicorn.run("career_pulse.web.app:app", host=host, port=port, reload=reload)



async def cmd_schedule():
    print("-> Starting CareerPulse Resilient Background Scheduler...")
    print("  Respects configured active hours and handles laptop sleep/wake.")
    print("  Press Ctrl+C to stop.\n")
    scheduler = ResilientScheduler()
    scheduler.start()
    try:
        while True:
            await asyncio.sleep(1)
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("\nStopping scheduler...")
        await scheduler.stop()


def main():
    parser = argparse.ArgumentParser(description="CareerPulse Job Tracker & Alert Bot")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # scan
    p_scan = subparsers.add_parser("scan", help="Run immediate scan across monitored portals")
    p_scan.add_argument("--company-id", type=int, default=None, help="Scan only specific company ID")

    # add
    p_add = subparsers.add_parser("add", help="Add a company career portal")
    p_add.add_argument("name", help="Company name")
    p_add.add_argument("url", help="Company career page or ATS URL")

    # list
    subparsers.add_parser("list", help="List all registered companies")

    # jobs
    p_jobs = subparsers.add_parser("jobs", help="List discovered jobs")
    p_jobs.add_argument("--limit", type=int, default=20, help="Number of jobs to display")

    # test-telegram
    subparsers.add_parser("test-telegram", help="Send test notification to Telegram")

    # serve
    p_serve = subparsers.add_parser("serve", help="Launch local FastAPI dashboard")
    p_serve.add_argument("--host", default="127.0.0.1", help="Host address")
    p_serve.add_argument("--port", type=int, default=8000, help="Port number")
    p_serve.add_argument("--reload", action=argparse.BooleanOptionalAction, default=True, help="Enable auto-reload on code changes")

    # schedule
    subparsers.add_parser("schedule", help="Run background scheduler")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    if args.command == "serve":
        cmd_serve(host=args.host, port=args.port, reload=args.reload)
    elif args.command == "scan":
        asyncio.run(cmd_scan(company_id=args.company_id))
    elif args.command == "add":
        asyncio.run(cmd_add(name=args.name, url=args.url))
    elif args.command == "list":
        asyncio.run(cmd_list())
    elif args.command == "jobs":
        asyncio.run(cmd_jobs(limit=args.limit))
    elif args.command == "test-telegram":
        asyncio.run(cmd_test_telegram())
    elif args.command == "schedule":
        asyncio.run(cmd_schedule())


if __name__ == "__main__":
    main()
