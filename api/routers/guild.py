"""
/guild endpoints.

GET /guild/members/search?query=<str>&limit=<int>
    Search guild members by username or nickname prefix.
    Proxied to Discord's REST API using the bot token.
    Does NOT require the GUILD_MEMBERS privileged intent.
"""

from __future__ import annotations

from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status

from api.deps import DISCORD_API_BASE, get_current_user
from api.schemas import DiscordUser, GuildMember
from config import Settings, get_settings

router = APIRouter(prefix="/guild", tags=["guild"])


@router.get("/members/search", response_model=list[GuildMember])
async def search_guild_members(
    query: Annotated[
        str,
        Query(description="Username/nickname prefix to search for.", min_length=1),
    ],
    limit: Annotated[
        int,
        Query(description="Maximum number of results to return (1-25).", ge=1, le=25),
    ] = 25,
    # Auth required so only guild members can query this endpoint.
    _current_user: DiscordUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> list[GuildMember]:
    """
    Search guild members whose username or nickname starts with *query*.

    Uses the bot token to call Discord's Search Guild Members endpoint, which
    does not require the GUILD_MEMBERS privileged intent.
    """
    guild_id = settings.discord_guild_id
    bot_token = settings.discord_token

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{DISCORD_API_BASE}/guilds/{guild_id}/members/search",
                params={"query": query, "limit": limit},
                headers={"Authorization": f"Bot {bot_token}"},
                timeout=10.0,
            )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not reach Discord API.",
        ) from exc

    if resp.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Discord API returned unexpected status {resp.status_code}.",
        )

    members: list[GuildMember] = []
    for raw in resp.json():
        user = raw.get("user", {})
        members.append(
            GuildMember(
                id=user["id"],
                username=user.get("username", ""),
                global_name=user.get("global_name"),
                nick=raw.get("nick"),
                avatar=user.get("avatar"),
            )
        )
    return members
