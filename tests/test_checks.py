"""Tests for checks.py — role-based access control."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from discord.app_commands import CheckFailure

import checks
from checks import has_allowed_role


def _make_role(role_id: int) -> MagicMock:
    role = MagicMock()
    role.id = role_id
    return role


def _make_interaction(role_ids: list[int]) -> MagicMock:
    interaction = MagicMock()
    interaction.user.roles = [_make_role(rid) for rid in role_ids]
    return interaction


def _get_predicate(check_decorator):
    """Extract the predicate function from a has_allowed_role() check decorator."""

    async def _dummy(interaction):
        pass

    decorated = check_decorator(_dummy)
    return decorated.__discord_app_commands_checks__[0]


async def test_user_with_allowed_role_passes():
    mock_settings = MagicMock()
    mock_settings.parsed_role_ids = [100, 200]

    with patch.object(checks, "get_settings", return_value=mock_settings):
        interaction = _make_interaction([200, 300])
        predicate = _get_predicate(has_allowed_role())
        result = await predicate(interaction)
        assert result is True


async def test_user_without_allowed_role_raises():
    mock_settings = MagicMock()
    mock_settings.parsed_role_ids = [100, 200]

    with patch.object(checks, "get_settings", return_value=mock_settings):
        interaction = _make_interaction([300, 400])
        predicate = _get_predicate(has_allowed_role())
        with pytest.raises(CheckFailure):
            await predicate(interaction)


async def test_user_with_no_roles_raises():
    mock_settings = MagicMock()
    mock_settings.parsed_role_ids = [100]

    with patch.object(checks, "get_settings", return_value=mock_settings):
        interaction = _make_interaction([])
        predicate = _get_predicate(has_allowed_role())
        with pytest.raises(CheckFailure):
            await predicate(interaction)


async def test_empty_allowed_role_ids_rejects_everyone():
    mock_settings = MagicMock()
    mock_settings.parsed_role_ids = []

    with patch.object(checks, "get_settings", return_value=mock_settings):
        interaction = _make_interaction([100, 200, 300])
        predicate = _get_predicate(has_allowed_role())
        with pytest.raises(CheckFailure):
            await predicate(interaction)


async def test_check_failure_message():
    mock_settings = MagicMock()
    mock_settings.parsed_role_ids = [999]

    with patch.object(checks, "get_settings", return_value=mock_settings):
        interaction = _make_interaction([1])
        predicate = _get_predicate(has_allowed_role())
        with pytest.raises(CheckFailure, match="permission"):
            await predicate(interaction)
