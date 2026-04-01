"""
/deadlines endpoints.

GET    /deadlines          — list the authenticated user's upcoming deadlines
POST   /deadlines          — create a new deadline (creator always assigned)
PATCH  /deadlines/{id}     — edit title/due_date/description/members by deadline ID
DELETE /deadlines/{id}     — delete a deadline by ID

All write operations send DM notifications to affected users via the Discord
bot, mirroring the behaviour of the Discord slash commands exactly.
"""

from __future__ import annotations

from datetime import UTC
from typing import Annotated

import discord
from fastapi import APIRouter, Depends, HTTPException, Query, status

from api.deps import get_bot, get_current_user
from api.schemas import (
    DeadlineCreateRequest,
    DeadlineEditRequest,
    DeadlineResponse,
    DiscordUser,
)
from cogs.deadlines import _parse_due_date
from db import DeadlineAccess, get_deadline_members
from discord_utils import notify_users

router = APIRouter(prefix="/deadlines", tags=["deadlines"])


def _user_access(current_user: DiscordUser) -> DeadlineAccess:
    return DeadlineAccess(int(current_user.id))


def _to_response(dl, members) -> DeadlineResponse:  # type: ignore[no-untyped-def]
    return DeadlineResponse(
        id=dl.id,  # type: ignore[arg-type]
        title=dl.title,
        description=dl.description,
        due_date=dl.due_date,
        created_by=str(dl.created_by),
        created_at=dl.created_at,
        member_ids=[str(m.user_id) for m in members],
    )


@router.get("", response_model=list[DeadlineResponse])
async def list_deadlines(
    days: Annotated[
        int | None,
        Query(description="Only show deadlines due within the next N days.", ge=1),
    ] = None,
    current_user: DiscordUser = Depends(get_current_user),
) -> list[DeadlineResponse]:
    """Return upcoming deadlines assigned to the authenticated user."""
    access = _user_access(current_user)
    deadlines = await access.list_upcoming(days=days)

    results: list[DeadlineResponse] = []
    for dl in deadlines:
        members = await get_deadline_members(dl.id)  # type: ignore[arg-type]
        results.append(_to_response(dl, members))
    return results


@router.post("", response_model=DeadlineResponse, status_code=status.HTTP_201_CREATED)
async def create_deadline(
    body: DeadlineCreateRequest,
    current_user: DiscordUser = Depends(get_current_user),
    bot: discord.Client = Depends(get_bot),
) -> DeadlineResponse:
    """Create a new deadline. The creator is always included in the assigned members."""
    due_date = _parse_due_date(body.due_date)
    if due_date is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Could not parse due_date. Accepted formats: "
                "'2026-06-15', '15 Jun 2026 17:00', '2026-06-15 AoE'."
            ),
        )

    creator_id = int(current_user.id)
    member_ids = list({creator_id, *[int(x) for x in body.member_ids]})

    access = DeadlineAccess(creator_id)
    deadline = await access.create(
        title=body.title,
        due_date=due_date,
        description=body.description,
        user_ids=member_ids,
    )

    if deadline is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "A deadline with this title already exists"
                " for one of the assigned members."
            ),
        )

    members = await get_deadline_members(deadline.id)  # type: ignore[arg-type]

    # Notify all assigned members except the creator — same DM as Discord cog.
    unix_ts = int(deadline.due_date.replace(tzinfo=UTC).timestamp())
    notify_ids = [m.user_id for m in members if m.user_id != creator_id]
    if notify_ids:
        dm_msg = (
            f"<@{creator_id}> has created the deadline "
            f'**"{deadline.title}"** due <t:{unix_ts}:F> that involves you.'
        )
        await notify_users(bot, notify_ids, dm_msg)

    return _to_response(deadline, members)


