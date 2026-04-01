"""
Tests for bot.py — specifically the @self.tree.error handler registered in setup_hook.

Strategy:
  - Instantiate DeadlineBot (no network calls)
  - Patch out all side-effectful operations in setup_hook (alembic, init_db,
    load_extension, tree.sync, tree.copy_global_to)
  - Run setup_hook so the @self.tree.error decorator fires and registers the handler
  - Invoke self.tree.on_error directly with a fake interaction and error
  - Assert the correct ephemeral reply was sent
"""

from __future__ import annotations

from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from discord import app_commands

from bot import DeadlineBot

# ── helpers ───────────────────────────────────────────────────────────────────


def _make_interaction(*, is_done: bool = False) -> MagicMock:
    interaction = MagicMock()
    interaction.response = MagicMock()
    interaction.response.is_done = MagicMock(return_value=is_done)
    interaction.response.send_message = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()
    return interaction


async def _run_setup_hook(bot: DeadlineBot) -> None:
    """Run setup_hook with all heavy I/O mocked out."""
    with (
        patch("bot.get_settings") as mock_settings,
        patch("bot.alembic_command.upgrade"),
        patch("bot.init_db", new_callable=AsyncMock),
        patch.object(bot, "load_extension", new_callable=AsyncMock),
        patch.object(bot.tree, "copy_global_to"),
        patch.object(bot.tree, "sync", new_callable=AsyncMock, return_value=[]),
    ):
        mock_settings.return_value = MagicMock(discord_guild_id=111111111111111111)
        await bot.setup_hook()


# ── tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tree_error_check_failure_replies_ephemerally() -> None:
    """CheckFailure causes an ephemeral reply with the error message."""
    bot = DeadlineBot()
    await _run_setup_hook(bot)

    interaction = _make_interaction(is_done=False)
    error = app_commands.CheckFailure("This command must be used in #deadlines.")

    await cast(AsyncMock, bot.tree.on_error)(interaction, error)

    interaction.response.send_message.assert_awaited_once_with(
        "This command must be used in #deadlines.", ephemeral=True
    )
    interaction.followup.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_tree_error_check_failure_uses_followup_when_response_done() -> None:
    """If the interaction is already responded to, followup.send is used instead."""
    bot = DeadlineBot()
    await _run_setup_hook(bot)

    interaction = _make_interaction(is_done=True)
    error = app_commands.CheckFailure("This command must be used in #deadlines.")

    await cast(AsyncMock, bot.tree.on_error)(interaction, error)

    interaction.followup.send.assert_awaited_once_with(
        "This command must be used in #deadlines.", ephemeral=True
    )
    interaction.response.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_tree_error_unexpected_error_sends_generic_message(
    mocker: MagicMock,
) -> None:
    """Non-CheckFailure errors produce a generic ephemeral reply and are logged."""
    bot = DeadlineBot()
    await _run_setup_hook(bot)

    mock_logger = mocker.patch("bot.logger")
    interaction = _make_interaction(is_done=False)
    error = app_commands.AppCommandError("something exploded")

    await cast(AsyncMock, bot.tree.on_error)(interaction, error)

    interaction.response.send_message.assert_awaited_once_with(
        "An unexpected error occurred. Please try again later.", ephemeral=True
    )
    mock_logger.exception.assert_called_once()
