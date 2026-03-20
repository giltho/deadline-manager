# AGENT.md — Codebase Guide for AI Agents

This file explains how the codebase is structured and how to navigate it safely.

## Toolchain

| Tool | Purpose | Command |
|---|---|---|
| `uv` | Package & environment management | `uv sync`, `uv run <cmd>` |
| `ruff` | Linting and formatting | `uv run ruff check .` / `uv run ruff format .` |
| `ty` | Type checking (advisory) | `uv run ty check` |
| `pytest` | Test suite | `uv run pytest` |

**Never** use `pip`, `black`, `mypy`, or `pyright`. No `requirements.txt` — dependencies live in `pyproject.toml`.

CI runs ruff (hard fail), ty (advisory, `continue-on-error: true`), and pytest (hard fail).

## Key Files

```
bot.py              Entry point. Loads cogs, runs alembic upgrade head, calls init_db(), syncs slash commands.
config.py           Settings via pydantic-settings. ALLOWED_ROLE_IDS is a str;
                    use settings.parsed_role_ids (list[int]) in code.
                    Settings() needs # type: ignore[call-arg].
models.py           SQLModel tables: Deadline and DeadlineMember.
                    NO `from __future__ import annotations` — breaks SQLModel runtime.
                    Datetimes use datetime.now(UTC).replace(tzinfo=None) as default_factory.
db.py               Database layer. The single most important file to understand.
checks.py           has_allowed_role() decorator for slash commands.
calendar_sync.py    Stub only. All methods are no-ops.
cogs/deadlines.py   All /deadline slash commands.
cogs/reminders.py   APScheduler reminder cog. Fires at 14, 7, 3 days before due_date.
```

## Database Layer (`db.py`)

### Session

```python
@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    ...
```

Always use `async with get_session() as session:`. Import `AsyncSession` from
`sqlmodel.ext.asyncio.session`, not from `sqlalchemy`.

**Critical:** a `_make_session_ctx` in tests can only be consumed once per `with patch.object`
block. If a function makes two `get_session` calls, use two separate patch blocks in the test.

### DeadlineAccess

The primary API for all user-facing deadline operations. Instantiate with the Discord user ID;
every method enforces membership — users only see and modify deadlines they are assigned to.

```python
access = DeadlineAccess(interaction.user.id)

await access.get_by_title(title)          # Deadline | None
await access.list_upcoming(days=7)        # list[Deadline]
await access.autocomplete(prefix)         # list[str]  (up to 25 results)
await access.create(title, due_date, description, user_ids)  # Deadline | None (None = per-user title conflict)
await access.edit(title, new_title, due_date, description)   # Deadline | None (None = not assigned)
await access.assign(title, add_ids, remove_ids)              # (added, removed, conflicts) | None
await access.delete(title)                                   # Deadline | None (None = not assigned)
```

All methods that need a membership check do the join inside a **single session** to avoid the
double-consume problem.

### Module-level helpers (admin/background use only)

```python
get_all_future_deadlines()          # Used by reminders cog — no user filter
get_deadline_members(deadline_id)   # Used by cogs to build embeds after write operations
```

### Private helpers (do not call directly outside db.py)

```python
_get_deadline_by_title(title)       # No membership check; used by show-everyone public path
_get_upcoming_deadlines(...)        # Backing implementation for DeadlineAccess.list_upcoming
_autocomplete_titles(...)           # Backing implementation for DeadlineAccess.autocomplete
```

`_get_deadline_by_title` is imported into `cogs/deadlines.py` at module level so it can be
patched in tests for the `show-everyone` single-deadline path.

## Slash Commands (`cogs/deadlines.py`)

All commands are under the `/deadline` group. Pattern for every command handler:

```python
access = DeadlineAccess(interaction.user.id)
result = await access.some_method(...)
if result is None:
    await interaction.response.send_message("Not found.", ephemeral=True)
    return
# ... use result
```

All responses are `ephemeral=True` except `/deadline show-everyone` which is `ephemeral=False`.

`_title_autocomplete` is the shared autocomplete callback — it filters to the invoking user's
own deadlines via `DeadlineAccess.autocomplete`.

## Models (`models.py`)

