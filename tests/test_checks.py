"""Tests for checks.py — channel-based access control."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from discord.app_commands import CheckFailure

import checks
from checks import in_deadline_channel

DEADLINE_CHANNEL = 111222333444555666


def _make_interaction(channel_id: int) -> MagicMock:
    interaction = MagicMock()
    interaction.channel_id = channel_id
    return interaction


def _get_predicate(check_decorator):
    """Extract the predicate function from an in_deadline_channel() decorator."""

    async def _dummy(interaction):
        pass

    decorated = check_decorator(_dummy)
    return decorated.__discord_app_commands_checks__[0]


def _mock_settings(channel_id: int = DEADLINE_CHANNEL) -> MagicMock:
    s = MagicMock()
    s.deadline_channel_id = channel_id
    return s


async def test_correct_channel_passes():
    with patch.object(checks, "get_settings", return_value=_mock_settings()):
        interaction = _make_interaction(DEADLINE_CHANNEL)
        predicate = _get_predicate(in_deadline_channel())
        result = await predicate(interaction)
        assert result is True


async def test_wrong_channel_raises():
    with patch.object(checks, "get_settings", return_value=_mock_settings()):
        interaction = _make_interaction(999888777)
        predicate = _get_predicate(in_deadline_channel())
        with pytest.raises(CheckFailure):
            await predicate(interaction)


async def test_error_message_contains_channel_mention():
    with patch.object(checks, "get_settings", return_value=_mock_settings()):
        interaction = _make_interaction(000000000)
        predicate = _get_predicate(in_deadline_channel())
        with pytest.raises(CheckFailure, match=str(DEADLINE_CHANNEL)):
            await predicate(interaction)
