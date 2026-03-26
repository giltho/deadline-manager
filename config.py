from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ── Discord ───────────────────────────────────────────────────────────────
    discord_token: str
    discord_guild_id: int
    deadline_channel_id: int
    reminder_channel_id: int

    # ── Microsoft Graph (all optional — omit to disable calendar sync) ────────
    # TODO: Populate and enable these when implementing calendar sync.
    ms_tenant_id: str | None = None
    ms_client_id: str | None = None
    ms_client_secret: str | None = None
    ms_calendar_id: str | None = None  # target mailbox / shared calendar

    @property
    def calendar_sync_enabled(self) -> bool:
        """True only when all four MS Graph vars are present."""
        return all(
            [
                self.ms_tenant_id,
                self.ms_client_id,
                self.ms_client_secret,
                self.ms_calendar_id,
            ]
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached Settings singleton."""
    return Settings()  # type: ignore[call-arg]