@router.patch("/{deadline_id}", response_model=DeadlineResponse)
async def edit_deadline(
    deadline_id: int,
    body: DeadlineEditRequest,
    current_user: DiscordUser = Depends(get_current_user),
    bot: discord.Client = Depends(get_bot),
) -> DeadlineResponse:
    """
    Edit a deadline's title, due date, description, and/or member list.

    All fields are optional. When member_ids is provided it replaces the full
    member list; the endpoint computes add/remove diffs internally.
    """
    if (
        body.new_title is None
        and body.due_date is None
        and body.description is None
        and body.member_ids is None
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide at least one field to update.",
        )

    parsed_date = None
    if body.due_date is not None:
        parsed_date = _parse_due_date(body.due_date)
        if parsed_date is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "Could not parse due_date. Accepted formats: "
                    "'2026-06-15', '15 Jun 2026 17:00', '2026-06-15 AoE'."
                ),
            )

    editor_id = int(current_user.id)
    access = DeadlineAccess(editor_id)

    # ── Edit scalar fields ────────────────────────────────────────────────────
    deadline = await access.edit_by_id(
        deadline_id,
        new_title=body.new_title,
        due_date=parsed_date,
        description=body.description,
    )
    if deadline is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Deadline not found or you are not assigned to it.",
        )

    # ── Edit member list ──────────────────────────────────────────────────────
    added_ids: list[int] = []
    removed_ids: list[int] = []

    if body.member_ids is not None:
        new_member_ids = {int(x) for x in body.member_ids}
        # Always keep the editor in the member list.
        new_member_ids.add(editor_id)

        current_members = await get_deadline_members(deadline_id)
        current_ids = {m.user_id for m in current_members}

        add_ids = list(new_member_ids - current_ids)
        remove_ids = list(current_ids - new_member_ids)

        if add_ids or remove_ids:
            result = await access.assign_by_id(deadline_id, add_ids, remove_ids)
            if result is not None:
                added_ids, removed_ids, _conflicts = result

    members = await get_deadline_members(deadline_id)

    # ── Notify affected users — same DM messages as Discord cog ──────────────
    unix_ts = int(deadline.due_date.replace(tzinfo=UTC).timestamp())

    change_parts: list[str] = []
    if body.new_title is not None:
        change_parts.append(f'title → **"{deadline.title}"**')
    if parsed_date is not None:
        change_parts.append(f"due date → <t:{unix_ts}:F>")
    if body.description is not None:
        change_parts.append("description updated")
    if added_ids or removed_ids:
        change_parts.append("members updated")
    changes_str = ", ".join(change_parts) if change_parts else "details updated"

    # Notify existing members about changes (excluding the editor).
    existing_notify_ids = [m.user_id for m in members if m.user_id != editor_id]
    if existing_notify_ids:
        dm_msg = (
            f"<@{editor_id}> has updated the deadline "
            f'**"{deadline.title}"** — {changes_str}.'
        )
        await notify_users(bot, existing_notify_ids, dm_msg)

    # Notify newly added members.
    if added_ids:
        add_msg = (
            f"<@{editor_id}> has added you to the deadline "
            f'**"{deadline.title}"** due <t:{unix_ts}:F>.'
        )
        newly_added = [uid for uid in added_ids if uid != editor_id]
        if newly_added:
            await notify_users(bot, newly_added, add_msg)

    # Notify removed members.
    if removed_ids:
        remove_msg = (
            f'<@{editor_id}> has removed you from the deadline **"{deadline.title}"**.'
        )
        await notify_users(bot, removed_ids, remove_msg)

    return _to_response(deadline, members)


@router.delete("/{deadline_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_deadline(
    deadline_id: int,
    current_user: DiscordUser = Depends(get_current_user),
    bot: discord.Client = Depends(get_bot),
) -> None:
    """Delete a deadline. Notifies all assigned members via DM."""
    deleter_id = int(current_user.id)
    access = DeadlineAccess(deleter_id)

    # Fetch members before deletion so we can notify them.
    members_before = await get_deadline_members(deadline_id)

    deadline = await access.delete_by_id(deadline_id)
    if deadline is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Deadline not found or you are not assigned to it.",
        )

    # Notify all assigned members — same DM as Discord cog.
    unix_ts = int(deadline.due_date.replace(tzinfo=UTC).timestamp())
    notify_ids = [m.user_id for m in members_before]
    if notify_ids:
        dm_msg = (
            f"<@{deleter_id}> has deleted the deadline "
            f'**"{deadline.title}"** (was due <t:{unix_ts}:F>).'
        )
        await notify_users(bot, notify_ids, dm_msg)
