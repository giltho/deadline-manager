from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from models import Deadline, DeadlineMember

# Use a Railway persistent volume when available, otherwise local file.
# On Railway: attach a volume at /data and this picks it up automatically.
_db_dir = os.environ.get("RAILWAY_VOLUME_MOUNT_PATH", ".")
_DATABASE_URL = f"sqlite+aiosqlite:///{_db_dir}/deadlines.db"

_engine = create_async_engine(_DATABASE_URL, echo=False)


async def init_db() -> None:
    """Create all tables if they don't already exist."""
    async with _engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Async context manager yielding a database session."""
    async with AsyncSession(_engine, expire_on_commit=False) as session:
        yield session


# ── Query helpers ─────────────────────────────────────────────────────────────


async def get_deadline_by_title(title: str) -> Deadline | None:
    """Return a Deadline by exact title match, or None."""
    async with get_session() as session:
        result = await session.exec(select(Deadline).where(Deadline.title == title))
        return result.first()


async def get_all_future_deadlines() -> list[Deadline]:
    """Return all deadlines whose due_date is in the future (UTC), sorted ascending."""
    now = datetime.now(UTC).replace(tzinfo=None)
    async with get_session() as session:
        result = await session.exec(
            select(Deadline).where(Deadline.due_date > now).order_by(Deadline.due_date)  # type: ignore[arg-type]
        )
        return list(result.all())


async def get_upcoming_deadlines(
    days: int | None = None,
    user_id: int | None = None,
) -> list[Deadline]:
    """
    Return upcoming (future) deadlines, optionally filtered by:
      - days: only deadlines due within the next N days
      - user_id: only deadlines the given Discord user is assigned to
    Results are sorted by due_date ascending.
    """
    from datetime import timedelta

    now = datetime.now(UTC).replace(tzinfo=None)

    async with get_session() as session:
        stmt = select(Deadline).where(Deadline.due_date > now)

        if days is not None:
            cutoff = now + timedelta(days=days)
            stmt = stmt.where(Deadline.due_date <= cutoff)

        if user_id is not None:
            stmt = stmt.join(DeadlineMember).where(DeadlineMember.user_id == user_id)

        stmt = stmt.order_by(Deadline.due_date)  # type: ignore[arg-type]
        result = await session.exec(stmt)
        return list(result.all())


async def get_deadline_members(deadline_id: int) -> list[DeadlineMember]:
    """Return all DeadlineMember rows for a given deadline."""
    async with get_session() as session:
        result = await session.exec(
            select(DeadlineMember).where(DeadlineMember.deadline_id == deadline_id)
        )
        return list(result.all())


async def autocomplete_titles(prefix: str) -> list[str]:
    """
    Return up to 25 deadline titles that start with *prefix* (case-insensitive),
    sorted alphabetically. Used for slash command autocomplete.
    """
    async with get_session() as session:
        result = await session.exec(
            select(Deadline.title)
            .where(Deadline.title.istartswith(prefix))  # type: ignore[union-attr]
            .order_by(Deadline.title)  # type: ignore[arg-type]
            .limit(25)
        )
        return list(result.all())
