"""Drop global UNIQUE constraint on deadline.title.

Revision ID: 001
Revises: (none — first migration)
Create Date: 2026-03-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic
revision: str = "001"
down_revision: str | None = None
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    """Recreate the deadline table without the UNIQUE constraint on title.

    SQLite does not support ALTER TABLE DROP CONSTRAINT; the only way to
    remove an inline UNIQUE is the copy-rename pattern (create new table
    without the constraint, copy data, drop old table, rename).

    This migration is a no-op on fresh installs where the table does not yet
    exist (those are handled by SQLModel.metadata.create_all in db.py).
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "deadline" not in inspector.get_table_names():
        return

    # Check whether the unique constraint is still present.
    # If a previous (failed) run already removed it we skip safely.
    unique_constraints = inspector.get_unique_constraints("deadline")
    title_unique_exists = any(
        "title" in uc["column_names"] for uc in unique_constraints
    )
    if not title_unique_exists:
        return

    # Copy-rename: create a clean table, copy data, replace.
    op.execute(sa.text("PRAGMA foreign_keys=OFF"))
    op.execute(
        sa.text(
            """
            CREATE TABLE _deadline_new (
                id       INTEGER NOT NULL,
                title    VARCHAR NOT NULL,
                description VARCHAR,
                due_date DATETIME NOT NULL,
                created_by INTEGER NOT NULL,
                created_at DATETIME NOT NULL,
                outlook_event_id VARCHAR,
                PRIMARY KEY (id)
            )
            """
        )
    )
    op.execute(
        sa.text(
            "INSERT INTO _deadline_new "
            "SELECT id, title, description, due_date, "
            "       created_by, created_at, outlook_event_id "
            "FROM deadline"
        )
    )
    op.execute(sa.text("DROP TABLE deadline"))
    op.execute(sa.text("ALTER TABLE _deadline_new RENAME TO deadline"))
    op.execute(
        sa.text("CREATE INDEX IF NOT EXISTS ix_deadline_title ON deadline (title)")
    )
    op.execute(sa.text("PRAGMA foreign_keys=ON"))


def downgrade() -> None:
    """Restore the UNIQUE constraint on deadline.title."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "deadline" not in inspector.get_table_names():
        return

    op.execute(sa.text("PRAGMA foreign_keys=OFF"))
    op.execute(
        sa.text(
            """
            CREATE TABLE _deadline_old (
                id       INTEGER NOT NULL,
                title    VARCHAR NOT NULL UNIQUE,
                description VARCHAR,
                due_date DATETIME NOT NULL,
                created_by INTEGER NOT NULL,
                created_at DATETIME NOT NULL,
                outlook_event_id VARCHAR,
                PRIMARY KEY (id)
            )
            """
        )
    )
    op.execute(
        sa.text(
            "INSERT INTO _deadline_old "
            "SELECT id, title, description, due_date, "
            "       created_by, created_at, outlook_event_id "
            "FROM deadline"
        )
    )
    op.execute(sa.text("DROP TABLE deadline"))
    op.execute(sa.text("ALTER TABLE _deadline_old RENAME TO deadline"))
    op.execute(
        sa.text("CREATE INDEX IF NOT EXISTS ix_deadline_title ON deadline (title)")
    )
    op.execute(sa.text("PRAGMA foreign_keys=ON"))
