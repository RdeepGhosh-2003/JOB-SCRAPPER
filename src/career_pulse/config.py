"""
CareerPulse Global Configuration & Settings.
"""

from pathlib import Path
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_DB_PATH = DEFAULT_DATA_DIR / "career_pulse.db"


class Settings(BaseSettings):
    """Application-wide settings with environment variable overrides."""
    model_config = SettingsConfigDict(env_prefix="CAREERPULSE_", env_file=".env", extra="ignore")

    app_name: str = "CareerPulse"
    app_version: str = "0.1.0"
    debug: bool = False

    # Server settings
    host: str = "127.0.0.1"
    port: int = 8000

    # Storage settings
    data_dir: Path = DEFAULT_DATA_DIR
    db_path: Path = DEFAULT_DB_PATH

    # Scraping & HTTP settings
    request_timeout: float = 15.0
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
    max_retries: int = 3
    retry_backoff: float = 1.0

    # Telegram Alert Settings
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    mock_telegram: bool = Field(default=False, description="Whether to route alerts to in-memory mock sink")
    telegram_mock_mode: bool = Field(default=False, description="Whether to route alerts to in-memory mock sink")

    # Scheduler Settings
    scan_interval_minutes: int = 60
    scheduler_tick_seconds: float = 5.0


settings = Settings()
