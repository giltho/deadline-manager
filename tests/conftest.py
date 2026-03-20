"""
Shared fixtures for the test suite.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from models import Deadline, DeadlineMember


# ── In-memory database ────────────────────────────────────────────────────────


@pytest.fixture()
async def engine():
    """Create a fresh in-memory SQLite engine per test."""
    _engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with _engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    yield _engine
    async with _engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
    await _engine.dispose()


@pytest.fixture()
async def db_session(engine) -> AsyncGenerator[AsyncSession, None]:
    """Yield an AsyncSession bound to the in-memory engine."""
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session


# ── Config fixtures ───────────────────────────────────────────────────────────


@pytest.fixture()
def mock_settings_no_calendar():
    """Settings with calendar sync disabled (MS_* vars absent)."""
    settings = MagicMock()
    settings.discord_token = "test-token"
    settings.discord_guild_id = 111111111111111111
    settings.allowed_role_ids = [999]
    settings.reminder_channel_id = 222222222222222222
    settings.calendar_sync_enabled = False
    settings.ms_tenant_id = None
    settings.ms_client_id = None
    settings.ms_client_secret = None
    settings.ms_calendar_id = None
    return settings


@pytest.fixture()
def mock_settings_with_calendar(mock_settings_no_calendar):
    """Settings with calendar sync enabled."""
    s = mock_settings_no_calendar
    s.calendar_sync_enabled = True
    s.ms_tenant_id = "tenant-id"
    s.ms_client_id = "client-id"
    s.ms_client_secret = "client-secret"
    s.ms_calendar_id = "calendar@example.com"
    return s


# ── Discord interaction mock ──────────────────────────────────────────────────


@pytest.fixture()
def mock_interaction():
    """
    A MagicMock shaped like a discord.Interaction.
    response.send_message and followup.send are AsyncMocks.
    """
    interaction = MagicMock()
    interaction.user.id = 123456789
    interaction.user.roles = []
    interaction.response = MagicMock()
    interaction.response.is_done = MagicMock(return_value=False)
    interaction.response.send_message = AsyncMock()
    interaction.response.edit_message = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()
    interaction.original_response = AsyncMock(return_value=MagicMock())
    return interaction


# ── Sample data helpers ───────────────────────────────────────────────────────


def make_deadline(
    *,
    id: int = 1,
    title: str = "Test Deadline",
    due_date: datetime | None = None,
    description: str | None = None,
    created_by: int = 123456789,
    outlook_event_id: str | None = None,
) -> Deadline:
    return Deadline(
        id=id,
        title=title,
        description=description,
        due_date=due_date or datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=10),
        created_by=created_by,
        created_at=datetime.now(timezone.utc).replace(tzinfo=None),
        outlook_event_id=outlook_event_id,
    )


def make_member(deadline_id: int = 1, user_id: int = 123456789) -> DeadlineMember:
    return DeadlineMember(deadline_id=deadline_id, user_id=user_id)
