"""
Pydantic request/response schemas for the REST API.

Kept separate from SQLModel table definitions so the API surface is
decoupled from the DB schema.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

# ── Auth / User ───────────────────────────────────────────────────────────────


class DiscordUser(BaseModel):
    """Minimal Discord user info returned by /users/@me."""

    id: str
    username: str
    global_name: str | None = None
    avatar: str | None = None


# ── Deadlines ─────────────────────────────────────────────────────────────────


class DeadlineResponse(BaseModel):
    """A deadline as returned by the API."""

    id: int
    title: str
    description: str | None
    due_date: datetime
    created_by: int
    created_at: datetime
    member_ids: list[int]


class DeadlineCreateRequest(BaseModel):
    """Payload for POST /deadlines."""

    title: str = Field(..., min_length=1, max_length=200)
    due_date: str = Field(
        ...,
        description=(
            "Flexible date string, same formats as the /deadline add Discord command. "
            "Examples: '2026-06-15', '15 Jun 2026 17:00', '2026-06-15 AoE'"
        ),
    )
    description: str | None = Field(default=None, max_length=1000)
    # Additional member Discord user IDs to assign (creator is always assigned).
    member_ids: list[int] = Field(default_factory=list)


# ── Guild ─────────────────────────────────────────────────────────────────────


class GuildMember(BaseModel):
    """A guild member as returned by GET /guild/members/search."""

    id: str
    username: str
    global_name: str | None = None
    nick: str | None = None
    avatar: str | None = None

    @property
    def display_name(self) -> str:
        """Nick > global_name > username, matching Discord's priority."""
        return self.nick or self.global_name or self.username
