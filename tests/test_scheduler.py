"""
Unit and Integration Tests for ResilientScheduler.
"""

from datetime import datetime
import pytest

from career_pulse.scheduler.resilient import ResilientScheduler, SchedulerConfig, TimeWindow


def test_time_window_standard_daytime():
    """Verify standard daytime window (e.g. 10:00 to 18:30)."""
    tw = TimeWindow(start="10:00", end="18:30")

    dt_active = datetime(2026, 10, 10, 14, 0)
    assert tw.is_active(dt_active) is True

    dt_before = datetime(2026, 10, 10, 9, 30)
    assert tw.is_active(dt_before) is False

    dt_after = datetime(2026, 10, 10, 19, 0)
    assert tw.is_active(dt_after) is False


def test_time_window_overnight():
    """Verify overnight window spanning midnight (e.g. 19:00 to 02:00)."""
    tw = TimeWindow(start="19:00", end="02:00")

    dt_evening = datetime(2026, 10, 10, 21, 30)
    assert tw.is_active(dt_evening) is True

    dt_early_morning = datetime(2026, 10, 10, 1, 30)
    assert tw.is_active(dt_early_morning) is True

    dt_daytime = datetime(2026, 10, 10, 12, 0)
    assert tw.is_active(dt_daytime) is False


@pytest.mark.asyncio
async def test_scheduler_lifecycle():
    """Verify scheduler starts, reports status, and stops cleanly."""
    cfg = SchedulerConfig(
        interval_minutes=30,
        enabled=True,
        time_windows_enabled=False,
    )
    sched = ResilientScheduler(config=cfg, tick_interval_seconds=0.1)
    assert sched._running is False

    sched.start()
    assert sched._running is True

    status = sched.get_status()
    assert status.is_running is True
    assert status.config.interval_minutes == 30

    await sched.stop()
    assert sched._running is False
