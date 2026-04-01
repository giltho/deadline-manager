"""
FastAPI dependencies: Discord auth and bot access.

Every protected endpoint injects
`current_user: DiscordUser = Depends(get_current_guild_member)`.
Auth is fully stateless — no sessions or JWTs are stored server-side.

Flow:
  1. Client sends `Authorization: Bearer <discord_oauth_token>`.
  2. get_current_user: forward token to Discord's /users/@me → DiscordUser.
  3. get_current_guild_member: call GET /guilds/{id}/members/{user_id} with
     the bot token to verify the user is actually in our guild.
     Returns 401 for bad tokens, 403 for valid-but-not-in-guild users,
     503/502 for Discord API problems.

`get_bot()` provides the live `discord.Client` so routers can send DMs.
It raises HTTP 503 when the bot is not wired in (e.g. during unit tests that
mock notifications separately).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
import httpx
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from api.schemas import DiscordUser
from config import Settings, get_settings

if TYPE_CHECKING:
    pass

_bearer = HTTPBearer()

DISCORD_API_BASE = "https://discord.com/api/v10"


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> DiscordUser:
    """
    Validate the Discord OAuth Bearer token by calling /users/@me.

    Raises HTTP 401 if the token is missing, invalid, or revoked.
    """
    token = credentials.credentials
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{DISCORD_API_BASE}/users/@me",
                headers={"Authorization": f"Bearer {token}"},
                timeout=10.0,
            )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not reach Discord API.",
        ) from exc

    if resp.status_code == 401:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired Discord token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if resp.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Discord API returned unexpected status {resp.status_code}.",
        )

    data = resp.json()
    return DiscordUser(
        id=data["id"],
        username=data["username"],
        global_name=data.get("global_name"),
        avatar=data.get("avatar"),
    )


async def get_current_guild_member(
    current_user: DiscordUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> DiscordUser:
    """
    Extend get_current_user by verifying the user is a member of our guild.

    Calls GET /guilds/{guild_id}/members/{user_id} with the bot token.
    Raises HTTP 403 if the user is not in the guild.
    """
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{DISCORD_API_BASE}/guilds/{settings.discord_guild_id}/members/{current_user.id}",
                headers={"Authorization": f"Bot {settings.discord_token}"},
                timeout=10.0,
            )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not reach Discord API.",
        ) from exc

    if resp.status_code == 404:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this server.",
        )
    if resp.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Discord API returned unexpected status {resp.status_code}.",
        )

    return current_user


def get_bot(request: Request) -> discord.Client:
    """
    Return the live Discord bot client stored in app.state.

    Raises HTTP 503 if the bot has not been wired in (should never happen in
    production; may occur in tests that don't need DM notifications).
    """
    bot: discord.Client | None = getattr(request.app.state, "bot", None)
    if bot is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Discord bot not available.",
        )
    return bot
