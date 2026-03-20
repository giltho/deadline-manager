from __future__ import annotations

from discord import Interaction
from discord.app_commands import CheckFailure, check

from config import get_settings


def has_allowed_role():
    """
    app_commands.check decorator that restricts a command to members holding
    at least one role whose ID is in ALLOWED_ROLE_IDS.

    Usage:
        @has_allowed_role()
        async def my_command(self, interaction: Interaction) -> None:
            ...
    """

    async def predicate(interaction: Interaction) -> bool:
        settings = get_settings()
        allowed = set(settings.parsed_role_ids)

        member = interaction.user
        # In a guild context interaction.user is a Member with .roles
        user_role_ids = {role.id for role in getattr(member, "roles", [])}

        if user_role_ids & allowed:
            return True

        raise CheckFailure("You don't have permission to use this command.")

    return check(predicate)
