from __future__ import annotations

from discord import Interaction
from discord.app_commands import CheckFailure, check

from config import get_settings


def in_deadline_channel():
    """
    app_commands.check decorator that restricts a command to the configured
    deadline channel (DEADLINE_CHANNEL_ID).

    Replies with an ephemeral error when invoked from the wrong channel.

    Usage:
        @in_deadline_channel()
        async def my_command(self, interaction: Interaction) -> None:
            ...
    """

    async def predicate(interaction: Interaction) -> bool:
        settings = get_settings()
        if interaction.channel_id == settings.deadline_channel_id:
            return True

        raise CheckFailure(
            f"This command can only be used in <#{settings.deadline_channel_id}>."
        )

    return check(predicate)
