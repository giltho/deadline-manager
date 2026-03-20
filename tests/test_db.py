"""Tests for db.py query helpers — run against an in-memory SQLite DB."""

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


async def test_get_deadline_by_title_found(db_session):
    import db as db_module

    await _seed(db_session)

    with patch.object(
        db_module,
        "get_session",
        return_value=_make_session_ctx(db_session),
    ):
        result = await db_module.get_deadline_by_title("Near")
        assert result is not None
        assert result.title == "Near"


async def test_get_deadline_by_title_not_found(db_session):
    import db as db_module

    await _seed(db_session)

    with patch.object(
        db_module,
        "get_session",
        return_value=_make_session_ctx(db_session),
    ):
        result = await db_module.get_deadline_by_title("Nonexistent")
        assert result is None


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


async def test_get_upcoming_deadlines_no_filter(db_session):
    import db as db_module

    await _seed(db_session)

    with patch.object(
        db_module,
        "get_session",
        return_value=_make_session_ctx(db_session),
    ):
        results = await db_module.get_upcoming_deadlines()
        titles = {r.title for r in results}
        assert "Past" not in titles
        assert {"Near", "Far"} <= titles


async def test_get_upcoming_deadlines_days_filter(db_session):
    import db as db_module

    await _seed(db_session)

    with patch.object(
        db_module,
        "get_session",
        return_value=_make_session_ctx(db_session),
    ):
        results = await db_module.get_upcoming_deadlines(days=7)
        titles = [r.title for r in results]
        assert "Near" in titles
        assert "Far" not in titles


async def test_get_upcoming_deadlines_user_filter(db_session):
    import db as db_module

    await _seed(db_session)

    with patch.object(
        db_module,
        "get_session",
        return_value=_make_session_ctx(db_session),
    ):
        results = await db_module.get_upcoming_deadlines(user_id=99)
        titles = [r.title for r in results]
        assert titles == ["Near"]


async def test_autocomplete_titles_prefix(db_session):
    import db as db_module

    await _seed(db_session)

    with patch.object(
        db_module,
        "get_session",
        return_value=_make_session_ctx(db_session),
    ):
        results = await db_module.autocomplete_titles("f")
        assert results == ["Far"]


async def test_autocomplete_titles_case_insensitive(db_session):
    import db as db_module

    await _seed(db_session)

    with patch.object(
        db_module,
        "get_session",
        return_value=_make_session_ctx(db_session),
    ):
        results = await db_module.autocomplete_titles("FA")
        assert "Far" in results


async def test_autocomplete_titles_empty_prefix(db_session):
    import db as db_module

    await _seed(db_session)

    with patch.object(
        db_module,
        "get_session",
        return_value=_make_session_ctx(db_session),
    ):
        results = await db_module.autocomplete_titles("")
        # All three titles start with ""
        assert len(results) >= 2  # at least the future ones, possibly Past too
