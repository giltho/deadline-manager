"""
Tests for cogs/deadlines.py slash command handlers.

Discord Interaction is fully mocked — no live bot connection required.
DB operations use the in-memory SQLite engine from conftest.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import cogs.deadlines as deadlines_module
from cogs.deadlines import (
    DeadlinesCog,
    _extract_user_ids,
    _parse_due_date,
    _days_remaining,
    _sync_status_label,
)
from models import Deadline, DeadlineMember
from calendar_sync import SYNC_FAILED


# ── Unit tests for pure helpers ───────────────────────────────────────────────


def test_parse_due_date_iso():
    result = _parse_due_date("2026-06-15")
    assert result is not None
    assert result.year == 2026
    assert result.month == 6
    assert result.day == 15


def test_parse_due_date_iso_not_dayfirst():
    # Regression: 2026-07-09 must be July 9, not September 7.
    result = _parse_due_date("2026-07-09")
    assert result is not None
    assert result.month == 7
    assert result.day == 9


def test_parse_due_date_natural():
    result = _parse_due_date("15 Jun 2026 17:00")
    assert result is not None
    assert result.hour == 17


def test_parse_due_date_invalid():
    result = _parse_due_date("not-a-date-at-all!!!")
    assert result is None


def test_extract_user_ids():
    ids = _extract_user_ids("<@123> <@!456> some text <@789>")
    assert ids == [123, 456, 789]


def test_extract_user_ids_empty():
    assert _extract_user_ids("no mentions here") == []


def test_days_remaining_future():
    future = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=5)
    # timedelta.days truncates fractional days; result is 4 or 5 depending on sub-second timing
    assert _days_remaining(future) >= 4


def test_days_remaining_past_returns_zero():
    past = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
    assert _days_remaining(past) == 0


def test_sync_status_label_disabled():
    assert _sync_status_label(None, sync_enabled=False) == "Disabled"


def test_sync_status_label_not_synced():
    assert _sync_status_label(None, sync_enabled=True) == "Not synced"


def test_sync_status_label_failed():
    assert _sync_status_label(SYNC_FAILED, sync_enabled=True) == "Sync failed"


def test_sync_status_label_synced():
    label = _sync_status_label("evt-abc123xyz", sync_enabled=True)
    assert "Synced" in label


# ── Integration-style tests (DB + mocked interaction) ─────────────────────────


@asynccontextmanager
async def _session_ctx(session: AsyncSession):
    yield session


def _make_cog(bot=None):
    if bot is None:
        bot = MagicMock()
        bot.cogs = {}
    mock_settings = MagicMock()
    mock_settings.allowed_role_ids = [999]
    mock_settings.reminder_channel_id = 1
    mock_settings.calendar_sync_enabled = False

    cog = DeadlinesCog.__new__(DeadlinesCog)
    cog.bot = bot
    cog._settings = mock_settings
    cog._calendar = None
    return cog


async def _seed_deadline(
    session: AsyncSession, title="Alpha", days_ahead=10
) -> Deadline:
    dl = Deadline(
        title=title,
        due_date=datetime.now(timezone.utc).replace(tzinfo=None)
        + timedelta(days=days_ahead),
        created_by=1,
    )
    session.add(dl)
    await session.flush()
    session.add(DeadlineMember(deadline_id=dl.id, user_id=1))
    await session.commit()
    await session.refresh(dl)
    return dl


# /deadline add ────────────────────────────────────────────────────────────────


async def test_add_creates_deadline(db_session, mock_interaction):
    cog = _make_cog()
    mock_interaction.user.id = 1

    with (
        patch.object(
            deadlines_module, "get_session", return_value=_session_ctx(db_session)
        ),
        patch.object(
            deadlines_module, "get_deadline_members", new=AsyncMock(return_value=[])
        ),
    ):
        await cog.deadline_add.callback(
            cog,
            mock_interaction,
            title="New Deadline",
            due_date="2027-01-01",
            members=None,
            description="Test desc",
        )

    mock_interaction.response.send_message.assert_called_once()
    call_kwargs = mock_interaction.response.send_message.call_args.kwargs
    assert call_kwargs.get("ephemeral") is True


async def test_add_invalid_date_replies_ephemeral(db_session, mock_interaction):
    cog = _make_cog()

    with patch.object(
        deadlines_module, "get_session", return_value=_session_ctx(db_session)
    ):
        await cog.deadline_add.callback(
            cog,
            mock_interaction,
            title="Bad Date",
            due_date="not-a-date",
            members=None,
            description=None,
        )

    mock_interaction.response.send_message.assert_called_once()
    assert (
        mock_interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    )


async def test_add_duplicate_title_replies_ephemeral(db_session, mock_interaction):
    cog = _make_cog()
    mock_interaction.user.id = 1

    await _seed_deadline(db_session, title="Duplicate")

    with patch.object(
        deadlines_module, "get_session", return_value=_session_ctx(db_session)
    ):
        await cog.deadline_add.callback(
            cog,
            mock_interaction,
            title="Duplicate",
            due_date="2027-01-01",
            members=None,
            description=None,
        )

    assert (
        mock_interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    )


# /deadline list ───────────────────────────────────────────────────────────────


async def test_list_returns_embed(db_session, mock_interaction):
    cog = _make_cog()
    await _seed_deadline(db_session, title="Alpha")
    await _seed_deadline(db_session, title="Beta", days_ahead=20)

    with (
        patch.object(
            deadlines_module,
            "get_upcoming_deadlines",
            new=AsyncMock(
                return_value=[
                    await _seed_deadline(db_session, title="Gamma"),
                ]
            ),
        ),
        patch.object(
            deadlines_module, "get_deadline_members", new=AsyncMock(return_value=[])
        ),
    ):
        await cog.deadline_list.callback(cog, mock_interaction, days=None)

    mock_interaction.response.send_message.assert_called_once()
    assert (
        mock_interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    )


async def test_show_everyone_is_not_ephemeral(db_session, mock_interaction):
    cog = _make_cog()

    with (
        patch.object(
            deadlines_module, "get_upcoming_deadlines", new=AsyncMock(return_value=[])
        ),
        patch.object(
            deadlines_module, "get_deadline_members", new=AsyncMock(return_value=[])
        ),
    ):
        await cog.deadline_show_everyone.callback(
            cog, mock_interaction, days=None, title=None
        )

    mock_interaction.response.send_message.assert_called_once()
    assert (
        mock_interaction.response.send_message.call_args.kwargs.get("ephemeral")
        is False
    )


async def test_show_everyone_single_deadline(db_session, mock_interaction):
    cog = _make_cog()
    dl = await _seed_deadline(db_session, title="Single Show")

    with (
        patch.object(
            deadlines_module, "get_deadline_by_title", new=AsyncMock(return_value=dl)
        ),
        patch.object(
            deadlines_module, "get_deadline_members", new=AsyncMock(return_value=[])
        ),
    ):
        await cog.deadline_show_everyone.callback(
            cog, mock_interaction, days=None, title="Single Show"
        )

    mock_interaction.response.send_message.assert_called_once()
    call_kwargs = mock_interaction.response.send_message.call_args.kwargs
    assert call_kwargs.get("ephemeral") is False
    assert "embed" in call_kwargs


async def test_show_everyone_single_deadline_not_found(mock_interaction):
    cog = _make_cog()

    with patch.object(
        deadlines_module, "get_deadline_by_title", new=AsyncMock(return_value=None)
    ):
        await cog.deadline_show_everyone.callback(
            cog, mock_interaction, days=None, title="Ghost"
        )

    assert (
        mock_interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    )


async def test_list_always_filters_by_invoking_user(db_session, mock_interaction):
    cog = _make_cog()
    mock_interaction.user.id = 42

    captured_user_id = {}

    async def fake_get_upcoming(days=None, user_id=None):
        captured_user_id["value"] = user_id
        return []

    with (
        patch.object(deadlines_module, "get_upcoming_deadlines", new=fake_get_upcoming),
        patch.object(
            deadlines_module, "get_deadline_members", new=AsyncMock(return_value=[])
        ),
    ):
        await cog.deadline_list.callback(cog, mock_interaction, days=None)

    assert captured_user_id["value"] == 42


# /deadline info ───────────────────────────────────────────────────────────────


async def test_info_found(db_session, mock_interaction):
    cog = _make_cog()
    dl = await _seed_deadline(db_session, title="Info Test")

    with (
        patch.object(
            deadlines_module, "get_deadline_by_title", new=AsyncMock(return_value=dl)
        ),
        patch.object(
            deadlines_module, "get_deadline_members", new=AsyncMock(return_value=[])
        ),
    ):
        await cog.deadline_info.callback(cog, mock_interaction, title="Info Test")

    mock_interaction.response.send_message.assert_called_once()


async def test_info_not_found(db_session, mock_interaction):
    cog = _make_cog()

    with patch.object(
        deadlines_module, "get_deadline_by_title", new=AsyncMock(return_value=None)
    ):
        await cog.deadline_info.callback(cog, mock_interaction, title="Ghost")

    assert (
        mock_interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    )


# /deadline edit ───────────────────────────────────────────────────────────────


async def test_edit_updates_title(db_session, mock_interaction):
    cog = _make_cog()
    dl = await _seed_deadline(db_session, title="Old Title")

    with (
        patch.object(
            deadlines_module, "get_deadline_by_title", new=AsyncMock(return_value=dl)
        ),
        patch.object(
            deadlines_module, "get_session", return_value=_session_ctx(db_session)
        ),
        patch.object(
            deadlines_module, "get_deadline_members", new=AsyncMock(return_value=[])
        ),
    ):
        await cog.deadline_edit.callback(
            cog,
            mock_interaction,
            title="Old Title",
            new_title="New Title",
            due_date=None,
            description=None,
        )

    mock_interaction.response.send_message.assert_called_once()
    # Verify the title was updated in DB
    from sqlmodel import select as sql_select

    result = await db_session.exec(
        sql_select(Deadline).where(Deadline.title == "New Title")
    )
    assert result.first() is not None


async def test_edit_no_fields_replies_ephemeral(mock_interaction):
    cog = _make_cog()

    await cog.deadline_edit.callback(
        cog,
        mock_interaction,
        title="Any",
        new_title=None,
        due_date=None,
        description=None,
    )

    assert (
        mock_interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    )


async def test_edit_success_is_ephemeral(db_session, mock_interaction):
    cog = _make_cog()
    dl = await _seed_deadline(db_session, title="Edit Ephemeral")

    with (
        patch.object(
            deadlines_module, "get_deadline_by_title", new=AsyncMock(return_value=dl)
        ),
        patch.object(
            deadlines_module, "get_session", return_value=_session_ctx(db_session)
        ),
        patch.object(
            deadlines_module, "get_deadline_members", new=AsyncMock(return_value=[])
        ),
    ):
        await cog.deadline_edit.callback(
            cog,
            mock_interaction,
            title="Edit Ephemeral",
            new_title="Edit Ephemeral 2",
            due_date=None,
            description=None,
        )

    assert (
        mock_interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    )


# /deadline assign ─────────────────────────────────────────────────────────────


async def test_assign_adds_member(db_session, mock_interaction):
    cog = _make_cog()
    dl = await _seed_deadline(db_session, title="Assign Test")

    with (
        patch.object(
            deadlines_module, "get_deadline_by_title", new=AsyncMock(return_value=dl)
        ),
        patch.object(
            deadlines_module, "get_session", return_value=_session_ctx(db_session)
        ),
    ):
        await cog.deadline_assign.callback(
            cog,
            mock_interaction,
            title="Assign Test",
            add="<@555>",
            remove=None,
        )

    from sqlmodel import select as sql_select

    result = await db_session.exec(
        sql_select(DeadlineMember).where(
            DeadlineMember.deadline_id == dl.id,
            DeadlineMember.user_id == 555,
        )
    )
    assert result.first() is not None


async def test_assign_no_add_or_remove_replies_ephemeral(mock_interaction):
    cog = _make_cog()

    await cog.deadline_assign.callback(
        cog, mock_interaction, title="Any", add=None, remove=None
    )

    assert (
        mock_interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    )


# /deadline delete ─────────────────────────────────────────────────────────────


async def test_delete_shows_confirmation(db_session, mock_interaction):
    cog = _make_cog()
    dl = await _seed_deadline(db_session, title="To Delete")

    with patch.object(
        deadlines_module, "get_deadline_by_title", new=AsyncMock(return_value=dl)
    ):
        await cog.deadline_delete.callback(cog, mock_interaction, title="To Delete")

    mock_interaction.response.send_message.assert_called_once()
    # Should include a view (the confirmation buttons)
    call_kwargs = mock_interaction.response.send_message.call_args.kwargs
    assert "view" in call_kwargs


async def test_delete_not_found_replies_ephemeral(mock_interaction):
    cog = _make_cog()

    with patch.object(
        deadlines_module, "get_deadline_by_title", new=AsyncMock(return_value=None)
    ):
        await cog.deadline_delete.callback(cog, mock_interaction, title="Ghost")

    assert (
        mock_interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    )


async def test_do_delete_removes_from_db(db_session, mock_interaction):
    cog = _make_cog()
    dl = await _seed_deadline(db_session, title="Delete Me")

    with patch.object(
        deadlines_module, "get_session", return_value=_session_ctx(db_session)
    ):
        await cog._do_delete(mock_interaction, dl)

    from sqlmodel import select as sql_select

    result = await db_session.exec(
        sql_select(Deadline).where(Deadline.title == "Delete Me")
    )
    assert result.first() is None
