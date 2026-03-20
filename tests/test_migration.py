"""Integration test for the Alembic migration 001_drop_title_unique.

Creates a pre-migration SQLite database (with the old schema including the
UNIQUE constraint on deadline.title), runs ``alembic upgrade head``, and
verifies that:
  1. The UNIQUE constraint on title is gone (two users can share a title).
  2. Pre-existing rows survive the migration intact.
  3. Running upgrade a second time is a no-op (idempotency).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest


@pytest.fixture()
def pre_migration_db(tmp_path: Path) -> Path:
    """Create a SQLite DB with the old schema (title UNIQUE) in a temp dir."""
    db_path = tmp_path / "deadlines.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE deadline (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            title       VARCHAR NOT NULL UNIQUE,
            description VARCHAR,
            due_date    DATETIME NOT NULL,
            created_by  INTEGER NOT NULL,
            created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            outlook_event_id VARCHAR
        )
        """
    )
    conn.execute("CREATE INDEX ix_deadline_title ON deadline (title)")
    conn.execute(
        "CREATE TABLE deadline_member ("
        "  deadline_id INTEGER NOT NULL REFERENCES deadline(id),"
        "  user_id     INTEGER NOT NULL,"
        "  PRIMARY KEY (deadline_id, user_id)"
        ")"
    )
    conn.execute(
        "INSERT INTO deadline (title, due_date, created_by) "
        "VALUES ('CVPR', '2026-06-15 00:00:00', 1)"
    )
    conn.execute(
        "INSERT INTO deadline (title, due_date, created_by) "
        "VALUES ('ICLR', '2026-05-01 00:00:00', 2)"
    )
    conn.commit()
    conn.close()
    return tmp_path


def _run_upgrade(db_dir: Path) -> None:
    """Run alembic upgrade head against the DB in db_dir."""
    import os

    from alembic import command as alembic_command
    from alembic.config import Config as AlembicConfig

    cfg = AlembicConfig("alembic.ini")
    # Override the URL so it points at our test DB directory
    orig = os.environ.get("RAILWAY_VOLUME_MOUNT_PATH")
    os.environ["RAILWAY_VOLUME_MOUNT_PATH"] = str(db_dir)
    try:
        alembic_command.upgrade(cfg, "head")
    finally:
        if orig is None:
            os.environ.pop("RAILWAY_VOLUME_MOUNT_PATH", None)
        else:
            os.environ["RAILWAY_VOLUME_MOUNT_PATH"] = orig


def test_migration_drops_title_unique(pre_migration_db: Path) -> None:
    """After migration, two rows with the same title (different users)
    must be allowed."""
    _run_upgrade(pre_migration_db)

    conn = sqlite3.connect(str(pre_migration_db / "deadlines.db"))
    # Should NOT raise UNIQUE constraint failed
    conn.execute(
        "INSERT INTO deadline (title, due_date, created_by, created_at) "
        "VALUES ('CVPR', '2026-09-01 00:00:00', 99, CURRENT_TIMESTAMP)"
    )
    conn.commit()

    rows = conn.execute(
        "SELECT title, created_by FROM deadline WHERE title = 'CVPR'"
    ).fetchall()
    conn.close()

    assert len(rows) == 2, f"Expected 2 CVPR rows, got {rows}"
    creator_ids = {r[1] for r in rows}
    assert creator_ids == {1, 99}


def test_migration_preserves_existing_rows(pre_migration_db: Path) -> None:
    """Pre-existing rows must survive the migration intact."""
    _run_upgrade(pre_migration_db)

    conn = sqlite3.connect(str(pre_migration_db / "deadlines.db"))
    rows = conn.execute("SELECT title, created_by FROM deadline ORDER BY id").fetchall()
    conn.close()

    assert rows[0] == ("CVPR", 1)
    assert rows[1] == ("ICLR", 2)


def test_migration_idempotent(pre_migration_db: Path) -> None:
    """Running upgrade head twice must be a no-op (no error, same data)."""
    _run_upgrade(pre_migration_db)
    _run_upgrade(pre_migration_db)  # second run must not raise

    conn = sqlite3.connect(str(pre_migration_db / "deadlines.db"))
    count = conn.execute("SELECT COUNT(*) FROM deadline").fetchone()[0]
    conn.close()
    assert count == 2


def test_migration_fresh_install_noop(tmp_path: Path) -> None:
    """On a fresh install with no deadline table, upgrade head must not raise."""
    # Create an empty DB file (just the alembic_version table will be added)
    db_path = tmp_path / "deadlines.db"
    conn = sqlite3.connect(str(db_path))
    conn.close()

    _run_upgrade(tmp_path)  # must not raise
