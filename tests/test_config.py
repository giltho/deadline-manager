"""Tests for config.py — settings loading and validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from config import Settings


def _make_settings(monkeypatch, extra: dict | None = None):
    """Helper: set minimum required env vars, optionally override with *extra*."""
    base = {
        "DISCORD_TOKEN": "tok",
        "DISCORD_GUILD_ID": "111",
        "DEADLINE_CHANNEL_ID": "777",
        "REMINDER_CHANNEL_ID": "999",
    }
    # Clear optional MS_* vars so they don't bleed in from a real .env
    for key in ("MS_TENANT_ID", "MS_CLIENT_ID", "MS_CLIENT_SECRET", "MS_CALENDAR_ID"):
        monkeypatch.delenv(key, raising=False)
    for k, v in {**base, **(extra or {})}.items():
        monkeypatch.setenv(k, v)
    return Settings(_env_file=None)  # type: ignore[call-arg]


def test_valid_settings(monkeypatch):
    s = _make_settings(monkeypatch)
    assert s.discord_token == "tok"
    assert s.discord_guild_id == 111
    assert s.deadline_channel_id == 777
    assert s.reminder_channel_id == 999


def test_missing_required_fields(monkeypatch):
    keys = (
        "DISCORD_TOKEN",
        "DISCORD_GUILD_ID",
        "DEADLINE_CHANNEL_ID",
        "REMINDER_CHANNEL_ID",
    )
    for key in keys:
        monkeypatch.delenv(key, raising=False)

    with pytest.raises((ValidationError, Exception)):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_calendar_sync_disabled_when_ms_vars_absent(monkeypatch):
    s = _make_settings(monkeypatch)
    assert s.calendar_sync_enabled is False


def test_calendar_sync_enabled_when_ms_vars_present(monkeypatch):
    s = _make_settings(
        monkeypatch,
        extra={
            "MS_TENANT_ID": "t",
            "MS_CLIENT_ID": "c",
            "MS_CLIENT_SECRET": "s",
            "MS_CALENDAR_ID": "cal@example.com",
        },
    )
    assert s.calendar_sync_enabled is True
