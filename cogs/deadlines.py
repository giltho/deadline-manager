"""
Deadlines cog — all slash commands for deadline management.

Commands:
  /deadline add
  /deadline list
  /deadline show-everyone
  /deadline info
  /deadline edit
  /deadline assign
  /deadline delete
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime

import discord
from dateutil import parser as dateutil_parser
from discord import app_commands
from discord.ext import commands

from calendar_sync import SYNC_FAILED, make_calendar_client
from checks import has_allowed_role
from config import get_settings
from db import DeadlineAccess, _get_deadline_by_title, get_deadline_members, get_session
from discord_utils import send_dm
from models import Deadline, DeadlineMember

logger = logging.getLogger(__name__)

# ── Colour constants ──────────────────────────────────────────────────────────
COLOUR_RED = discord.Colour.red()
COLOUR_AMBER = discord.Colour.orange()
COLOUR_GREEN = discord.Colour.green()
COLOUR_BLUE = discord.Colour.blue()


def _days_remaining(due_date: datetime) -> int:
    now = datetime.now(UTC).replace(tzinfo=None)
    delta = due_date - now
    return max(0, delta.days)


def _deadline_colour(days: int) -> discord.Colour:
    if days <= 3:
        return COLOUR_RED
    if days <= 7:
        return COLOUR_AMBER
    return COLOUR_GREEN


def _parse_due_date(raw: str) -> datetime | None:
    """Parse a flexible date string into a naive UTC datetime, or return None.

    yearfirst=True ensures ISO dates like 2026-07-09 are read as YYYY-MM-DD
    rather than being misinterpreted when dayfirst would swap month and day.
    """
    try:
        dt = dateutil_parser.parse(raw, yearfirst=True)
        # If no timezone info, treat as UTC
        if dt.tzinfo is not None:
            dt = dt.astimezone(UTC).replace(tzinfo=None)
        return dt
    except (ValueError, OverflowError):
        return None


def _extract_user_ids(mentions_str: str) -> list[int]:
    """Extract Discord user IDs from a string of @mentions like '<@123> <@456>'."""
    return [int(uid) for uid in re.findall(r"<@!?(\d+)>", mentions_str)]


def _sync_status_label(outlook_event_id: str | None, sync_enabled: bool) -> str:
    if not sync_enabled:
        return "Disabled"
    if outlook_event_id is None:
        return "Not synced"
    if outlook_event_id == SYNC_FAILED:
        return "Sync failed"
    return f"Synced (`{outlook_event_id[:12]}…`)"


def _build_deadline_embed(
    deadline: Deadline,
    members: list[DeadlineMember],
    *,
    sync_enabled: bool,
    title_prefix: str = "",
) -> discord.Embed:
    days = _days_remaining(deadline.due_date)
    colour = _deadline_colour(days)
    unix_ts = int(deadline.due_date.replace(tzinfo=UTC).timestamp())
    member_mentions = (
        ", ".join(f"<@{m.user_id}>" for m in members) if members else "None"
    )

    embed = discord.Embed(
        title=f"{title_prefix}{deadline.title}",
        description=deadline.description or "",
        colour=colour,
    )
    embed.add_field(name="Due", value=f"<t:{unix_ts}:F>", inline=True)
    embed.add_field(name="Days remaining", value=str(days), inline=True)
    embed.add_field(name="Assigned to", value=member_mentions, inline=False)
    embed.add_field(name="Created by", value=f"<@{deadline.created_by}>", inline=True)
    embed.add_field(
        name="Created at",
        value=f"<t:{int(deadline.created_at.replace(tzinfo=UTC).timestamp())}:D>",
        inline=True,
    )
    embed.add_field(
        name="Outlook sync",
        value=_sync_status_label(deadline.outlook_event_id, sync_enabled),
        inline=True,
    )
    return embed


# ── Delete confirmation view ──────────────────────────────────────────────────


class DeleteConfirmView(discord.ui.View):
    """A two-button (Confirm / Cancel) prompt for deadline deletion."""

    def __init__(self, deadline: Deadline, cog: DeadlinesCog) -> None:
        super().__init__(timeout=60)
        self._deadline = deadline
        self._cog = cog
        self.confirmed: bool | None = None
        self.message: discord.InteractionMessage | None = None

    async def on_timeout(self) -> None:
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        if self.message:
            await self.message.edit(
                content="Deletion timed out — no action taken.", view=self
            )

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger)
    async def confirm(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self.confirmed = True
        self.stop()
        await self._cog._do_delete(interaction, self._deadline)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self.confirmed = False
        self.stop()
        await interaction.response.send_message("Deletion cancelled.", ephemeral=True)


# ── Pagination view for /deadline list ───────────────────────────────────────


class DeadlineListView(discord.ui.View):
    """Previous / Next pagination for /deadline list."""

    PAGE_SIZE = 10

    def __init__(
        self,
        deadlines: list[Deadline],
        member_map: dict[int, list[DeadlineMember]],
        sync_enabled: bool,
    ) -> None:
        super().__init__(timeout=120)
        self._deadlines = deadlines
        self._member_map = member_map
        self._sync_enabled = sync_enabled
        self._page = 0
        self._total_pages = max(
            1, (len(deadlines) + self.PAGE_SIZE - 1) // self.PAGE_SIZE
        )
        self._update_buttons()

    def _update_buttons(self) -> None:
        self.prev_button.disabled = self._page == 0
        self.next_button.disabled = self._page >= self._total_pages - 1

    def build_embed(self) -> discord.Embed:
        start = self._page * self.PAGE_SIZE
        page_items = self._deadlines[start : start + self.PAGE_SIZE]

        embed = discord.Embed(
            title="Upcoming Deadlines",
            colour=COLOUR_BLUE,
        )
        embed.set_footer(text=f"Page {self._page + 1}/{self._total_pages}")

        for deadline in page_items:
            days = _days_remaining(deadline.due_date)
            unix_ts = int(deadline.due_date.replace(tzinfo=UTC).timestamp())
            members = self._member_map.get(deadline.id or 0, [])
            member_str = (
                ", ".join(f"<@{m.user_id}>" for m in members) if members else "None"
            )
            colour_indicator = "🔴" if days <= 3 else "🟡" if days <= 7 else "🟢"
            embed.add_field(
                name=f"{colour_indicator} {deadline.title}",
                value=f"Due: <t:{unix_ts}:F> ({days}d) | {member_str}",
                inline=False,
            )

        if not page_items:
            embed.description = "No upcoming deadlines."

        return embed

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary)
    async def prev_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self._page = max(0, self._page - 1)
        self._update_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def next_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self._page = min(self._total_pages - 1, self._page + 1)
        self._update_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)


# ── Cog ───────────────────────────────────────────────────────────────────────


class DeadlinesCog(commands.Cog, name="Deadlines"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._settings = get_settings()
        # calendar_sync TODO: this will return a real client once MS vars are set
        self._calendar = make_calendar_client(self._settings)

    # ── Shared autocomplete ───────────────────────────────────────────────────

    async def _title_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        access = DeadlineAccess(interaction.user.id)
        titles = await access.autocomplete(current)
        return [app_commands.Choice(name=t, value=t) for t in titles]

    # ── /deadline group ───────────────────────────────────────────────────────

    deadline_group = app_commands.Group(name="deadline", description="Manage deadlines")

    # ── /deadline help ────────────────────────────────────────────────────────

    @deadline_group.command(name="help", description="How to use the deadline bot")
    async def deadline_help(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title="Deadline Manager — Quick Guide",
            colour=COLOUR_BLUE,
        )
        embed.add_field(
            name="Privacy",
            value=(
                "All deadline interactions are **private by default** — "
                "only you can see the bot's replies. "
                "Deadlines you are assigned to are visible only to you; "
                "others cannot see or search them."
            ),
            inline=False,
        )
        embed.add_field(
            name="Creating a deadline",
            value=(
                "`/deadline add title: … due_date: … [members: @mentions] [description: …]`\n"  # noqa: E501
                "Creates a new deadline. If you omit `members` it is assigned to you alone. "  # noqa: E501
                "Date formats like `2026-06-15` or `15 Jun 2026 17:00` are both accepted."  # noqa: E501
            ),
            inline=False,
        )
        embed.add_field(
            name="Viewing your deadlines",
            value=(
                "`/deadline list [days: N]` — lists all upcoming deadlines you are assigned to, "  # noqa: E501
                "sorted by due date. Add `days:` to limit to the next N days.\n"
                "`/deadline info title: …` — shows full details for a single deadline."
            ),
            inline=False,
        )
        embed.add_field(
            name="Sharing with the channel",
            value=(
                "`/deadline show-everyone [days: N] [title: …]` — posts your deadlines publicly. "  # noqa: E501
                "Pass a `title:` to share just one deadline, or omit it to share the full list."  # noqa: E501
            ),
            inline=False,
        )
        embed.add_field(
            name="Editing & managing",
            value=(
                "`/deadline edit title: … [new_title:] [due_date:] [description:]` — update fields.\n"  # noqa: E501
                "`/deadline assign title: … [add: @mentions] [remove: @mentions]` — change who is assigned.\n"  # noqa: E501
                "`/deadline delete title: …` — permanently delete (requires confirmation).\n"  # noqa: E501
                "Anyone assigned to a deadline can edit or delete it."
            ),
            inline=False,
        )
        embed.set_footer(
            text="All title fields support autocomplete — start typing to search."
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /deadline test-dms ────────────────────────────────────────────────────

    @deadline_group.command(
        name="test-dms",
        description="Check whether the bot can DM you (required for reminders)",
    )
    async def deadline_test_dms(self, interaction: discord.Interaction) -> None:
        result = await send_dm(
            self.bot,
            interaction.user.id,
            "This is a test DM from the deadline bot. Your reminders are working!",
        )
        if result == "sent":
            msg = "\u2705 DMs are working \u2014 you will receive deadline reminders."
        elif result == "forbidden":
            msg = (
                "\u274c Your DMs are disabled. You will **not** receive deadline "
                "reminders. Enable DMs from server members in your Discord privacy "
                "settings."
            )
        else:
            msg = "\u26a0\ufe0f Something went wrong trying to DM you."
        await interaction.response.send_message(msg, ephemeral=True)

    # ── /deadline add ─────────────────────────────────────────────────────────

    @deadline_group.command(name="add", description="Create a new deadline")
    @has_allowed_role()
    @app_commands.describe(
        title="Short name for the deadline",
        due_date="Due date, e.g. '2026-06-15' or '15 Jun 2026 17:00'",
        members="@mentions to assign (defaults to you)",
        description="Optional free-text notes",
    )
    async def deadline_add(
        self,
        interaction: discord.Interaction,
        title: str,
        due_date: str,
        members: str | None = None,
        description: str | None = None,
    ) -> None:
        parsed_date = _parse_due_date(due_date)
        if parsed_date is None:
            await interaction.response.send_message(
                f"Could not parse date: `{due_date}`. "
                "Try formats like `2026-06-15` or `15 Jun 2026 17:00`.",
                ephemeral=True,
            )
            return

        # Resolve assigned user IDs
        if members:
            user_ids = _extract_user_ids(members)
            if not user_ids:
                await interaction.response.send_message(
                    "No valid @mentions found in `members`.", ephemeral=True
                )
                return
        else:
            user_ids = [interaction.user.id]

        access = DeadlineAccess(interaction.user.id)
        deadline = await access.create(title, parsed_date, description, user_ids)
        if deadline is None:
            await interaction.response.send_message(
                f"One or more members already have a deadline named **{title}**.",
                ephemeral=True,
            )
            return

        # Schedule reminders
        reminders_cog = self.bot.cogs.get("Reminders")
        if reminders_cog is not None:
            from cogs.reminders import RemindersCog

            if isinstance(reminders_cog, RemindersCog):
                reminders_cog.schedule_reminders(deadline)

        # calendar_sync TODO: call self._calendar.create_event() here once implemented

        member_rows = await get_deadline_members(deadline.id)  # type: ignore[arg-type]
        embed = _build_deadline_embed(
            deadline,
            member_rows,
            sync_enabled=self._settings.calendar_sync_enabled,
            title_prefix="Created: ",
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /deadline list ────────────────────────────────────────────────────────

    async def _send_deadline_list(
        self,
        interaction: discord.Interaction,
        days: int | None,
        ephemeral: bool,
    ) -> None:
        """Fetch and send the invoking user's deadline list."""
        access = DeadlineAccess(interaction.user.id)
        deadlines = await access.list_upcoming(days=days)

        # Fetch members for all deadlines in a single pass
        member_map: dict[int, list[DeadlineMember]] = {}
        for dl in deadlines:
            member_map[dl.id or 0] = await get_deadline_members(dl.id)  # type: ignore[arg-type]

        view = DeadlineListView(
            deadlines, member_map, self._settings.calendar_sync_enabled
        )
        embed = view.build_embed()

        if len(deadlines) <= DeadlineListView.PAGE_SIZE:
            await interaction.response.send_message(embed=embed, ephemeral=ephemeral)
        else:
            await interaction.response.send_message(
                embed=embed, view=view, ephemeral=ephemeral
            )
            view.message = await interaction.original_response()  # type: ignore[attr-defined]

    @deadline_group.command(
        name="list", description="List your upcoming deadlines (only visible to you)"
    )
    @has_allowed_role()
    @app_commands.describe(
        days="Only show deadlines due within this many days",
    )
    async def deadline_list(
        self,
        interaction: discord.Interaction,
        days: int | None = None,
    ) -> None:
        await self._send_deadline_list(interaction, days=days, ephemeral=True)

    @deadline_group.command(
        name="show-everyone",
        description="Share your upcoming deadlines with the channel",
    )
    @has_allowed_role()
    @app_commands.describe(
        days="Only show deadlines due within this many days",
        title="Share a single deadline by name (optional)",
    )
    @app_commands.autocomplete(title=_title_autocomplete)
    async def deadline_show_everyone(
        self,
        interaction: discord.Interaction,
        days: int | None = None,
        title: str | None = None,
    ) -> None:
        if title is not None:
            # Show a single deadline publicly; bypass membership filter for public share
            deadline = await _get_deadline_by_title(title)
            if deadline is None:
                await interaction.response.send_message(
                    f"No deadline found with title **{title}**.", ephemeral=True
                )
                return
            members = await get_deadline_members(deadline.id)  # type: ignore[arg-type]
            embed = _build_deadline_embed(
                deadline,
                members,
                sync_enabled=self._settings.calendar_sync_enabled,
            )
            await interaction.response.send_message(embed=embed, ephemeral=False)
        else:
            await self._send_deadline_list(interaction, days=days, ephemeral=False)

    # ── /deadline info ────────────────────────────────────────────────────────

    @deadline_group.command(name="info", description="Show full details for a deadline")
    @has_allowed_role()
    @app_commands.describe(title="Deadline title")
    @app_commands.autocomplete(title=_title_autocomplete)
    async def deadline_info(
        self,
        interaction: discord.Interaction,
        title: str,
    ) -> None:
        access = DeadlineAccess(interaction.user.id)
        deadline = await access.get_by_title(title)
        if deadline is None:
            await interaction.response.send_message(
                f"No deadline found with title **{title}**.", ephemeral=True
            )
            return

        members = await get_deadline_members(deadline.id)  # type: ignore[arg-type]
        embed = _build_deadline_embed(
            deadline,
            members,
            sync_enabled=self._settings.calendar_sync_enabled,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /deadline edit ────────────────────────────────────────────────────────

    @deadline_group.command(name="edit", description="Edit an existing deadline")
    @has_allowed_role()
    @app_commands.describe(
        title="Deadline to edit",
        new_title="New title",
        due_date="New due date",
        description="New description",
    )
    @app_commands.autocomplete(title=_title_autocomplete)
    async def deadline_edit(
        self,
        interaction: discord.Interaction,
        title: str,
        new_title: str | None = None,
        due_date: str | None = None,
        description: str | None = None,
    ) -> None:
        if new_title is None and due_date is None and description is None:
            await interaction.response.send_message(
                "Provide at least one field to update.", ephemeral=True
            )
            return

        parsed_date: datetime | None = None
        if due_date is not None:
            parsed_date = _parse_due_date(due_date)
            if parsed_date is None:
                await interaction.response.send_message(
                    f"Could not parse date: `{due_date}`.", ephemeral=True
                )
                return

        access = DeadlineAccess(interaction.user.id)
        deadline = await access.edit(
            title, new_title=new_title, due_date=parsed_date, description=description
        )
        if deadline is None:
            await interaction.response.send_message(
                f"No deadline found with title **{title}**.", ephemeral=True
            )
            return

        # Reschedule reminders with updated due_date
        reminders_cog = self.bot.cogs.get("Reminders")
        if reminders_cog is not None:
            from cogs.reminders import RemindersCog

            if isinstance(reminders_cog, RemindersCog):
                reminders_cog.schedule_reminders(deadline)

        # calendar_sync TODO: update Outlook event if one exists

        members = await get_deadline_members(deadline.id)  # type: ignore[arg-type]
        embed = _build_deadline_embed(
            deadline,
            members,
            sync_enabled=self._settings.calendar_sync_enabled,
            title_prefix="Updated: ",
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /deadline assign ──────────────────────────────────────────────────────

    @deadline_group.command(
        name="assign", description="Add or remove members from a deadline"
    )
    @has_allowed_role()
    @app_commands.describe(
        title="Deadline title",
        add="@mentions to add",
        remove="@mentions to remove",
    )
    @app_commands.autocomplete(title=_title_autocomplete)
    async def deadline_assign(
        self,
        interaction: discord.Interaction,
        title: str,
        add: str | None = None,
        remove: str | None = None,
    ) -> None:
        if add is None and remove is None:
            await interaction.response.send_message(
                "Provide at least one of `add` or `remove`.", ephemeral=True
            )
            return

        access = DeadlineAccess(interaction.user.id)
        result = await access.assign(
            title,
            add_ids=_extract_user_ids(add) if add else [],
            remove_ids=_extract_user_ids(remove) if remove else [],
        )
        if result is None:
            await interaction.response.send_message(
                f"No deadline found with title **{title}**.", ephemeral=True
            )
            return

        added, removed, conflicts = result
        parts: list[str] = []
        if added:
            parts.append("Added: " + ", ".join(f"<@{u}>" for u in added))
        if removed:
            parts.append("Removed: " + ", ".join(f"<@{u}>" for u in removed))
        if conflicts:
            parts.append(
                "Skipped (already have a deadline named **"
                + title
                + "**): "
                + ", ".join(f"<@{u}>" for u in conflicts)
            )

        await interaction.response.send_message(
            f"**{title}** — " + " | ".join(parts) if parts else "No changes made.",
            ephemeral=True,
        )

    # ── /deadline delete ──────────────────────────────────────────────────────

    @deadline_group.command(name="delete", description="Delete a deadline")
    @has_allowed_role()
    @app_commands.describe(title="Deadline to delete")
    @app_commands.autocomplete(title=_title_autocomplete)
    async def deadline_delete(
        self,
        interaction: discord.Interaction,
        title: str,
    ) -> None:
        access = DeadlineAccess(interaction.user.id)
        deadline = await access.get_by_title(title)
        if deadline is None:
            await interaction.response.send_message(
                f"No deadline found with title **{title}**.", ephemeral=True
            )
            return

        view = DeleteConfirmView(deadline, self)
        await interaction.response.send_message(
            f"Are you sure you want to delete **{title}**? This cannot be undone.",
            view=view,
            ephemeral=True,
        )
        view.message = await interaction.original_response()

    async def _do_delete(
        self, interaction: discord.Interaction, deadline: Deadline
    ) -> None:
        """Perform the actual deletion after confirmation."""
        title = deadline.title
        deadline_id = deadline.id

        # Cancel reminder jobs first
        reminders_cog = self.bot.cogs.get("Reminders")
        if reminders_cog is not None:
            from cogs.reminders import RemindersCog

            if isinstance(reminders_cog, RemindersCog):
                reminders_cog.cancel_reminders(deadline_id)  # type: ignore[arg-type]

        # calendar_sync TODO: delete Outlook event if one exists

        async with get_session() as session:
            db_deadline = await session.get(Deadline, deadline_id)
            if db_deadline:
                await session.delete(db_deadline)
                await session.commit()

        await interaction.response.send_message(
            f"Deadline **{title}** has been deleted.", ephemeral=True
        )

    # ── calendar_sync TODO helpers (implement alongside MS Graph) ────────────
    # async def _sync_create(self, deadline: Deadline) -> None: ...
    # async def _sync_update(
    #     self, deadline: Deadline, changed_fields: dict
    # ) -> None: ...
    # async def _sync_delete(self, event_id: str) -> None: ...


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(DeadlinesCog(bot))
