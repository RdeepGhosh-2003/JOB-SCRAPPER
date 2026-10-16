"""
Unified Scan Pipeline Orchestrator for CareerPulse.

Coordinates:
1. Loading target companies from SQLite.
2. Direct ATS API adapters and scraping fallbacks.
3. Matching and filtering via JobMatcher.
4. Atomic deduplication and persistence in SQLite.
5. Formatted alert dispatch via TelegramNotifier.
"""

import asyncio
from datetime import datetime, timezone
import logging
import time
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from career_pulse.config import settings
from career_pulse.core.matching import JobMatcher
from career_pulse.core.models import (
    FilterResult,
    JobFilterConfig,
    JobListing,
    ProviderType,
)
from career_pulse.db.session import Database
from career_pulse.adapters.greenhouse import GreenhouseAdapter
from career_pulse.adapters.lever import LeverAdapter
from career_pulse.adapters.ashby import AshbyAdapter
from career_pulse.adapters.workday import WorkdayAdapter
from career_pulse.adapters.fallback import FallbackScraper
from career_pulse.adapters.detector import ATSDetector
from career_pulse.services.telegram import TelegramNotifier, get_telegram_notifier

logger = logging.getLogger("career_pulse.pipeline")


class ScanCompanyResult(BaseModel):
    company_id: int
    company_name: str
    provider: str
    total_found: int = 0
    total_matched: int = 0
    new_alerts: int = 0
    status: str = "success"
    error: Optional[str] = None


class ScanReport(BaseModel):
    started_at: datetime
    finished_at: datetime
    duration_seconds: float
    companies_scanned: int = 0
    total_jobs_found: int = 0
    total_jobs_matched: int = 0
    new_alerts_sent: int = 0
    company_results: List[ScanCompanyResult] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)


