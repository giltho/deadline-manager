"""
Tests for cogs/deadlines.py slash command handlers.

Discord Interaction is fully mocked — no live bot connection required.
DB operations use the in-memory SQLite engine from conftest.
DeadlineAccess is mocked at the cogs.deadlines module level.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.ext.asyncio import AsyncSession

import cogs.deadlines as deadlines_module
from calendar_sync import SYNC_FAILED
from cogs.deadlines import (
    DeadlinesCog,
    _days_remaining,
    _extract_user_ids,
    _parse_due_date,
    _pending_reminder_times,
    _sync_status_label,
)
from models import Deadline, DeadlineMember

# ── Unit tests for pure helpers ───────────────────────────────────────────────


def test_parse_due_date_iso():
    # Date-only ISO: should default to 23:59:59 UK time (GMT in January = UTC+0)
    result = _parse_due_date("2026-01-15")
    assert result is not None
    assert result.year == 2026
    assert result.month == 1
    assert result.day == 15
    assert result.hour == 23
    assert result.minute == 59
    assert result.second == 59


def test_parse_due_date_iso_bst():
    # Date-only in BST season (June, UK = UTC+1): 23:59:59 BST = 22:59:59 UTC
    result = _parse_due_date("2026-06-15")
    assert result is not None
    assert result.year == 2026
    assert result.month == 6
    assert result.day == 15
    assert result.hour == 22
    assert result.minute == 59
    assert result.second == 59


def test_parse_due_date_iso_not_dayfirst():
    # Regression: 2026-07-09 must be July 9, not September 7.
    result = _parse_due_date("2026-07-09")
    assert result is not None
    assert result.month == 7
    assert result.day == 9


def test_parse_due_date_natural_no_time():
    # Natural date without time: defaults to 23:59:59 UK time
    result = _parse_due_date("15 Jan 2026")
    assert result is not None
    assert result.hour == 23
    assert result.minute == 59
    assert result.second == 59


def test_parse_due_date_natural_with_time():
    # Explicit time without offset is interpreted as UK time.
    # June is BST (UTC+1): 17:00 BST = 16:00 UTC
    result = _parse_due_date("15 Jun 2026 17:00")
    assert result is not None
    assert result.hour == 16
    assert result.minute == 0


def test_parse_due_date_explicit_time_preserved():
    # Explicit time should not be overridden to 23:59:59 and is UK time.
    # June is BST (UTC+1): 09:30 BST = 08:30 UTC
    result = _parse_due_date("2026-06-15 09:30")
    assert result is not None
    assert result.hour == 8
    assert result.minute == 30


def test_parse_due_date_explicit_time_winter():
    # January is GMT (UTC+0): 17:00 GMT = 17:00 UTC (no offset)
    result = _parse_due_date("2026-01-15 17:00")
    assert result is not None
    assert result.year == 2026
    assert result.month == 1
    assert result.day == 15
    assert result.hour == 17
    assert result.minute == 0


def test_parse_due_date_explicit_time_with_tz_offset():
    # Tz-aware input: the supplied offset must be honoured, not overridden.
    # 17:00+05:30 = 11:30 UTC
    result = _parse_due_date("2026-06-15 17:00+05:30")
    assert result is not None
    assert result.year == 2026
    assert result.month == 6
    assert result.day == 15
    assert result.hour == 11
    assert result.minute == 30


def test_parse_due_date_aoe_lowercase():
    # "aoe" suffix (lowercase) — 23:59:59 UTC-12 = next day 11:59:59 UTC
    result = _parse_due_date("2026-06-15 aoe")
    assert result is not None
    assert result.year == 2026
    assert result.month == 6
    assert result.day == 16
    assert result.hour == 11
    assert result.minute == 59
    assert result.second == 59


def test_parse_due_date_aoe_uppercase():
    result = _parse_due_date("2026-06-15 AOE")
    assert result is not None
    assert result.day == 16
    assert result.hour == 11


def test_parse_due_date_aoe_mixed_case():
    result = _parse_due_date("2026-06-15 AoE")
    assert result is not None
    assert result.day == 16
    assert result.hour == 11


def test_parse_due_date_aoe_natural_date():
    result = _parse_due_date("15 Jun 2026 AoE")
    assert result is not None
    assert result.month == 6
    assert result.day == 16
    assert result.hour == 11
    assert result.minute == 59
    assert result.second == 59


def test_parse_due_date_aoe_alone_returns_none():
    # "aoe" without a date is invalid
    assert _parse_due_date("aoe") is None
    assert _parse_due_date("AOE") is None
    assert _parse_due_date("AoE") is None


def test_parse_due_date_invalid():
    result = _parse_due_date("not-a-date-at-all!!!")
    assert result is None


def test_extract_user_ids():
    ids = _extract_user_ids("<@123> <@!456> some text <@789>")
    assert ids == [123, 456, 789]


def test_extract_user_ids_empty():
    assert _extract_user_ids("no mentions here") == []


def test_days_remaining_future():
    future = datetime.now(UTC).replace(tzinfo=None) + timedelta(days=5)
    # timedelta.days truncates fractional days; result is 4 or 5 depending on timing
    assert _days_remaining(future) >= 4


def test_days_remaining_past_returns_zero():
    past = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1)
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


# ── _pending_reminder_times ───────────────────────────────────────────────────


def test_pending_reminder_times_all_future():
    # Due in 31 days: all five offsets (30, 14, 7, 3, 1) should be pending
    now = datetime.now(UTC).replace(tzinfo=None)
    due = now + timedelta(days=31)
    pending = _pending_reminder_times(due, now)
    assert len(pending) == 5
    fire_times = [ft for _, ft in pending]
    # Results are sorted ascending by fire time (30d fires first, 1d fires last)
    assert fire_times == sorted(fire_times)
    assert [d for d, _ in pending] == [30, 14, 7, 3, 1]


def test_pending_reminder_times_partial():
    # Due in 5 days: only 3d and 1d are still in the future
    now = datetime.now(UTC).replace(tzinfo=None)
    due = now + timedelta(days=5)
    pending = _pending_reminder_times(due, now)
    assert [d for d, _ in pending] == [3, 1]


def test_pending_reminder_times_none_left():
    # Overdue: no reminders pending
    now = datetime.now(UTC).replace(tzinfo=None)
    due = now - timedelta(days=1)
    pending = _pending_reminder_times(due, now)
    assert pending == []


# ── Integration-style tests (DB + mocked interaction) ─────────────────────────


@asynccontextmanager
async def _session_ctx(session: AsyncSession):
    yield session


def _make_cog(bot=None):
    if bot is None:
        bot = MagicMock()
        bot.cogs = {}
    mock_settings = MagicMock()
    mock_settings.deadline_channel_id = 777
    mock_settings.reminder_channel_id = 1
    mock_settings.calendar_sync_enabled = False

    cog = DeadlinesCog.__new__(DeadlinesCog)
    cog.bot = bot
    cog._settings = mock_settings
    cog._calendar = None
    return cog


def _make_access_mock(**kwargs) -> MagicMock:
    """
    Return a MagicMock that behaves like DeadlineAccess.
    Pass keyword args to pre-configure return values, e.g.:
      get_by_title=some_deadline
      list_upcoming=[dl1, dl2]
      autocomplete=["Title A"]
      create=some_deadline
      edit=some_deadline
      assign=([], [])
      delete=some_deadline
    """
    access = MagicMock()
    access.get_by_title = AsyncMock(return_value=kwargs.get("get_by_title", None))
    access.list_upcoming = AsyncMock(return_value=kwargs.get("list_upcoming", []))
    access.autocomplete = AsyncMock(return_value=kwargs.get("autocomplete", []))
    access.create = AsyncMock(return_value=kwargs.get("create", None))
    access.edit = AsyncMock(return_value=kwargs.get("edit", None))
    access.assign = AsyncMock(return_value=kwargs.get("assign", None))
    access.delete = AsyncMock(return_value=kwargs.get("delete", None))
    return access


async def _seed_deadline(
    session: AsyncSession, title="Alpha", days_ahead=10
) -> Deadline:
    dl = Deadline(
        title=title,
        due_date=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=days_ahead),
        created_by=1,
    )
    session.add(dl)
    await session.flush()
    assert dl.id is not None
    session.add(DeadlineMember(deadline_id=dl.id, user_id=1))
    await session.commit()
    await session.refresh(dl)
    return dl


# /deadline add ────────────────────────────────────────────────────────────────


async def test_add_creates_deadline(db_session, mock_interaction):
    cog = _make_cog()
    mock_interaction.user.id = 1

    dl = Deadline(
        id=1,
        title="New Deadline",
        due_date=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=10),
        created_by=1,
        created_at=datetime.now(UTC).replace(tzinfo=None),
    )
    access = _make_access_mock(create=dl)

    with (
        patch.object(deadlines_module, "DeadlineAccess", return_value=access),
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


async def test_add_invalid_date_replies_ephemeral(mock_interaction):
    cog = _make_cog()

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


async def test_add_duplicate_title_replies_ephemeral(mock_interaction):
    cog = _make_cog()
    mock_interaction.user.id = 1

    access = _make_access_mock(create=None)  # None means duplicate

    with patch.object(deadlines_module, "DeadlineAccess", return_value=access):
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
    dl = await _seed_deadline(db_session, title="Gamma")

    access = _make_access_mock(list_upcoming=[dl])

    with (
        patch.object(deadlines_module, "DeadlineAccess", return_value=access),
        patch.object(
            deadlines_module, "get_deadline_members", new=AsyncMock(return_value=[])
        ),
    ):
        await cog.deadline_list.callback(cog, mock_interaction, days=None)

    mock_interaction.response.send_message.assert_called_once()
    assert (
        mock_interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    )


async def test_show_everyone_is_not_ephemeral(mock_interaction):
    cog = _make_cog()

    access = _make_access_mock(list_upcoming=[])

    with (
        patch.object(deadlines_module, "DeadlineAccess", return_value=access),
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
            deadlines_module,
            "_get_deadline_by_title",
            new=AsyncMock(return_value=dl),
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
        deadlines_module,
        "_get_deadline_by_title",
        new=AsyncMock(return_value=None),
    ):
        await cog.deadline_show_everyone.callback(
            cog, mock_interaction, days=None, title="Ghost"
        )

    assert (
        mock_interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    )


async def test_list_always_filters_by_invoking_user(mock_interaction):
    cog = _make_cog()
    mock_interaction.user.id = 42

    captured_user_id: dict[str, int] = {}

    class FakeAccess:
        def __init__(self, user_id: int) -> None:
            captured_user_id["value"] = user_id

        async def list_upcoming(self, days=None):
            return []

    with (
        patch.object(deadlines_module, "DeadlineAccess", FakeAccess),
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
    mock_interaction.user.id = 123456789
    assigned_member = MagicMock()
    assigned_member.user_id = 123456789

    access = _make_access_mock(get_by_title=dl)

    with (
        patch.object(deadlines_module, "DeadlineAccess", return_value=access),
        patch.object(
            deadlines_module,
            "get_deadline_members",
            new=AsyncMock(return_value=[assigned_member]),
        ),
    ):
        await cog.deadline_info.callback(cog, mock_interaction, title="Info Test")

    mock_interaction.response.send_message.assert_called_once()
    assert (
        mock_interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    )


async def test_info_includes_pending_reminders(db_session, mock_interaction):
    """deadline_info embed includes an 'Upcoming reminders' field."""
    cog = _make_cog()
    # Due in 31 days: all 5 reminders are still pending
    dl = await _seed_deadline(db_session, title="Reminder Test", days_ahead=31)
    mock_interaction.user.id = 1

    access = _make_access_mock(get_by_title=dl)

    with (
        patch.object(deadlines_module, "DeadlineAccess", return_value=access),
        patch.object(
            deadlines_module, "get_deadline_members", new=AsyncMock(return_value=[])
        ),
    ):
        await cog.deadline_info.callback(cog, mock_interaction, title="Reminder Test")

    embed = mock_interaction.response.send_message.call_args.kwargs["embed"]
    field_names = [f.name for f in embed.fields]
    assert "Upcoming reminders" in field_names
    reminders_field = next(f for f in embed.fields if f.name == "Upcoming reminders")
    # All five offsets should appear in the value
    for days in ("30d", "14d", "7d", "3d", "1d"):
        assert days in reminders_field.value


async def test_info_no_pending_reminders_when_overdue(db_session, mock_interaction):
    """When all reminders have fired, the field says so."""
    cog = _make_cog()
    # Due yesterday — all reminders have passed
    dl = await _seed_deadline(db_session, title="Past Test", days_ahead=-1)
    mock_interaction.user.id = 1

    access = _make_access_mock(get_by_title=dl)

    with (
        patch.object(deadlines_module, "DeadlineAccess", return_value=access),
        patch.object(
            deadlines_module, "get_deadline_members", new=AsyncMock(return_value=[])
        ),
    ):
        await cog.deadline_info.callback(cog, mock_interaction, title="Past Test")

    embed = mock_interaction.response.send_message.call_args.kwargs["embed"]
    reminders_field = next(
        (f for f in embed.fields if f.name == "Upcoming reminders"), None
    )
    assert reminders_field is not None
    assert "all reminders have been sent" in reminders_field.value.lower()


async def test_info_not_assigned_replies_ephemeral(mock_interaction):
    """User can't see info for a deadline they're not assigned to."""
    cog = _make_cog()
    mock_interaction.user.id = 999  # different user

    access = _make_access_mock(get_by_title=None)  # access returns None = not assigned

    with patch.object(deadlines_module, "DeadlineAccess", return_value=access):
        await cog.deadline_info.callback(cog, mock_interaction, title="Other Deadline")

    assert (
        mock_interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    )
    # Should get a "not found" style response, not the embed
    assert "embed" not in mock_interaction.response.send_message.call_args.kwargs


async def test_info_not_found(mock_interaction):
    cog = _make_cog()

    access = _make_access_mock(get_by_title=None)

    with patch.object(deadlines_module, "DeadlineAccess", return_value=access):
        await cog.deadline_info.callback(cog, mock_interaction, title="Ghost")

    assert (
        mock_interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    )


# /deadline edit ───────────────────────────────────────────────────────────────


async def test_edit_updates_title(db_session, mock_interaction):
    cog = _make_cog()
    dl = await _seed_deadline(db_session, title="Old Title")
    updated_dl = Deadline(
        id=dl.id,
        title="New Title",
        due_date=dl.due_date,
        created_by=dl.created_by,
        created_at=dl.created_at,
    )

    access = _make_access_mock(edit=updated_dl)

    with (
        patch.object(deadlines_module, "DeadlineAccess", return_value=access),
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
    access.edit.assert_called_once_with(
        "Old Title", new_title="New Title", due_date=None, description=None
    )


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
    updated_dl = Deadline(
        id=dl.id,
        title="Edit Ephemeral 2",
        due_date=dl.due_date,
        created_by=dl.created_by,
        created_at=dl.created_at,
    )

    access = _make_access_mock(edit=updated_dl)

    with (
        patch.object(deadlines_module, "DeadlineAccess", return_value=access),
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


async def test_edit_not_assigned_replies_ephemeral(mock_interaction):
    cog = _make_cog()

    access = _make_access_mock(edit=None)

    with patch.object(deadlines_module, "DeadlineAccess", return_value=access):
        await cog.deadline_edit.callback(
            cog,
            mock_interaction,
            title="Some Deadline",
            new_title="Whatever",
            due_date=None,
            description=None,
        )

    assert (
        mock_interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    )


# /deadline assign ─────────────────────────────────────────────────────────────


async def test_assign_adds_member(mock_interaction):
    cog = _make_cog()

    access = _make_access_mock(assign=([555], [], []))

    with patch.object(deadlines_module, "DeadlineAccess", return_value=access):
        await cog.deadline_assign.callback(
            cog,
            mock_interaction,
            title="Assign Test",
            add="<@555>",
            remove=None,
        )

    access.assign.assert_called_once_with("Assign Test", add_ids=[555], remove_ids=[])
    mock_interaction.response.send_message.assert_called_once()


async def test_assign_no_add_or_remove_replies_ephemeral(mock_interaction):
    cog = _make_cog()

    await cog.deadline_assign.callback(
        cog, mock_interaction, title="Any", add=None, remove=None
    )

    assert (
        mock_interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    )


async def test_assign_not_assigned_replies_ephemeral(mock_interaction):
    cog = _make_cog()

    access = _make_access_mock(assign=None)

    with patch.object(deadlines_module, "DeadlineAccess", return_value=access):
        await cog.deadline_assign.callback(
            cog, mock_interaction, title="Ghost", add="<@555>", remove=None
        )

    assert (
        mock_interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    )


async def test_assign_conflict_shown_in_reply(mock_interaction):
    """When a user can't be added due to per-user title conflict,
    they appear in the reply."""
    cog = _make_cog()

    # added=[], removed=[], conflicts=[777]
    access = _make_access_mock(assign=([], [], [777]))

    with patch.object(deadlines_module, "DeadlineAccess", return_value=access):
        await cog.deadline_assign.callback(
            cog, mock_interaction, title="CVPR", add="<@777>", remove=None
        )

    mock_interaction.response.send_message.assert_called_once()
    msg_content = mock_interaction.response.send_message.call_args.args[0]
    assert "777" in msg_content
    assert (
        mock_interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    )


# /deadline delete ─────────────────────────────────────────────────────────────


async def test_delete_shows_confirmation(db_session, mock_interaction):
    cog = _make_cog()
    dl = await _seed_deadline(db_session, title="To Delete")

    access = _make_access_mock(get_by_title=dl)

    with patch.object(deadlines_module, "DeadlineAccess", return_value=access):
        await cog.deadline_delete.callback(cog, mock_interaction, title="To Delete")

    mock_interaction.response.send_message.assert_called_once()
    # Should include a view (the confirmation buttons)
    call_kwargs = mock_interaction.response.send_message.call_args.kwargs
    assert "view" in call_kwargs


async def test_delete_not_found_replies_ephemeral(mock_interaction):
    cog = _make_cog()

    access = _make_access_mock(get_by_title=None)

    with patch.object(deadlines_module, "DeadlineAccess", return_value=access):
        await cog.deadline_delete.callback(cog, mock_interaction, title="Ghost")

    assert (
        mock_interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
    )


async def test_do_delete_removes_from_db(db_session, mock_interaction):
    cog = _make_cog()
    dl = await _seed_deadline(db_session, title="Delete Me")

    with (
        patch.object(
            deadlines_module, "get_session", return_value=_session_ctx(db_session)
        ),
        patch.object(
            deadlines_module,
            "get_deadline_members",
            new=AsyncMock(return_value=[]),
        ),
        patch.object(deadlines_module, "notify_users", new=AsyncMock(return_value=[])),
    ):
        await cog._do_delete(mock_interaction, dl)

    from sqlmodel import select as sql_select

    result = await db_session.exec(
        sql_select(Deadline).where(Deadline.title == "Delete Me")
    )
    assert result.first() is None


# /deadline test-dms ───────────────────────────────────────────────────────────


async def test_test_dms_sent(mock_interaction):
    """When send_dm returns 'sent', reply contains a success message."""
    cog = _make_cog()
    mock_interaction.user.id = 123

    with patch.object(deadlines_module, "send_dm", new=AsyncMock(return_value="sent")):
        await cog.deadline_test_dms.callback(cog, mock_interaction)

    mock_interaction.response.send_message.assert_called_once()
    call_kwargs = mock_interaction.response.send_message.call_args
    assert call_kwargs.kwargs.get("ephemeral") is True
    assert "working" in call_kwargs.args[0].lower()


async def test_test_dms_forbidden(mock_interaction):
    """When send_dm returns 'forbidden', reply tells user DMs are disabled."""
    cog = _make_cog()
    mock_interaction.user.id = 123

    with patch.object(
        deadlines_module, "send_dm", new=AsyncMock(return_value="forbidden")
    ):
        await cog.deadline_test_dms.callback(cog, mock_interaction)

    mock_interaction.response.send_message.assert_called_once()
    call_kwargs = mock_interaction.response.send_message.call_args
    assert call_kwargs.kwargs.get("ephemeral") is True
    assert "disabled" in call_kwargs.args[0].lower()


async def test_test_dms_error(mock_interaction):
    """When send_dm returns 'error', reply indicates something went wrong."""
    cog = _make_cog()
    mock_interaction.user.id = 123

    with patch.object(deadlines_module, "send_dm", new=AsyncMock(return_value="error")):
        await cog.deadline_test_dms.callback(cog, mock_interaction)

    mock_interaction.response.send_message.assert_called_once()
    call_kwargs = mock_interaction.response.send_message.call_args
    assert call_kwargs.kwargs.get("ephemeral") is True
    assert "wrong" in call_kwargs.args[0].lower()


# ── Notification DMs ───────────────────────────────────────────────────────────


async def test_add_notifies_other_members(mock_interaction):
    """deadline_add DMs all assigned users except the actor."""
    cog = _make_cog()
    actor_id = 1
    other_id = 2
    mock_interaction.user.id = actor_id

    dl = Deadline(
        id=10,
        title="Notify Test",
        due_date=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=10),
        created_by=actor_id,
        created_at=datetime.now(UTC).replace(tzinfo=None),
    )
    access = _make_access_mock(create=dl)

    notify_mock = AsyncMock(return_value=[])

    with (
        patch.object(deadlines_module, "DeadlineAccess", return_value=access),
        patch.object(
            deadlines_module, "get_deadline_members", new=AsyncMock(return_value=[])
        ),
        patch.object(deadlines_module, "notify_users", notify_mock),
    ):
        await cog.deadline_add.callback(
            cog,
            mock_interaction,
            title="Notify Test",
            due_date="2027-01-01",
            members=f"<@{actor_id}> <@{other_id}>",
            description=None,
        )

    # notify_users should have been called with [other_id] only (actor excluded)
    notify_mock.assert_awaited_once()
    _, called_ids, called_msg = notify_mock.call_args.args
    assert called_ids == [other_id]
    assert "Notify Test" in called_msg
    assert str(actor_id) in called_msg


async def test_add_no_notification_when_only_actor(mock_interaction):
    """deadline_add does not call notify_users when actor is the only member."""
    cog = _make_cog()
    mock_interaction.user.id = 1

    dl = Deadline(
        id=11,
        title="Solo",
        due_date=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=10),
        created_by=1,
        created_at=datetime.now(UTC).replace(tzinfo=None),
    )
    access = _make_access_mock(create=dl)
    notify_mock = AsyncMock(return_value=[])

    with (
        patch.object(deadlines_module, "DeadlineAccess", return_value=access),
        patch.object(
            deadlines_module, "get_deadline_members", new=AsyncMock(return_value=[])
        ),
        patch.object(deadlines_module, "notify_users", notify_mock),
    ):
        await cog.deadline_add.callback(
            cog,
            mock_interaction,
            title="Solo",
            due_date="2027-01-01",
            members=None,
            description=None,
        )

    notify_mock.assert_not_called()


async def test_add_failed_dm_note_in_reply(mock_interaction):
    """When some DMs fail on add, the reply contains a warning note."""
    cog = _make_cog()
    actor_id = 1
    other_id = 2
    mock_interaction.user.id = actor_id

    dl = Deadline(
        id=12,
        title="DM Fail Test",
        due_date=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=10),
        created_by=actor_id,
        created_at=datetime.now(UTC).replace(tzinfo=None),
    )
    access = _make_access_mock(create=dl)
    # notify_users returns the failed IDs
    notify_mock = AsyncMock(return_value=[other_id])

    with (
        patch.object(deadlines_module, "DeadlineAccess", return_value=access),
        patch.object(
            deadlines_module, "get_deadline_members", new=AsyncMock(return_value=[])
        ),
        patch.object(deadlines_module, "notify_users", notify_mock),
    ):
        await cog.deadline_add.callback(
            cog,
            mock_interaction,
            title="DM Fail Test",
            due_date="2027-01-01",
            members=f"<@{actor_id}> <@{other_id}>",
            description=None,
        )

    call_kwargs = mock_interaction.response.send_message.call_args.kwargs
    note = call_kwargs.get("content") or ""
    assert str(other_id) in note
    assert "could not dm" in note.lower()


async def test_add_no_notification_on_bad_date(mock_interaction):
    """deadline_add does not call notify_users when date parsing fails."""
    cog = _make_cog()
    notify_mock = AsyncMock(return_value=[])

    with patch.object(deadlines_module, "notify_users", notify_mock):
        await cog.deadline_add.callback(
            cog,
            mock_interaction,
            title="Bad",
            due_date="not-a-date",
            members="<@2>",
            description=None,
        )

    notify_mock.assert_not_called()


async def test_edit_notifies_other_members(db_session, mock_interaction):
    """deadline_edit DMs all assigned members except the actor."""
    cog = _make_cog()
    actor_id = 1
    other_id = 2
    mock_interaction.user.id = actor_id

    dl = await _seed_deadline(db_session, title="Edit Notify")
    updated_dl = Deadline(
        id=dl.id,
        title="Edit Notify",
        due_date=dl.due_date,
        created_by=dl.created_by,
        created_at=dl.created_at,
    )
    access = _make_access_mock(edit=updated_dl)

    other_member = MagicMock()
    other_member.user_id = other_id

    notify_mock = AsyncMock(return_value=[])

    with (
        patch.object(deadlines_module, "DeadlineAccess", return_value=access),
        patch.object(
            deadlines_module,
            "get_deadline_members",
            new=AsyncMock(return_value=[other_member]),
        ),
        patch.object(deadlines_module, "notify_users", notify_mock),
    ):
        await cog.deadline_edit.callback(
            cog,
            mock_interaction,
            title="Edit Notify",
            new_title=None,
            due_date=None,
            description="new desc",
        )

    notify_mock.assert_awaited_once()
    _, called_ids, called_msg = notify_mock.call_args.args
    assert called_ids == [other_id]
    assert "Edit Notify" in called_msg


async def test_edit_actor_excluded_from_notifications(db_session, mock_interaction):
    """deadline_edit does not DM the actor even if they are a member."""
    cog = _make_cog()
    actor_id = 42
    mock_interaction.user.id = actor_id

    dl = await _seed_deadline(db_session, title="Actor Excluded")
    updated_dl = Deadline(
        id=dl.id,
        title="Actor Excluded",
        due_date=dl.due_date,
        created_by=dl.created_by,
        created_at=dl.created_at,
    )
    access = _make_access_mock(edit=updated_dl)

    # actor is the only member
    actor_member = MagicMock()
    actor_member.user_id = actor_id

    notify_mock = AsyncMock(return_value=[])

    with (
        patch.object(deadlines_module, "DeadlineAccess", return_value=access),
        patch.object(
            deadlines_module,
            "get_deadline_members",
            new=AsyncMock(return_value=[actor_member]),
        ),
        patch.object(deadlines_module, "notify_users", notify_mock),
    ):
        await cog.deadline_edit.callback(
            cog,
            mock_interaction,
            title="Actor Excluded",
            new_title=None,
            due_date=None,
            description="updated",
        )

    # notify_users should NOT have been called (no one else to notify)
    notify_mock.assert_not_called()


async def test_edit_changes_description_in_dm(db_session, mock_interaction):
    """When only description changes, DM says 'description updated'."""
    cog = _make_cog()
    actor_id = 1
    other_id = 3
    mock_interaction.user.id = actor_id

    dl = await _seed_deadline(db_session, title="Desc Change")
    updated_dl = Deadline(
        id=dl.id,
        title="Desc Change",
        due_date=dl.due_date,
        created_by=dl.created_by,
        created_at=dl.created_at,
    )
    access = _make_access_mock(edit=updated_dl)

    other_member = MagicMock()
    other_member.user_id = other_id

    notify_mock = AsyncMock(return_value=[])

    with (
        patch.object(deadlines_module, "DeadlineAccess", return_value=access),
        patch.object(
            deadlines_module,
            "get_deadline_members",
            new=AsyncMock(return_value=[other_member]),
        ),
        patch.object(deadlines_module, "notify_users", notify_mock),
    ):
        await cog.deadline_edit.callback(
            cog,
            mock_interaction,
            title="Desc Change",
            new_title=None,
            due_date=None,
            description="new desc",
        )

    _, _, called_msg = notify_mock.call_args.args
    assert "description updated" in called_msg.lower()


async def test_assign_notifies_added_user(mock_interaction):
    """deadline_assign DMs newly added users."""
    cog = _make_cog()
    actor_id = 1
    added_id = 5
    mock_interaction.user.id = actor_id

    dl = Deadline(
        id=20,
        title="Assign Notify",
        due_date=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=10),
        created_by=actor_id,
        created_at=datetime.now(UTC).replace(tzinfo=None),
    )
    access = _make_access_mock(assign=([added_id], [], []), get_by_title=dl)

    notify_mock = AsyncMock(return_value=[])

    with (
        patch.object(deadlines_module, "DeadlineAccess", return_value=access),
        patch.object(deadlines_module, "notify_users", notify_mock),
    ):
        await cog.deadline_assign.callback(
            cog,
            mock_interaction,
            title="Assign Notify",
            add=f"<@{added_id}>",
            remove=None,
        )

    # Should have been called once for the added user
    notify_mock.assert_awaited_once()
    _, called_ids, called_msg = notify_mock.call_args.args
    assert called_ids == [added_id]
    assert "added you" in called_msg.lower()
    assert "Assign Notify" in called_msg


async def test_assign_notifies_removed_user(mock_interaction):
    """deadline_assign DMs newly removed users."""
    cog = _make_cog()
    actor_id = 1
    removed_id = 6
    mock_interaction.user.id = actor_id

    dl = Deadline(
        id=21,
        title="Remove Notify",
        due_date=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=10),
        created_by=actor_id,
        created_at=datetime.now(UTC).replace(tzinfo=None),
    )
    access = _make_access_mock(assign=([], [removed_id], []), get_by_title=dl)

    notify_mock = AsyncMock(return_value=[])

    with (
        patch.object(deadlines_module, "DeadlineAccess", return_value=access),
        patch.object(deadlines_module, "notify_users", notify_mock),
    ):
        await cog.deadline_assign.callback(
            cog,
            mock_interaction,
            title="Remove Notify",
            add=None,
            remove=f"<@{removed_id}>",
        )

    notify_mock.assert_awaited_once()
    _, called_ids, called_msg = notify_mock.call_args.args
    assert called_ids == [removed_id]
    assert "removed you" in called_msg.lower()
    assert "Remove Notify" in called_msg


async def test_assign_notifies_both_added_and_removed(mock_interaction):
    """deadline_assign sends separate DMs to added and removed users."""
    cog = _make_cog()
    actor_id = 1
    added_id = 7
    removed_id = 8
    mock_interaction.user.id = actor_id

    dl = Deadline(
        id=22,
        title="Both Notify",
        due_date=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=10),
        created_by=actor_id,
        created_at=datetime.now(UTC).replace(tzinfo=None),
    )
    access = _make_access_mock(assign=([added_id], [removed_id], []), get_by_title=dl)

    notify_mock = AsyncMock(return_value=[])

    with (
        patch.object(deadlines_module, "DeadlineAccess", return_value=access),
        patch.object(deadlines_module, "notify_users", notify_mock),
    ):
        await cog.deadline_assign.callback(
            cog,
            mock_interaction,
            title="Both Notify",
            add=f"<@{added_id}>",
            remove=f"<@{removed_id}>",
        )

    assert notify_mock.await_count == 2
    all_ids = []
    for call in notify_mock.call_args_list:
        all_ids.extend(call.args[1])
    assert added_id in all_ids
    assert removed_id in all_ids


async def test_assign_no_notification_on_conflict_only(mock_interaction):
    """No DMs when the only result is a conflict (nothing added or removed)."""
    cog = _make_cog()
    mock_interaction.user.id = 1

    access = _make_access_mock(assign=([], [], [99]))
    notify_mock = AsyncMock(return_value=[])

    with (
        patch.object(deadlines_module, "DeadlineAccess", return_value=access),
        patch.object(deadlines_module, "notify_users", notify_mock),
    ):
        await cog.deadline_assign.callback(
            cog,
            mock_interaction,
            title="Conflict Only",
            add="<@99>",
            remove=None,
        )

    notify_mock.assert_not_called()


async def test_do_delete_notifies_all_members(db_session, mock_interaction):
    """_do_delete DMs all members before deleting the deadline."""
    cog = _make_cog()
    actor_id = 1
    other_id = 2
    mock_interaction.user.id = actor_id

    dl = await _seed_deadline(db_session, title="Delete Notify")

    member1 = MagicMock()
    member1.user_id = actor_id
    member2 = MagicMock()
    member2.user_id = other_id

    notify_mock = AsyncMock(return_value=[])

    with (
        patch.object(
            deadlines_module,
            "get_deadline_members",
            new=AsyncMock(return_value=[member1, member2]),
        ),
        patch.object(
            deadlines_module, "get_session", return_value=_session_ctx(db_session)
        ),
        patch.object(deadlines_module, "notify_users", notify_mock),
    ):
        await cog._do_delete(mock_interaction, dl)

    notify_mock.assert_awaited_once()
    _, called_ids, called_msg = notify_mock.call_args.args
    assert set(called_ids) == {actor_id, other_id}
    assert "deleted" in called_msg.lower()
    assert "Delete Notify" in called_msg


async def test_do_delete_failed_dm_note_in_reply(db_session, mock_interaction):
    """When delete DMs fail, the reply contains a warning note."""
    cog = _make_cog()
    mock_interaction.user.id = 1

    dl = await _seed_deadline(db_session, title="Delete DM Fail")

    member = MagicMock()
    member.user_id = 2
    notify_mock = AsyncMock(return_value=[2])  # user 2 failed

    with (
        patch.object(
            deadlines_module,
            "get_deadline_members",
            new=AsyncMock(return_value=[member]),
        ),
        patch.object(
            deadlines_module, "get_session", return_value=_session_ctx(db_session)
        ),
        patch.object(deadlines_module, "notify_users", notify_mock),
    ):
        await cog._do_delete(mock_interaction, dl)

    reply = mock_interaction.response.send_message.call_args.args[0]
    assert "deleted" in reply.lower()
    assert "could not dm" in reply.lower()
    assert "2" in reply
