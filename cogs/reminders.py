"""
Reminders cog — schedules and dispatches deadline reminder messages.

Jobs are keyed as `reminder_{deadline_id}_{offset}` (e.g. `reminder_42_14d`)
so they can be cleanly replaced when a deadline is edited or rescheduled.

Reminders are sent as private DMs to each assigned user, so only the people
who are assigned to a deadline receive its reminders.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from discord.ext import commands

from db import get_all_future_deadlines, get_deadline_members
from discord_utils import send_dm
from models import Deadline

logger = logging.getLogger(__name__)

# (label, days_before) pairs — order doesn't matter for scheduling
REMINDER_OFFSETS: list[tuple[str, int]] = [
    ("14d", 14),
    ("7d", 7),
    ("3d", 3),
]


def _job_id(deadline_id: int, offset_label: str) -> str:
    return f"reminder_{deadline_id}_{offset_label}"


class RemindersCog(commands.Cog, name="Reminders"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.scheduler = AsyncIOScheduler(timezone="UTC")

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def cog_load(self) -> None:
        self.scheduler.start()
        await self._reschedule_all()
        logger.info("RemindersCog loaded; scheduler started.")

    async def cog_unload(self) -> None:
        self.scheduler.shutdown(wait=False)
        logger.info("RemindersCog unloaded; scheduler stopped.")

    # ── Public API (called from deadlines cog) ────────────────────────────────

    def schedule_reminders(self, deadline: Deadline) -> None:
        """
        Create (or replace) the three reminder jobs for *deadline*.
        Jobs whose fire time has already passed are silently skipped.
        """
        now = datetime.now(UTC)

        for label, days_before in REMINDER_OFFSETS:
            fire_at = deadline.due_date.replace(tzinfo=UTC) - timedelta(
                days=days_before
            )
            if fire_at <= now:
                logger.debug(
                    "Skipping past reminder job %s for deadline %d",
                    label,
                    deadline.id,
                )
                continue

            job_id = _job_id(deadline.id, label)  # type: ignore[arg-type]
            self.scheduler.add_job(
                self._send_reminder,
                trigger=DateTrigger(run_date=fire_at),
                id=job_id,
                replace_existing=True,
                kwargs={
                    "deadline_id": deadline.id,
                    "deadline_title": deadline.title,
                    "deadline_description": deadline.description,
                    "due_date": deadline.due_date,
                    "days_before": days_before,
                },
            )
            logger.info("Scheduled reminder job %s at %s", job_id, fire_at)

    def cancel_reminders(self, deadline_id: int) -> None:
        """Remove all reminder jobs for *deadline_id*."""
        for label, _ in REMINDER_OFFSETS:
            job_id = _job_id(deadline_id, label)
            if self.scheduler.get_job(job_id):
                self.scheduler.remove_job(job_id)
                logger.info("Cancelled reminder job %s", job_id)

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _reschedule_all(self) -> None:
        """On startup, schedule reminders for every future deadline in the DB."""
        deadlines = await get_all_future_deadlines()
        for deadline in deadlines:
            self.schedule_reminders(deadline)
        logger.info("Rescheduled reminders for %d future deadline(s).", len(deadlines))

    async def _send_reminder(
        self,
        deadline_id: int,
        deadline_title: str,
        deadline_description: str | None,
        due_date: datetime,
        days_before: int,
    ) -> None:
        """DM each assigned user a private reminder for their deadline."""
        members = await get_deadline_members(deadline_id)
        if not members:
            logger.info(
                "No members assigned to deadline '%s'; skipping reminder.",
                deadline_title,
            )
            return

        # Discord timestamp: <t:UNIX:F> renders in each user's local timezone
        unix_ts = int(due_date.replace(tzinfo=UTC).timestamp())
        timestamp_str = f"<t:{unix_ts}:F>"

        lines = [
            f"\u23f0  Reminder: **{deadline_title}** is due in "
            f"{days_before} days ({timestamp_str})",
        ]
        if deadline_description:
            lines.append(deadline_description)
        message = "\n".join(lines)

        for member in members:
            result = await send_dm(self.bot, member.user_id, message)
            if result == "sent":
                logger.info(
                    "Sent %d-day reminder for '%s' to user %d.",
                    days_before,
                    deadline_title,
                    member.user_id,
                )
            else:
                logger.info(
                    "Reminder for '%s' not delivered to user %d: %s",
                    deadline_title,
                    member.user_id,
                    result,
                )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RemindersCog(bot))