class ScanPipeline:
    """
    Coordinates end-to-end scanning across configured company career portals.
    """

    def __init__(
        self,
        db: Optional[Database] = None,
        notifier: Optional[TelegramNotifier] = None,
    ):
        self.db = db or Database(settings.db_path)
        self.notifier = notifier or get_telegram_notifier()
        self._gh_adapter = GreenhouseAdapter()
        self._lever_adapter = LeverAdapter()
        self._ashby_adapter = AshbyAdapter()
        self._workday_adapter = WorkdayAdapter()
        self._fallback_scraper = FallbackScraper()
        self._detector = ATSDetector()

    async def get_filter_config(self) -> JobFilterConfig:
        """Loads filter configuration from settings table, or falls back to defaults."""
        raw = await self.db.get_setting("filter_config")
        if raw and isinstance(raw, dict):
            try:
                return JobFilterConfig(**raw)
            except Exception as e:
                logger.warning(f"Invalid saved filter_config, falling back to defaults: {e}")
        return JobFilterConfig()

    async def save_filter_config(self, config: JobFilterConfig) -> None:
        """Saves updated filter configuration into database settings."""
        await self.db.set_setting("filter_config", config.model_dump())

    def _get_adapter(self, provider: str):
        prov = (provider or "custom").lower()
        if prov == "greenhouse":
            return self._gh_adapter
        elif prov == "lever":
            return self._lever_adapter
        elif prov == "ashby":
            return self._ashby_adapter
        elif prov == "workday":
            return self._workday_adapter
        else:
            return self._fallback_scraper

    async def scan_company(
        self,
        company: Dict[str, Any],
        matcher: JobMatcher,
    ) -> ScanCompanyResult:
        """Scans a single company, stores jobs, and sends alerts for new matches."""
        comp_id = int(company["id"])
        comp_name = company["name"]
        career_url = company.get("career_url") or company.get("url") or ""
        provider = (company.get("ats_provider") or company.get("provider") or "custom").lower()
        identifier = company.get("identifier")

        result = ScanCompanyResult(
            company_id=comp_id,
            company_name=comp_name,
            provider=provider,
        )

        _t0 = time.monotonic()
        try:
            # If identifier is missing, attempt to extract via detector
            if not identifier and career_url:
                det = ATSDetector.match_url(career_url)
                if det:
                    provider = det.provider
                    identifier = det.identifier
                    result.provider = provider

            adapter = self._get_adapter(provider)

            # Fetch jobs based on adapter requirements
            jobs: List[JobListing] = []
            target = identifier or career_url
            if provider == "workday":
                career_site = company.get("career_site")
                jobs = await self._workday_adapter.fetch_jobs(
                    company_identifier=target,
                    career_site=career_site or "",
                    company_name=comp_name,
                )
            elif provider in ("greenhouse", "lever", "ashby"):
                jobs = await adapter.fetch_jobs(
                    company_identifier=target,
                    company_name=comp_name,
                )
            else:
                jobs = await self._fallback_scraper.fetch_jobs(
                    company_identifier=career_url,
                    company_name=comp_name,
                )

            result.total_found = len(jobs)

            # Evaluate each job
            for job in jobs:
                job_id, is_new = await self.db.upsert_job(comp_id, job)
                filter_res = matcher.evaluate(job)

                if filter_res.matched:
                    result.total_matched += 1

                    # Atomic reservation for alert
                    reserved = await self.db.reserve_alert_slot(job_id, "telegram")
                    if reserved:
                        # Dispatch Telegram notification
                        try:
                            msg = await self.notifier.dispatch_alert(
                                company_name=comp_name,
                                job=job,
                                filter_result=filter_res,
                            )
                            status = "mock" if (self.notifier.mock_mode or not self.notifier.bot_token) else "sent"
                            preview = msg.get("text") if isinstance(msg, dict) else str(msg)
                            await self.db.finalize_alert_status(
                                job_id=job_id,
                                channel="telegram",
                                status=status,
                                preview=preview,
                            )
                            result.new_alerts += 1
                        except Exception as alert_err:
                            logger.error(f"Failed to dispatch Telegram alert for job {job_id}: {alert_err}")
                            await self.db.finalize_alert_status(
                                job_id=job_id,
                                channel="telegram",
                                status="failed",
                                error=str(alert_err),
                            )

            # Update company status in database
            async with await self.db.get_connection() as conn:
                await conn.execute(
                    """
                    UPDATE companies
                    SET last_scanned_at = CURRENT_TIMESTAMP,
                        scan_status = 'success',
                        last_error = NULL
                    WHERE id = ?
                    """,
                    (comp_id,),
                )
                await conn.commit()

        except Exception as e:
            err_msg = str(e)
            logger.error(f"Error scanning company {comp_name} ({comp_id}): {err_msg}")
            result.status = "failed"
            result.error = err_msg

            # Update company error status
            async with await self.db.get_connection() as conn:
                await conn.execute(
                    """
                    UPDATE companies
                    SET last_scanned_at = CURRENT_TIMESTAMP,
                        scan_status = 'failed',
                        last_error = ?
                    WHERE id = ?
                    """,
                    (err_msg, comp_id),
                )
                await conn.commit()

        finally:
            duration = round(time.monotonic() - _t0, 2)
            if result.status == "failed" or result.error:
                log_status = "failed"
            elif result.total_found > 0:
                log_status = "success"
            else:
                log_status = "warning"

            try:
                await self.db.write_scan_log(
                    company_id=comp_id,
                    company_name=comp_name,
                    provider=result.provider,
                    jobs_found=result.total_found,
                    jobs_matched=result.total_matched,
                    alerts_sent=result.new_alerts,
                    duration_seconds=duration,
                    status=log_status,
                    error_message=result.error,
                )
            except Exception as log_err:
                logger.warning(f"Failed to write scan log for {comp_name}: {log_err}")

        return result

    async def run_scan(self, company_id: Optional[int] = None) -> ScanReport:
        """Executes full scan across all active or specified company portals."""
        start_time = datetime.now(timezone.utc)
        filter_config = await self.get_filter_config()
        matcher = JobMatcher(filter_config)

        # Retrieve companies
        query = "SELECT * FROM companies WHERE 1=1"
        params: List[Any] = []
        if company_id is not None:
            query += " AND id = ?"
            params.append(company_id)
        else:
            query += " AND is_active = 1"

        async with await self.db.get_connection() as conn:
            async with conn.execute(query, tuple(params)) as cursor:
                rows = await cursor.fetchall()
                companies = [dict(r) for r in rows]

        report = ScanReport(
            started_at=start_time,
            finished_at=start_time,
            duration_seconds=0.0,
            companies_scanned=len(companies),
        )

        for comp in companies:
            res = await self.scan_company(comp, matcher)
            report.company_results.append(res)
            report.total_jobs_found += res.total_found
            report.total_jobs_matched += res.total_matched
            report.new_alerts_sent += res.new_alerts
            if res.error:
                report.errors.append(f"{res.company_name}: {res.error}")

        finish_time = datetime.now(timezone.utc)
        report.finished_at = finish_time
        report.duration_seconds = round((finish_time - start_time).total_seconds(), 2)
        return report
