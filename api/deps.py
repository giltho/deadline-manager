"""
FastAPI dependency: resolve the current Discord user from the Bearer token.

Every protected endpoint injects
`current_user: DiscordUser = Depends(get_current_user)`.
Auth is fully stateless — no sessions or JWTs are stored server-side.

Flow:
  1. Client sends `Authorization: Bearer <discord_oauth_token>`.
  2. We forward the token to Discord's `/users/@me` endpoint.
  3. Discord validates it and returns the user's profile.
  4. We return a `DiscordUser` for the rest of the request handler.

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
