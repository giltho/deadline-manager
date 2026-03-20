"""Tests for cogs/reminders.py — scheduler job management."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

from tests.conftest import make_deadline


def _make_reminders_cog():
    """Build a RemindersCog with a mocked bot and scheduler."""
    from cogs.reminders import RemindersCog

    bot = MagicMock()
    bot.cogs = {}
    cog = RemindersCog(bot)
    # Replace the real scheduler with a mock
    cog.scheduler = MagicMock()
    cog.scheduler.get_job = MagicMock(return_value=None)
    return cog


def test_schedule_reminders_creates_three_jobs():
    cog = _make_reminders_cog()
    deadline = make_deadline(
        id=1,
        due_date=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=30),
    )
    cog.schedule_reminders(deadline)
    assert cog.scheduler.add_job.call_count == 3


def test_schedule_reminders_skips_past_jobs():
    cog = _make_reminders_cog()
    # Due in 5 days — 14d and 7d reminders are already past, only 3d remains
    deadline = make_deadline(
        id=2,
        due_date=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=5),
    )
    cog.schedule_reminders(deadline)
    assert cog.scheduler.add_job.call_count == 1


def test_schedule_reminders_skips_all_when_overdue():
    cog = _make_reminders_cog()
    deadline = make_deadline(
        id=3,
        due_date=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1),
    )
    cog.schedule_reminders(deadline)
    assert cog.scheduler.add_job.call_count == 0


def test_schedule_reminders_uses_replace_existing():
    cog = _make_reminders_cog()
    deadline = make_deadline(
        id=4,
        due_date=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=30),
    )
    cog.schedule_reminders(deadline)
    calls = cog.scheduler.add_job.call_args_list
    for call in calls:
        assert call.kwargs.get("replace_existing") is True


def test_schedule_reminders_job_ids():
    cog = _make_reminders_cog()
    deadline = make_deadline(
        id=5,
        due_date=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=30),
    )
    cog.schedule_reminders(deadline)
    job_ids = {call.kwargs["id"] for call in cog.scheduler.add_job.call_args_list}
    assert job_ids == {"reminder_5_14d", "reminder_5_7d", "reminder_5_3d"}


def test_cancel_reminders_removes_existing_jobs():
    cog = _make_reminders_cog()
    # Pretend all three jobs exist
    cog.scheduler.get_job = MagicMock(return_value=MagicMock())
    cog.cancel_reminders(deadline_id=10)
    assert cog.scheduler.remove_job.call_count == 3


def test_cancel_reminders_skips_nonexistent_jobs():
    cog = _make_reminders_cog()
    # No jobs exist
    cog.scheduler.get_job = MagicMock(return_value=None)
    cog.cancel_reminders(deadline_id=10)
    cog.scheduler.remove_job.assert_not_called()


def test_reschedule_replaces_existing_jobs():
    """schedule_reminders called twice should replace jobs, not duplicate."""
    cog = _make_reminders_cog()
    deadline = make_deadline(
        id=6,
        due_date=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=30),
    )
    cog.schedule_reminders(deadline)
    cog.schedule_reminders(deadline)
    # add_job called 6 times total but replace_existing=True means no duplication
    # at the scheduler level — we just verify replace_existing is always True
    for call in cog.scheduler.add_job.call_args_list:
        assert call.kwargs.get("replace_existing") is True


async def test_send_reminder_posts_to_channel(mocker):
    from cogs.reminders import RemindersCog

    bot = MagicMock()
    mock_channel = AsyncMock(spec=["send"])
    mock_channel.send = AsyncMock()
    bot.get_channel = MagicMock(return_value=mock_channel)

    cog = RemindersCog(bot)
    cog.scheduler = MagicMock()

    mock_settings = MagicMock()
    mock_settings.reminder_channel_id = 999

    mocker.patch("cogs.reminders.get_settings", return_value=mock_settings)
    mocker.patch(
        "cogs.reminders.get_deadline_members",
        new=AsyncMock(return_value=[MagicMock(user_id=42)]),
    )

    import discord

    bot.get_channel.return_value = MagicMock(spec=discord.TextChannel)
    bot.get_channel.return_value.send = AsyncMock()

    await cog._send_reminder(
        deadline_id=1,
        deadline_title="My Deadline",
        deadline_description="Some notes",
        due_date=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=7),
        days_before=7,
    )

    bot.get_channel.return_value.send.assert_called_once()
    call_args = bot.get_channel.return_value.send.call_args[0][0]
    assert "My Deadline" in call_args
    assert "7 days" in call_args
    assert "Some notes" in call_args


async def test_send_reminder_no_channel_logs_error(mocker, caplog):
    import logging

    from cogs.reminders import RemindersCog

    bot = MagicMock()
    bot.get_channel = MagicMock(return_value=None)

    cog = RemindersCog(bot)
    cog.scheduler = MagicMock()

    mock_settings = MagicMock()
    mock_settings.reminder_channel_id = 999

    mocker.patch("cogs.reminders.get_settings", return_value=mock_settings)
    mocker.patch("cogs.reminders.get_deadline_members", new=AsyncMock(return_value=[]))

    with caplog.at_level(logging.ERROR, logger="cogs.reminders"):
        await cog._send_reminder(
            deadline_id=1,
            deadline_title="Test",
            deadline_description=None,
            due_date=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=3),
            days_before=3,
        )

    assert any("not found" in r.message for r in caplog.records)
