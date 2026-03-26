"""Tests for discord_utils.send_dm and discord_utils.notify_users."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

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


# ── notify_users ──────────────────────────────────────────────────────────────


async def test_notify_users_all_sent():
    """notify_users returns empty list when all DMs succeed."""
    from discord_utils import notify_users

    bot = MagicMock()
    with patch("discord_utils.send_dm", new=AsyncMock(return_value="sent")):
        failed = await notify_users(bot, [1, 2, 3], "Hello!")

    assert failed == []


async def test_notify_users_returns_failed_ids():
    """notify_users returns IDs of users whose DMs failed."""
    from discord_utils import notify_users

    bot = MagicMock()
    results = {"1": "sent", "2": "forbidden", "3": "error"}

    async def fake_send_dm(_bot, uid, _msg):
        return results[str(uid)]

    with patch("discord_utils.send_dm", new=fake_send_dm):
        failed = await notify_users(bot, [1, 2, 3], "Hello!")

    assert set(failed) == {2, 3}


async def test_notify_users_empty_list():
    """notify_users with no IDs returns empty list and sends no DMs."""
    from discord_utils import notify_users

    bot = MagicMock()
    with patch("discord_utils.send_dm", new=AsyncMock()) as mock_send:
        failed = await notify_users(bot, [], "Hello!")

    assert failed == []
    mock_send.assert_not_called()
