"""
Entry point for the Deadline Bot.

Startup sequence:
  1. Load settings from .env
  2. Initialise the SQLite database (create tables if missing)
  3. Set up the Discord bot with default intents
  4. Register a global error handler for slash command check failures
  5. Load cogs (Reminders first so the scheduler is running before commands fire)
  6. Sync slash commands to the configured guild
  7. Start the FastAPI server (uvicorn) alongside the Discord bot
  8. Connect to Discord
"""

from __future__ import annotations

import asyncio
import logging

import discord
import uvicorn
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from discord import app_commands
from discord.ext import commands

from api.main import create_app
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

        # Run any pending Alembic migrations (no-op if already at head).
        # Must run before init_db so existing DBs are migrated before create_all.
        alembic_cfg = AlembicConfig("alembic.ini")
        await asyncio.get_event_loop().run_in_executor(
            None, alembic_command.upgrade, alembic_cfg, "head"
        )
        logger.info("Alembic migrations applied.")

        # Initialise DB schema (creates tables on fresh installs)
        await init_db()
        logger.info("Database initialised.")

        # Register the tree-level error handler for all slash commands.
        # on_app_command_error is NOT a valid discord.py hook on commands.Bot;
        # CommandTree.on_error (wired via @self.tree.error) is the correct API.
        @self.tree.error
        async def on_tree_error(
            interaction: discord.Interaction,
            error: app_commands.AppCommandError,
        ) -> None:
            if isinstance(error, app_commands.CheckFailure):
                msg = str(error) or "You don't have permission to use this command."
            else:
                logger.exception("Unhandled app command error: %s", error)
                msg = "An unexpected error occurred. Please try again later."

            if not interaction.response.is_done():
                await interaction.response.send_message(msg, ephemeral=True)
            else:
                await interaction.followup.send(msg, ephemeral=True)

        # Load cogs
        for cog in COGS:
            await self.load_extension(cog)
            logger.info("Loaded cog: %s", cog)

        # Sync slash commands to the configured guild only (instant propagation)
        guild = discord.Object(id=settings.discord_guild_id)
        self.tree.copy_global_to(guild=guild)
        synced = await self.tree.sync(guild=guild)
        logger.info(
            "Synced %d slash command(s) to guild %d.",
            len(synced),
            settings.discord_guild_id,
        )

    async def on_ready(self) -> None:
        logger.info("Logged in as %s (ID: %d)", self.user, self.user.id)  # type: ignore[union-attr]


async def main() -> None:
    settings = get_settings()
    bot = DeadlineBot()

    # Build the FastAPI app and configure uvicorn to use the running event loop.
    # Pass the bot instance so API routers can send DM notifications.
    app = create_app(bot=bot)
    uvicorn_config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=settings.resolved_port,
        log_level="info",
        # loop="none" tells uvicorn not to create its own event loop; it will
        # use the one that is already running (the same loop as the Discord bot).
        loop="none",
    )
    api_server = uvicorn.Server(uvicorn_config)

    async with bot:
        await asyncio.gather(
            bot.start(settings.discord_token),
            api_server.serve(),
        )


if __name__ == "__main__":
    asyncio.run(main())
