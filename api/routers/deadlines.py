"""
/deadlines endpoints.

GET  /deadlines          — list the authenticated user's upcoming deadlines
POST /deadlines          — create a new deadline (creator always assigned)
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from api.deps import get_current_user
from api.schemas import DeadlineCreateRequest, DeadlineResponse, DiscordUser
from cogs.deadlines import _parse_due_date
from db import DeadlineAccess, get_deadline_members

router = APIRouter(prefix="/deadlines", tags=["deadlines"])


def _user_access(current_user: DiscordUser) -> DeadlineAccess:
    return DeadlineAccess(int(current_user.id))


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
        results.append(
            DeadlineResponse(
                id=dl.id,  # type: ignore[arg-type]
                title=dl.title,
                description=dl.description,
                due_date=dl.due_date,
                created_by=dl.created_by,
                created_at=dl.created_at,
                member_ids=[m.user_id for m in members],
            )
        )
    return results


@router.post("", response_model=DeadlineResponse, status_code=status.HTTP_201_CREATED)
async def create_deadline(
    body: DeadlineCreateRequest,
    current_user: DiscordUser = Depends(get_current_user),
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
    # Deduplicate: always include the creator; preserve any additional members.
    member_ids = list({creator_id, *body.member_ids})

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
    return DeadlineResponse(
        id=deadline.id,  # type: ignore[arg-type]
        title=deadline.title,
        description=deadline.description,
        due_date=deadline.due_date,
        created_by=deadline.created_by,
        created_at=deadline.created_at,
        member_ids=[m.user_id for m in members],
    )
