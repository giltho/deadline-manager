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


async def test_send_reminder_dms_each_member(mocker):
    """_send_reminder calls send_dm for every assigned member."""
    from cogs.reminders import RemindersCog

    bot = MagicMock()
    cog = RemindersCog(bot)
    cog.scheduler = MagicMock()

    mocker.patch(
        "cogs.reminders.get_deadline_members",
        new=AsyncMock(return_value=[MagicMock(user_id=42), MagicMock(user_id=99)]),
    )
    mock_send_dm = mocker.patch(
        "cogs.reminders.send_dm",
        new=AsyncMock(return_value="sent"),
    )

    await cog._send_reminder(
        deadline_id=1,
        deadline_title="My Deadline",
        deadline_description="Some notes",
        due_date=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=7),
        days_before=7,
    )

    # send_dm called once per member
    assert mock_send_dm.call_count == 2
    # Each call passes the bot and the correct user_id
    call_user_ids = {c.args[1] for c in mock_send_dm.call_args_list}
    assert call_user_ids == {42, 99}
    # Message content is correct
    sent_msg = mock_send_dm.call_args_list[0].args[2]
    assert "My Deadline" in sent_msg
    assert "7 days" in sent_msg
    assert "Some notes" in sent_msg


async def test_send_reminder_no_members_skips(mocker, caplog):
    """_send_reminder is a no-op when no members are assigned."""
    import logging

    from cogs.reminders import RemindersCog

    bot = MagicMock()
    bot.fetch_user = AsyncMock()

    cog = RemindersCog(bot)
    cog.scheduler = MagicMock()

    mocker.patch(
        "cogs.reminders.get_deadline_members",
        new=AsyncMock(return_value=[]),
    )

    with caplog.at_level(logging.INFO, logger="cogs.reminders"):
        await cog._send_reminder(
            deadline_id=1,
            deadline_title="Test",
            deadline_description=None,
            due_date=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=3),
            days_before=3,
        )

    bot.fetch_user.assert_not_called()


async def test_send_reminder_forbidden_logs_warning(mocker, caplog):
    """If send_dm returns 'forbidden', a non-delivery info log is emitted and
    processing continues for the next member."""
    import logging

    from cogs.reminders import RemindersCog

    bot = MagicMock()
    cog = RemindersCog(bot)
    cog.scheduler = MagicMock()

    mocker.patch(
        "cogs.reminders.get_deadline_members",
        new=AsyncMock(return_value=[MagicMock(user_id=10), MagicMock(user_id=20)]),
    )
    # First member forbidden, second succeeds
    mock_send_dm = mocker.patch(
        "cogs.reminders.send_dm",
        new=AsyncMock(side_effect=["forbidden", "sent"]),
    )

    with caplog.at_level(logging.INFO, logger="cogs.reminders"):
        await cog._send_reminder(
            deadline_id=1,
            deadline_title="Test",
            deadline_description=None,
            due_date=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=3),
            days_before=3,
        )

    # send_dm was called for both members
    assert mock_send_dm.call_count == 2
    # The cog logs non-delivery at INFO level
    assert any("not delivered" in r.message for r in caplog.records)
