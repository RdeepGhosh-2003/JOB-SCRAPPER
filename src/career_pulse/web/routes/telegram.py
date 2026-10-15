"""
Telegram Settings and Test Dispatch REST Endpoints.
"""

from typing import Any, Dict, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from career_pulse.config import settings
from career_pulse.db.session import Database
from career_pulse.services.telegram import TelegramNotifier, get_telegram_notifier

router = APIRouter(prefix="/api/telegram", tags=["telegram"])
db = Database(settings.db_path)


class TelegramSettingsRequest(BaseModel):
    bot_token: Optional[str] = None
    chat_id: Optional[str] = None
    mock_mode: bool = False


@router.get("/settings")
async def get_telegram_settings() -> Dict[str, Any]:
    """Get current Telegram configuration (with masked token)."""
    saved = await db.get_setting("telegram_config", {})
    token = saved.get("bot_token") or settings.telegram_bot_token or ""
    chat_id = saved.get("chat_id") or settings.telegram_chat_id or ""
    mock_mode = saved.get("mock_mode", settings.telegram_mock_mode)

    masked_token = (token[:6] + "..." + token[-4:]) if len(token) > 10 else ("***" if token else "")

    return {
        "bot_token": masked_token,
        "has_token": bool(token),
        "chat_id": chat_id,
        "mock_mode": mock_mode,
    }


@router.post("/settings")
async def update_telegram_settings(req: TelegramSettingsRequest) -> Dict[str, Any]:
    """Update Telegram bot credentials and mock mode."""
    saved = await db.get_setting("telegram_config", {})
    
    # Only update token if provided and not masked
    if req.bot_token and not req.bot_token.startswith("***") and "..." not in req.bot_token:
        saved["bot_token"] = req.bot_token.strip()
    
    if req.chat_id is not None:
        saved["chat_id"] = req.chat_id.strip()

    saved["mock_mode"] = req.mock_mode

    await db.set_setting("telegram_config", saved)
    return {"success": True, "message": "Telegram settings updated"}


@router.post("/test")
async def test_telegram_message() -> Dict[str, Any]:
    """Dispatch a test message to verify Telegram bot setup."""
    saved = await db.get_setting("telegram_config", {})
    token = saved.get("bot_token") or settings.telegram_bot_token
    chat_id = saved.get("chat_id") or settings.telegram_chat_id
    mock_mode = saved.get("mock_mode", settings.telegram_mock_mode)

    notifier = TelegramNotifier(
        bot_token=token,
        chat_id=chat_id,
        mock_mode=mock_mode,
    )

    try:
        res = await notifier.send_test_message()
        return {
            "success": True,
            "mock": mock_mode,
            "message": "Test alert sent successfully!",
            "details": res,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Telegram verification failed: {e}")
