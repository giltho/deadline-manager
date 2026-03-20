"""Tests for SQLModel table definitions and cascade delete."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from models import Deadline, DeadlineMember


async def _add_deadline(session: AsyncSession, title: str = "Test") -> Deadline:
    dl = Deadline(
        title=title,
        due_date=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=5),
        created_by=1,
    )
    session.add(dl)
    await session.commit()
    await session.refresh(dl)
    return dl


async def test_deadline_created(db_session):
    dl = await _add_deadline(db_session)
    assert dl.id is not None
    assert dl.title == "Test"
    assert dl.outlook_event_id is None


async def test_deadline_member_created(db_session):
    dl = await _add_deadline(db_session)
    assert dl.id is not None
    member = DeadlineMember(deadline_id=dl.id, user_id=42)
    db_session.add(member)
    await db_session.commit()

    result = await db_session.exec(
        select(DeadlineMember).where(DeadlineMember.deadline_id == dl.id)
    )
    rows = result.all()
    assert len(rows) == 1
    assert rows[0].user_id == 42


async def test_cascade_delete_removes_members(db_session):
    dl = await _add_deadline(db_session)
    assert dl.id is not None
    for uid in [1, 2, 3]:
        db_session.add(DeadlineMember(deadline_id=dl.id, user_id=uid))
    await db_session.commit()

    # Delete the deadline
    db_dl = await db_session.get(Deadline, dl.id)
    await db_session.delete(db_dl)
    await db_session.commit()

    # Members should be gone
    result = await db_session.exec(
        select(DeadlineMember).where(DeadlineMember.deadline_id == dl.id)
    )
    assert result.all() == []


async def test_deadline_defaults(db_session):
    dl = await _add_deadline(db_session, title="Defaults")
    assert dl.created_at is not None
    assert dl.description is None
    assert dl.outlook_event_id is None


async def test_same_title_different_users_allowed_at_db_level(db_session):
    """The DB no longer enforces a global UNIQUE on title.
    Two rows with the same title but different created_by values are permitted.
    Per-user uniqueness is enforced at the application layer (DeadlineAccess.create).
    """
    await _add_deadline(db_session, title="Unique")
    dl2 = Deadline(
        title="Unique",
        due_date=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=5),
        created_by=2,
    )
    db_session.add(dl2)
    await db_session.commit()  # must NOT raise

    result = await db_session.exec(select(Deadline).where(Deadline.title == "Unique"))
    rows = result.all()
    assert len(rows) == 2
