"""
Services package for CareerPulse (Notifications, External Integrations).
"""

from .telegram import MockTelegramSink, TelegramNotifier, dispatch_job_alert

__all__ = ["TelegramNotifier", "MockTelegramSink", "dispatch_job_alert"]
