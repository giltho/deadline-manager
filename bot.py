"""
Entry point for the Deadline Bot.

Startup sequence:
  1. Load settings from .env
  2. Initialise the SQLite database (create tables if missing)
  3. Set up the Discord bot with default intents
  4. Register a global error handler for access-control check failures
  5. Load cogs (Reminders first so the scheduler is running before commands fire)
  6. Sync slash commands to the configured guild
  7. Connect to Discord
"""

from __future__ import annotations

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

from config import get_settings
from db import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

COGS = [
    "cogs.reminders",  # load first — deadlines cog references it
    "cogs.deadlines",
]


class DeadlineBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self) -> None:
        settings = get_settings()

        # Initialise DB schema
        await init_db()
        logger.info("Database initialised.")

        # Load cogs
        for cog in COGS:
            await self.load_extension(cog)
            logger.info("Loaded cog: %s", cog)

        # Sync slash commands to the configured guild only (instant propagation)
        guild = discord.Object(id=settings.discord_guild_id)
        self.tree.copy_global_to(guild=guild)
        synced = await self.tree.sync(guild=guild)
        logger.info("Synced %d slash command(s) to guild %d.", len(synced), settings.discord_guild_id)

    async def on_ready(self) -> None:
        logger.info("Logged in as %s (ID: %d)", self.user, self.user.id)  # type: ignore[union-attr]

    async def on_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        """Global handler for slash command errors."""
        if isinstance(error, app_commands.CheckFailure):
            msg = str(error) or "You don't have permission to use this command."
            # Respond ephemerally; handle both fresh and deferred interactions
            if not interaction.response.is_done():
                await interaction.response.send_message(msg, ephemeral=True)
            else:
                await interaction.followup.send(msg, ephemeral=True)
            return

        # Log unexpected errors and inform the user generically
        logger.exception("Unhandled app command error: %s", error)
        msg = "An unexpected error occurred. Please try again later."
        if not interaction.response.is_done():
            await interaction.response.send_message(msg, ephemeral=True)
        else:
            await interaction.followup.send(msg, ephemeral=True)


async def main() -> None:
    settings = get_settings()
    bot = DeadlineBot()
    async with bot:
        await bot.start(settings.discord_token)


if __name__ == "__main__":
    asyncio.run(main())
