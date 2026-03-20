from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

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


# ── Module-level functions (admin/background use) ─────────────────────────────


async def get_all_future_deadlines() -> list[Deadline]:
    """Return all deadlines whose due_date is in the future (UTC), sorted ascending."""
    now = datetime.now(UTC).replace(tzinfo=None)
    async with get_session() as session:
        result = await session.exec(
            select(Deadline).where(Deadline.due_date > now).order_by(Deadline.due_date)  # type: ignore[arg-type]
        )
        return list(result.all())


async def get_deadline_members(deadline_id: int) -> list[DeadlineMember]:
    """Return all DeadlineMember rows for a given deadline."""
    async with get_session() as session:
        result = await session.exec(
            select(DeadlineMember).where(DeadlineMember.deadline_id == deadline_id)
        )
        return list(result.all())


# ── Private helpers (used only by DeadlineAccess) ─────────────────────────────


async def _get_deadline_by_title(title: str) -> Deadline | None:
    """Return a Deadline by exact title match, or None."""
    async with get_session() as session:
        result = await session.exec(select(Deadline).where(Deadline.title == title))
        return result.first()


async def _get_upcoming_deadlines(
    days: int | None = None,
    user_id: int | None = None,
) -> list[Deadline]:
    """
    Return upcoming (future) deadlines, optionally filtered by:
      - days: only deadlines due within the next N days
      - user_id: only deadlines the given Discord user is assigned to
    Results are sorted by due_date ascending.
    """
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


async def _autocomplete_titles(prefix: str, user_id: int | None = None) -> list[str]:
    """
    Return up to 25 deadline titles that start with *prefix* (case-insensitive),
    sorted alphabetically. Used for slash command autocomplete.

    If *user_id* is given, only titles for deadlines the user is assigned to
    are returned.
    """
    async with get_session() as session:
        stmt = select(Deadline.title).where(Deadline.title.istartswith(prefix))  # type: ignore[union-attr]
        if user_id is not None:
            stmt = stmt.join(DeadlineMember).where(DeadlineMember.user_id == user_id)
        stmt = stmt.order_by(Deadline.title).limit(25)
        result = await session.exec(stmt)
        return list(result.all())


# ── DeadlineAccess — user-scoped accessor ─────────────────────────────────────


class DeadlineAccess:
    """
    All user-facing deadline queries go through this class.
    Instantiate with the Discord user_id; every method enforces membership.
    """

    def __init__(self, user_id: int) -> None:
        self._user_id = user_id

    async def get_by_title(self, title: str) -> Deadline | None:
        """Return deadline only if this user is assigned. None otherwise."""
        async with get_session() as session:
            result = await session.exec(
                select(Deadline)
                .where(Deadline.title == title)
                .join(DeadlineMember)
                .where(DeadlineMember.user_id == self._user_id)
            )
            return result.first()

    async def list_upcoming(self, days: int | None = None) -> list[Deadline]:
        """Upcoming deadlines for this user only."""
        return await _get_upcoming_deadlines(days=days, user_id=self._user_id)

    async def autocomplete(self, prefix: str) -> list[str]:
        """Title suggestions for this user only."""
        return await _autocomplete_titles(prefix, user_id=self._user_id)

    async def create(
        self,
        title: str,
        due_date: datetime,
        description: str | None,
        user_ids: list[int],
    ) -> Deadline | None:
        """
        Create a new deadline and assign given user_ids.
        Returns None if a deadline with the same title already exists.
        """
        async with get_session() as session:
            existing = await session.exec(
                select(Deadline).where(Deadline.title == title)
            )
            if existing.first():
                return None

            deadline = Deadline(
                title=title,
                description=description,
                due_date=due_date,
                created_by=self._user_id,
            )
            session.add(deadline)
            await session.flush()

            for uid in user_ids:
                session.add(
                    DeadlineMember(deadline_id=deadline.id, user_id=uid)  # type: ignore[arg-type]
                )
            await session.commit()
            await session.refresh(deadline)
            return deadline

    async def edit(
        self,
        title: str,
        new_title: str | None = None,
        due_date: datetime | None = None,
        description: str | None = None,
    ) -> Deadline | None:
        """
        Edit deadline fields. Returns the updated Deadline, or None if not assigned.
        """
        async with get_session() as session:
            # Check membership in the same session
            check = await session.exec(
                select(Deadline)
                .where(Deadline.title == title)
                .join(DeadlineMember)
                .where(DeadlineMember.user_id == self._user_id)
            )
            db_deadline = check.first()
            if db_deadline is None:
                return None

            if new_title is not None:
                db_deadline.title = new_title
            if due_date is not None:
                db_deadline.due_date = due_date
            if description is not None:
                db_deadline.description = description

            session.add(db_deadline)
            await session.commit()
            await session.refresh(db_deadline)
            return db_deadline

    async def assign(
        self,
        title: str,
        add_ids: list[int],
        remove_ids: list[int],
    ) -> tuple[list[int], list[int]] | None:
        """
        Add/remove members from a deadline.
        Returns (added, removed) lists, or None if user is not assigned.
        """
        async with get_session() as session:
            # Check membership in the same session
            check = await session.exec(
                select(Deadline)
                .where(Deadline.title == title)
                .join(DeadlineMember)
                .where(DeadlineMember.user_id == self._user_id)
            )
            deadline = check.first()
            if deadline is None:
                return None

            added: list[int] = []
            removed: list[int] = []

            for uid in add_ids:
                exists = await session.exec(
                    select(DeadlineMember).where(
                        DeadlineMember.deadline_id == deadline.id,
                        DeadlineMember.user_id == uid,
                    )
                )
                if not exists.first():
                    session.add(
                        DeadlineMember(deadline_id=deadline.id, user_id=uid)  # type: ignore[arg-type]
                    )
                    added.append(uid)

            for uid in remove_ids:
                existing = await session.exec(
                    select(DeadlineMember).where(
                        DeadlineMember.deadline_id == deadline.id,
                        DeadlineMember.user_id == uid,
                    )
                )
                row = existing.first()
                if row:
                    await session.delete(row)
                    removed.append(uid)

            await session.commit()

        return added, removed

    async def delete(self, title: str) -> Deadline | None:
        """
        Delete deadline. Returns the deleted Deadline, or None if not assigned.
        """
        async with get_session() as session:
            # Check membership in the same session
            check = await session.exec(
                select(Deadline)
                .where(Deadline.title == title)
                .join(DeadlineMember)
                .where(DeadlineMember.user_id == self._user_id)
            )
            deadline = check.first()
            if deadline is None:
                return None

            # Store a copy of data before deletion
            deleted_snapshot = Deadline(
                id=deadline.id,
                title=deadline.title,
                description=deadline.description,
                due_date=deadline.due_date,
                created_by=deadline.created_by,
                created_at=deadline.created_at,
                outlook_event_id=deadline.outlook_event_id,
            )
            await session.delete(deadline)
            await session.commit()

        return deleted_snapshot
