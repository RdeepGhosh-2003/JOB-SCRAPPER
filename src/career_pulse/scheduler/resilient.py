"""
Resilient Background Scheduler for CareerPulse.

Implements sleep/wake resilience with:
1. High-frequency tick loop (5-10s) using RTC wall-clock comparisons.
2. Active time windows (e.g. 10:00 AM-6:30 PM, 7:00 PM-2:00 AM).
3. Concurrency guard preventing overlapping scans.
4. Single catch-up execution upon system wake (no execution storms).
"""

import asyncio
from datetime import datetime, time, timedelta, timezone
import logging
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field

from career_pulse.core.pipeline import ScanPipeline, ScanReport

logger = logging.getLogger("career_pulse.scheduler")


class TimeWindow(BaseModel):
    """Time window in local 24-hour time (e.g. start='10:00', end='18:30')."""
    start: str = Field(..., description="Start time HH:MM")
    end: str = Field(..., description="End time HH:MM")

    def is_active(self, current_dt: Optional[datetime] = None) -> bool:
        """Determines if the given local datetime falls within this active window."""
        now = (current_dt or datetime.now()).time()
        s_parts = [int(p) for p in self.start.split(":")]
        e_parts = [int(p) for p in self.end.split(":")]
        s_time = time(s_parts[0], s_parts[1])
        e_time = time(e_parts[0], e_parts[1])

        if s_time <= e_time:
            # Standard single-day window (e.g. 10:00 to 18:30)
            return s_time <= now <= e_time
        else:
            # Overnight window spanning midnight (e.g. 19:00 to 02:00)
            return now >= s_time or now <= e_time


class SchedulerConfig(BaseModel):
    interval_minutes: int = Field(default=60, description="Scan interval in minutes")
    enabled: bool = Field(default=True, description="Whether background scanning is enabled")
    time_windows_enabled: bool = Field(default=True, description="Enforce specific daily operating hours")
    time_windows: List[TimeWindow] = Field(
        default_factory=lambda: [
            TimeWindow(start="10:00", end="18:30"),  # Morning & afternoon shift
            TimeWindow(start="19:00", end="02:00"),  # Evening & night shift
        ],
        description="Daily operating hours"
    )


class SchedulerStatus(BaseModel):
    is_running: bool = False
    is_scanning: bool = False
    last_run_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None
    total_runs: int = 0
    in_active_window: bool = True
    config: SchedulerConfig


class ResilientScheduler:
    """
    Sleep/Wake Resilient Background Scheduler for CareerPulse.
    """

    def __init__(
        self,
        pipeline: Optional[ScanPipeline] = None,
        config: Optional[SchedulerConfig] = None,
        tick_interval_seconds: float = 5.0,
    ):
        self.pipeline = pipeline or ScanPipeline()
        self.config = config or SchedulerConfig()
        self.tick_interval_seconds = tick_interval_seconds

        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        self._last_run_at: Optional[datetime] = None
        self._next_run_at: Optional[datetime] = None
        self._total_runs: int = 0
        self._last_report: Optional[ScanReport] = None

    def is_in_active_window(self, dt: Optional[datetime] = None) -> bool:
        """Returns True if current time is within enabled time windows, or if windows disabled."""
        if not self.config.time_windows_enabled or not self.config.time_windows:
            return True
        check_dt = dt or datetime.now()
        return any(window.is_active(check_dt) for window in self.config.time_windows)

    def get_status(self) -> SchedulerStatus:
        """Returns current scheduler state."""
        return SchedulerStatus(
            is_running=self._running,
            is_scanning=self._lock.locked(),
            last_run_at=self._last_run_at,
            next_run_at=self._next_run_at,
            total_runs=self._total_runs,
            in_active_window=self.is_in_active_window(),
            config=self.config,
        )

    async def trigger_now(self) -> Optional[ScanReport]:
        """Triggers an immediate scan run guarded by concurrency lock."""
        if self._lock.locked():
            logger.info("Scan already in progress. Skipping trigger.")
            return None

        async with self._lock:
            logger.info("Starting scheduled scan pipeline execution...")
            now = datetime.now(timezone.utc)
            self._last_run_at = now
            try:
                report = await self.pipeline.run_scan()
                self._last_report = report
                self._total_runs += 1
                logger.info(
                    f"Scan complete: {report.companies_scanned} companies, "
                    f"{report.total_jobs_found} jobs, {report.new_alerts_sent} alerts sent."
                )
                return report
            except Exception as e:
                logger.error(f"Error executing scan pipeline: {e}")
                return None
            finally:
                # Set next scheduled run forward from current wall clock
                self._next_run_at = datetime.now(timezone.utc) + timedelta(minutes=self.config.interval_minutes)

    async def _loop(self) -> None:
        """Resilient background polling loop using wall-clock RTC comparison."""
        logger.info("CareerPulse Resilient Scheduler started.")
        self._next_run_at = datetime.now(timezone.utc)

        while self._running:
            try:
                now_utc = datetime.now(timezone.utc)
                local_now = datetime.now()

                if self.config.enabled:
                    # Check if in operating window
                    if self.is_in_active_window(local_now):
                        # Check if scheduled time has arrived or was passed during system sleep
                        if self._next_run_at is None or now_utc >= self._next_run_at:
                            await self.trigger_now()
                    else:
                        logger.debug("Currently outside configured operating time windows.")

                await asyncio.sleep(self.tick_interval_seconds)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Unexpected error in scheduler loop: {e}")
                await asyncio.sleep(self.tick_interval_seconds)

        logger.info("CareerPulse Resilient Scheduler stopped.")

    def start(self) -> None:
        """Starts the scheduler in the current asyncio event loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        """Gracefully stops the scheduler loop."""
        if not self._running:
            return
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
