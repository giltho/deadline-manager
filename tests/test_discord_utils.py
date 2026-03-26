"""Tests for discord_utils.send_dm."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import discord as discord_lib


async def test_send_dm_returns_sent_on_success():
    bot = MagicMock()
    mock_user = AsyncMock()
    mock_user.send = AsyncMock()
    bot.fetch_user = AsyncMock(return_value=mock_user)

    from discord_utils import send_dm

    result = await send_dm(bot, 42, "Hello!")

    assert result == "sent"
    bot.fetch_user.assert_awaited_once_with(42)
    mock_user.send.assert_awaited_once_with("Hello!")


async def test_send_dm_returns_forbidden_on_discord_forbidden():
    bot = MagicMock()
    mock_user = AsyncMock()
    mock_user.send = AsyncMock(
        side_effect=discord_lib.Forbidden(MagicMock(status=403), "Cannot send")
    )
    bot.fetch_user = AsyncMock(return_value=mock_user)

    from discord_utils import send_dm

    result = await send_dm(bot, 99, "Hello!")

    assert result == "forbidden"


async def test_send_dm_returns_error_on_http_exception():
    bot = MagicMock()
    mock_user = AsyncMock()
    mock_user.send = AsyncMock(
        side_effect=discord_lib.HTTPException(MagicMock(status=500), "Server error")
    )
    bot.fetch_user = AsyncMock(return_value=mock_user)

    from discord_utils import send_dm

    result = await send_dm(bot, 7, "Hello!")

    assert result == "error"