```python
class Deadline(SQLModel, table=True):
    id: int | None          # auto-incremented PK
    title: str              # indexed; unique per-user (enforced in DeadlineAccess, not at DB level)
    description: str | None
    due_date: datetime      # naive UTC
    created_by: int         # Discord user ID
    created_at: datetime    # naive UTC, auto-set
    outlook_event_id: str | None  # calendar sync stub

class DeadlineMember(SQLModel, table=True):
    id: int | None
    deadline_id: int        # FK → Deadline.id (cascade delete)
    user_id: int            # Discord user ID
```

All datetimes are **naive UTC** — no `tzinfo`. Use `datetime.now(UTC).replace(tzinfo=None)`.

## Tests

```
tests/conftest.py           Fixtures: db_session (in-memory SQLite), mock_interaction, make_deadline, make_member
tests/test_db.py            Tests for DeadlineAccess and module-level helpers
tests/test_deadlines.py     Tests for slash command handlers; mocks DeadlineAccess
tests/test_migration.py     Integration tests for the Alembic migration
tests/test_reminders.py     Tests for the reminders cog
tests/test_models.py        Unit tests for model properties
tests/test_checks.py        Tests for has_allowed_role()
tests/test_config.py        Tests for Settings parsing
tests/test_calendar_sync.py Tests for the calendar stub
```

### Patching pattern for command tests

Mock `DeadlineAccess` at the module level using `_make_access_mock()`:

```python
access = _make_access_mock(get_by_title=some_deadline, ...)
with patch.object(deadlines_module, "DeadlineAccess", return_value=access):
    await cog.deadline_info.callback(cog, mock_interaction, title="My Deadline")
```

For `show-everyone` single-deadline path, patch `_get_deadline_by_title` directly:

```python
with patch.object(deadlines_module, "_get_deadline_by_title", new=AsyncMock(return_value=dl)):
    ...
```

`mock_interaction.user.id` defaults to `123456789` (set in `conftest.py`).

## Known Gotchas

1. **`from __future__ import annotations` in `models.py`** — must not be present; breaks SQLModel
   relationship resolution at runtime.
2. **`get_session` context manager** — yields one session; patching it with `_make_session_ctx`
   wraps the test session. A patched ctx can only be consumed once per `with patch.object` block.
3. **`timedelta.days` truncates** — `delta.days` for fractional days rounds down; tests that
   compare days remaining use `>= N-1` where timing is involved.
4. **`yearfirst=True` in dateutil** — required to parse ISO dates like `2026-07-09` correctly.
5. **`intents.members = True` removed** — caused `PrivilegedIntentsRequired` on Railway.
6. **`Settings()` call** — needs `# type: ignore[call-arg]`; `ty` doesn't understand
   pydantic-settings env population.
7. **`ty` false positives in tests** — `ty` incorrectly flags keyword args to `.callback()`
   as "already assigned". These are advisory and do not block CI.
8. **Railway volume** — mount at `/data`; `db.py` reads `RAILWAY_VOLUME_MOUNT_PATH` env var
   to locate `deadlines.db`.

## Migrations (Alembic)

Database schema changes are managed via Alembic. Migrations live in `migrations/versions/`.

### Adding a new migration

```bash
uv run alembic revision -m "describe the change"
```

Then edit the generated file in `migrations/versions/`. For SQLite always use either
`op.batch_alter_table(...)` with `recreate='always'` or raw SQL copy-rename — SQLite
does not support `ALTER TABLE DROP CONSTRAINT` / `ADD COLUMN NOT NULL` etc. directly.

### Running migrations

```bash
uv run alembic upgrade head   # apply all pending migrations
uv run alembic downgrade -1   # revert last migration
```

The bot runs `alembic upgrade head` automatically on startup (in `bot.py`) before
`init_db()`, so existing deployed databases are migrated on redeploy.

### Current migrations

| Revision | Description |
|---|---|
| `001` | Drop global `UNIQUE` constraint on `deadline.title`; uniqueness is now enforced per-user at the application layer in `DeadlineAccess`. |

### env.py notes

- `migrations/env.py` reads `RAILWAY_VOLUME_MOUNT_PATH` (same as `db.py`) to find the DB.
- Uses the **sync** SQLite driver (`sqlite:///`) — Alembic's standard runner is synchronous.
  `db.py` continues to use `aiosqlite`.
- `render_as_batch=True` is set in both offline and online modes (required for SQLite).
- `import models  # noqa: F401` registers all SQLModel table metadata so Alembic can
  detect autogenerate diffs.
