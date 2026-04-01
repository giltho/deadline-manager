"""
/guild endpoints.

GET /guild/members/search?query=<str>&limit=<int>
    Search guild members by username or nickname prefix.
    Proxied to Discord's REST API using the bot token.
    Does NOT require the GUILD_MEMBERS privileged intent.

GET /guild/members?ids=<id1>&ids=<id2>...
    Resolve a list of Discord user IDs to GuildMember objects.
    Uses the bot token to fetch each member from the guild.
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


@router.get("/members", response_model=list[GuildMember])
async def get_guild_members(
    ids: Annotated[
        list[str],
        Query(description="Discord user IDs to resolve."),
    ],
    _current_user: DiscordUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> list[GuildMember]:
    """
    Resolve a list of Discord user IDs to GuildMember objects.

    Fetches each member individually from the guild using the bot token.
    IDs that cannot be found are silently omitted from the result.
    """
    guild_id = settings.discord_guild_id
    bot_token = settings.discord_token

    members: list[GuildMember] = []
    async with httpx.AsyncClient() as client:
        for user_id in ids:
            try:
                resp = await client.get(
                    f"{DISCORD_API_BASE}/guilds/{guild_id}/members/{user_id}",
                    headers={"Authorization": f"Bot {bot_token}"},
                    timeout=10.0,
                )
            except httpx.RequestError:
                continue  # skip unreachable

            if resp.status_code != 200:
                continue  # member not found or left the guild — skip silently

            raw = resp.json()
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
