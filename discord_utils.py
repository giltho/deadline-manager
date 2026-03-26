"""Shared Discord utility helpers."""

from __future__ import annotations

import logging
from typing import Literal

import discord

logger = logging.getLogger(__name__)

DMResult = Literal["sent", "forbidden", "error"]


async def send_dm(
    bot: discord.Client,
    user_id: int,
    message: str,
) -> DMResult:
    """Attempt to send *message* as a DM to *user_id*.

    Returns:
      ``"sent"``      — DM was delivered successfully.
      ``"forbidden"`` — The user has DMs disabled (discord.Forbidden).
      ``"error"``     — Any other HTTP failure.
    """
    try:
        user = await bot.fetch_user(user_id)
        await user.send(message)
        logger.debug("DM sent to user %d.", user_id)
        return "sent"
    except discord.Forbidden:
        logger.warning("Cannot DM user %d (DMs disabled).", user_id)
        return "forbidden"
    except discord.HTTPException as exc:
        logger.error("Failed to DM user %d: %s", user_id, exc)
        return "error"
