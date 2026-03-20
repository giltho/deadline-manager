"""Tests for db.py — DeadlineAccess and module-level helpers."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from sqlalchemy.ext.asyncio import AsyncSession

from models import Deadline, DeadlineMember


# Patch db.get_session to use the test session from the fixture
@asynccontextmanager
async def _make_session_ctx(session: AsyncSession):
    yield session


async def _seed(session: AsyncSession) -> list[Deadline]:
    """Insert three deadlines: past, near, far."""
    now = datetime.now(UTC).replace(tzinfo=None)
    deadlines = [
        Deadline(title="Past", due_date=now - timedelta(days=1), created_by=1),
        Deadline(title="Near", due_date=now + timedelta(days=2), created_by=1),
        Deadline(title="Far", due_date=now + timedelta(days=30), created_by=2),
    ]
    for dl in deadlines:
        session.add(dl)
    await session.flush()

    # Assign user 99 to "Near" only
    assert deadlines[1].id is not None
    session.add(DeadlineMember(deadline_id=deadlines[1].id, user_id=99))
    await session.commit()
    for dl in deadlines:
        await session.refresh(dl)
    return deadlines


# ── get_all_future_deadlines ──────────────────────────────────────────────────


async def test_get_all_future_deadlines_excludes_past(db_session):
    import db as db_module

    await _seed(db_session)

    with patch.object(
        db_module,
        "get_session",
        return_value=_make_session_ctx(db_session),
    ):
        results = await db_module.get_all_future_deadlines()
        titles = [r.title for r in results]
        assert "Past" not in titles
        assert "Near" in titles
        assert "Far" in titles


async def test_get_all_future_deadlines_sorted(db_session):
    import db as db_module

    await _seed(db_session)

    with patch.object(
        db_module,
        "get_session",
        return_value=_make_session_ctx(db_session),
    ):
        results = await db_module.get_all_future_deadlines()
        dates = [r.due_date for r in results]
        assert dates == sorted(dates)


# ── get_deadline_members ──────────────────────────────────────────────────────


async def test_get_deadline_members(db_session):
    import db as db_module

    deadlines = await _seed(db_session)
    near = deadlines[1]  # user 99 assigned
    assert near.id is not None

    with patch.object(
        db_module,
        "get_session",
        return_value=_make_session_ctx(db_session),
    ):
        members = await db_module.get_deadline_members(near.id)
        assert len(members) == 1
        assert members[0].user_id == 99


# ── DeadlineAccess.get_by_title ───────────────────────────────────────────────


async def test_access_get_by_title_found(db_session):
    import db as db_module

    await _seed(db_session)

    with patch.object(
        db_module, "get_session", return_value=_make_session_ctx(db_session)
    ):
        access = db_module.DeadlineAccess(99)
        result = await access.get_by_title("Near")
        assert result is not None
        assert result.title == "Near"


async def test_access_get_by_title_not_assigned(db_session):
    import db as db_module

    await _seed(db_session)

    with patch.object(
        db_module, "get_session", return_value=_make_session_ctx(db_session)
    ):
        access = db_module.DeadlineAccess(1)  # user 1 is NOT assigned to "Near"
        result = await access.get_by_title("Near")
        assert result is None


async def test_access_get_by_title_not_found(db_session):
    import db as db_module

    await _seed(db_session)

    with patch.object(
        db_module, "get_session", return_value=_make_session_ctx(db_session)
    ):
        access = db_module.DeadlineAccess(99)
        result = await access.get_by_title("Nonexistent")
        assert result is None


# ── DeadlineAccess.list_upcoming ──────────────────────────────────────────────


async def test_access_list_upcoming_no_filter(db_session):
    import db as db_module

    await _seed(db_session)

    with patch.object(
        db_module, "get_session", return_value=_make_session_ctx(db_session)
    ):
        access = db_module.DeadlineAccess(99)
        results = await access.list_upcoming()
        titles = [r.title for r in results]
        assert titles == ["Near"]  # user 99 only assigned to Near


async def test_access_list_upcoming_days_filter(db_session):
    import db as db_module

    await _seed(db_session)

    with patch.object(
        db_module, "get_session", return_value=_make_session_ctx(db_session)
    ):
        access = db_module.DeadlineAccess(99)
        results = await access.list_upcoming(days=7)
        titles = [r.title for r in results]
        assert "Near" in titles
        assert "Far" not in titles


# ── DeadlineAccess.autocomplete ───────────────────────────────────────────────


async def test_access_autocomplete_prefix(db_session):
    import db as db_module

    await _seed(db_session)

    with patch.object(
        db_module, "get_session", return_value=_make_session_ctx(db_session)
    ):
        access = db_module.DeadlineAccess(99)
        results = await access.autocomplete("n")
        assert results == ["Near"]


async def test_access_autocomplete_case_insensitive(db_session):
    import db as db_module

    await _seed(db_session)

    with patch.object(
        db_module, "get_session", return_value=_make_session_ctx(db_session)
    ):
        access = db_module.DeadlineAccess(99)
        results = await access.autocomplete("N")
        assert "Near" in results


async def test_access_autocomplete_user_scoped(db_session):
    import db as db_module

    await _seed(db_session)

    with patch.object(
        db_module, "get_session", return_value=_make_session_ctx(db_session)
    ):
        # user 99 only sees Near
        access = db_module.DeadlineAccess(99)
        results = await access.autocomplete("")
        assert results == ["Near"]

    with patch.object(
        db_module, "get_session", return_value=_make_session_ctx(db_session)
    ):
        # user 1 is assigned to nothing
        access = db_module.DeadlineAccess(1)
        results = await access.autocomplete("")
        assert results == []


# ── DeadlineAccess.create ─────────────────────────────────────────────────────


async def test_access_create(db_session):
    from datetime import timedelta

    import db as db_module

    due = datetime.now(UTC).replace(tzinfo=None) + timedelta(days=5)

    with patch.object(
        db_module, "get_session", return_value=_make_session_ctx(db_session)
    ):
        access = db_module.DeadlineAccess(1)
        deadline = await access.create("New", due, "desc", [1, 2])
        assert deadline is not None
        assert deadline.title == "New"
        assert deadline.created_by == 1


async def test_access_create_duplicate_returns_none(db_session):
    import db as db_module

    await _seed(db_session)
    due = datetime.now(UTC).replace(tzinfo=None) + timedelta(days=5)

    with patch.object(
        db_module, "get_session", return_value=_make_session_ctx(db_session)
    ):
        access = db_module.DeadlineAccess(1)
        result = await access.create("Near", due, None, [1])
        assert result is None


# ── DeadlineAccess.edit ───────────────────────────────────────────────────────


async def test_access_edit_success(db_session):
    import db as db_module

    deadlines = await _seed(db_session)
    near = deadlines[1]

    with patch.object(
        db_module, "get_session", return_value=_make_session_ctx(db_session)
    ):
        access = db_module.DeadlineAccess(99)
        updated = await access.edit(near.title, new_title="Near Updated")
        assert updated is not None
        assert updated.title == "Near Updated"

    with patch.object(
        db_module, "get_session", return_value=_make_session_ctx(db_session)
    ):
        # Verify in DB
        from sqlmodel import select

        result = await db_session.exec(
            select(Deadline).where(Deadline.title == "Near Updated")
        )
        assert result.first() is not None


async def test_access_edit_not_assigned_returns_none(db_session):
    import db as db_module

    await _seed(db_session)

    with patch.object(
        db_module, "get_session", return_value=_make_session_ctx(db_session)
    ):
        access = db_module.DeadlineAccess(1)  # user 1 not assigned to Near
        result = await access.edit("Near", new_title="Should Fail")
        assert result is None


# ── DeadlineAccess.assign ─────────────────────────────────────────────────────


async def test_access_assign_add(db_session):
    import db as db_module

    await _seed(db_session)

    with patch.object(
        db_module, "get_session", return_value=_make_session_ctx(db_session)
    ):
        access = db_module.DeadlineAccess(99)
        result = await access.assign("Near", add_ids=[42], remove_ids=[])
        assert result is not None
        added, removed = result
        assert 42 in added
        assert removed == []


async def test_access_assign_remove(db_session):
    import db as db_module

    await _seed(db_session)

    with patch.object(
        db_module, "get_session", return_value=_make_session_ctx(db_session)
    ):
        access = db_module.DeadlineAccess(99)
        result = await access.assign("Near", add_ids=[], remove_ids=[99])
        assert result is not None
        added, removed = result
        assert added == []
        assert 99 in removed


async def test_access_assign_not_assigned_returns_none(db_session):
    import db as db_module

    await _seed(db_session)

    with patch.object(
        db_module, "get_session", return_value=_make_session_ctx(db_session)
    ):
        access = db_module.DeadlineAccess(1)  # not assigned to Near
        result = await access.assign("Near", add_ids=[42], remove_ids=[])
        assert result is None


# ── DeadlineAccess.delete ─────────────────────────────────────────────────────


async def test_access_delete_success(db_session):
    import db as db_module

    await _seed(db_session)

    with patch.object(
        db_module, "get_session", return_value=_make_session_ctx(db_session)
    ):
        access = db_module.DeadlineAccess(99)
        deleted = await access.delete("Near")
        assert deleted is not None
        assert deleted.title == "Near"

    with patch.object(
        db_module, "get_session", return_value=_make_session_ctx(db_session)
    ):
        from sqlmodel import select

        result = await db_session.exec(select(Deadline).where(Deadline.title == "Near"))
        assert result.first() is None


async def test_access_delete_not_assigned_returns_none(db_session):
    import db as db_module

    await _seed(db_session)

    with patch.object(
        db_module, "get_session", return_value=_make_session_ctx(db_session)
    ):
        access = db_module.DeadlineAccess(1)  # not assigned to Near
        result = await access.delete("Near")
        assert result is None
