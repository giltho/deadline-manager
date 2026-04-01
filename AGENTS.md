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
                    Also starts the FastAPI server via uvicorn in a background thread, passing bot=bot to create_app().
config.py           Settings via pydantic-settings. ALLOWED_ROLE_IDS is a str;
                    use settings.parsed_role_ids (list[int]) in code.
                    Settings() needs # type: ignore[call-arg].
                    resolved_port property: reads Railway $PORT env var first, falls back to api_port (default 8000).
models.py           SQLModel tables: Deadline and DeadlineMember.
                    NO `from __future__ import annotations` — breaks SQLModel runtime.
                    Datetimes use datetime.now(UTC).replace(tzinfo=None) as default_factory.
db.py               Database layer. The single most important file to understand.
checks.py           has_allowed_role() decorator for slash commands.
calendar_sync.py    Stub only. All methods are no-ops.
cogs/deadlines.py   All /deadline slash commands.
cogs/reminders.py   APScheduler reminder cog. Fires at 14, 7, 3 days before due_date.
discord_utils.py    notify_users(bot, user_ids, message) — sends DMs via the live bot instance.
                    send_dm(bot, user_id, message) — sends a single DM; swallows Forbidden errors.
api/main.py         FastAPI app factory: create_app(bot=None). Stores bot in app.state.bot.
                    CORS allows GET, POST, PATCH, DELETE.
api/deps.py         FastAPI dependencies:
                    - get_current_user: validates Bearer token via Discord /users/@me
                    - get_current_guild_member: chains get_current_user + guild membership check
                      via bot token (GET /guilds/{guild_id}/members/{user_id}). Returns 403
                      for non-members, 503 on network error, 502 on unexpected Discord status.
                      THIS is the dependency all routers use — not get_current_user directly.
                    - get_bot: retrieves bot from app.state.bot
                    - get_settings: returns Settings instance
api/schemas.py      Pydantic schemas: DeadlineCreateRequest, DeadlineEditRequest, DeadlineResponse,
                    DiscordUser, GuildMember (with display_name property).
api/routers/deadlines.py  REST endpoints for deadlines. All write ops call notify_users().
api/routers/guild.py      REST endpoints for guild member lookup (search + list all).
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

# ID-based methods — used by the REST API (Raycast extension)
await access.get_by_id(deadline_id)                          # Deadline | None
await access.edit_by_id(deadline_id, new_title, due_date, description)  # Deadline | None
await access.assign_by_id(deadline_id, add_ids, remove_ids)             # (added, removed, conflicts) | None
await access.delete_by_id(deadline_id)                       # Deadline | None (returns snapshot before deletion)
```

The title-based methods are used exclusively by Discord slash commands. The ID-based methods
are used exclusively by the REST API. Do not mix them.

### Module-level helpers (admin/background use only)

```python
get_all_future_deadlines()          # Used by reminders cog — no user filter
get_deadline_members(deadline_id)   # Used by cogs and REST API to build responses after write operations
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
tests/test_api.py           Tests for FastAPI REST endpoints (auth, CRUD, notifications, guild)
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

### Patching pattern for API tests

All write endpoints (`POST`, `PATCH`, `DELETE /deadlines`) depend on both `get_current_guild_member`
and `get_bot`. Use the `mock_auth_and_bot` fixture for these; use `mock_auth` for read-only
endpoints; use `mock_auth_and_settings` for guild endpoints.

**Always override `get_current_guild_member`, not `get_current_user`.** All routers declare
`get_current_guild_member` as their dependency; overriding only the inner `get_current_user`
has no effect because FastAPI resolves the outermost declared dependency.

```python
@pytest.fixture()
def mock_auth_and_bot(app):
    from api.deps import get_bot, get_current_guild_member
    fake_bot = MagicMock()
    app.dependency_overrides[get_current_guild_member] = lambda: FAKE_USER
    app.dependency_overrides[get_bot] = lambda: fake_bot
    yield fake_bot
    app.dependency_overrides.clear()
```

When testing the real `get_current_guild_member` dependency chain (e.g. `TestAuth`), also
override `get_settings` so pydantic-settings doesn't try to read a missing `.env`:

```python
app.dependency_overrides[get_settings] = lambda: FAKE_SETTINGS
```

Always patch `api.routers.deadlines.notify_users` (not `discord_utils.notify_users`) in API
tests — the router imports it at module level, so the patch target must be the router's
namespace.

When `get_deadline_members` is called more than once in a single request (e.g. `PATCH`
fetches current members for the diff, then fetches again for the final response), use
`side_effect` with a list of plain values on an `AsyncMock`:

```python
mock_get_members.side_effect = [first_call_result, second_call_result]
```

Do **not** use `AsyncMock(return_value=...)()` (pre-called coroutines) in `side_effect` —
this produces a coroutine object that is not iterable and causes a `TypeError` at runtime.

## Raycast Extension (`raycast-extension/`)

A private Raycast extension (not published to the Store). Install from source:

```bash
cd raycast-extension
npm install
npm run build    # or: npm run dev  for hot-reload
```

In Raycast: **Settings → Extensions → + → Add Script Directory** — point at `raycast-extension/`.

### Key source files

```
src/oauth.ts            Discord OAuth2 PKCE client setup (no proxy).
src/api.ts              All HTTP calls to the FastAPI backend. Types: DeadlineResponse,
                        DeadlineCreateRequest, DeadlineEditRequest, GuildMember.
src/list-deadlines.tsx  Main command. Shows deadlines with detail panel. Supports Edit (⌘E)
                        and Delete (ctrl+X) per-row actions.
src/create-deadline.tsx Create command / pushed form. Uses Form.TagPicker for member assignment.
src/edit-deadline.tsx   Edit form, pre-filled with existing values. Same TagPicker pattern.
```

### API functions (`src/api.ts`)

```ts
listDeadlines(days?)                          // GET /deadlines
createDeadline(body: DeadlineCreateRequest)   // POST /deadlines → DeadlineResponse
editDeadline(id, body: DeadlineEditRequest)   // PATCH /deadlines/{id} → DeadlineResponse
deleteDeadline(id)                            // DELETE /deadlines/{id} → void (204)
getMembers(ids: string[])                     // GET /guild/members/all, filtered client-side
getAllMembers()                               // GET /guild/members/all
searchMembers(query, limit?)                 // GET /guild/members/search
```

`apiFetch` guards `204 No Content` responses — returns `undefined` instead of calling
`.json()` (which would throw on an empty body).

### Member name resolution in the detail panel

`DeadlineDetail` in `list-deadlines.tsx` resolves all user IDs (members + `created_by`) via
a single `getMembers(allIds)` call. While loading, both the "Created By" and "Members" rows
show `"Loading…"` rather than the raw snowflake ID. After resolution, the creator falls back
to `"User <id>"` only if the ID is not found in the guild.

### Icon

Place a 512×512 PNG at `raycast-extension/assets/command-icon.png` (matches `"icon"` in
`package.json`). The `assets/` directory is otherwise empty.

## Raycast Extension OAuth2

The Raycast extension authenticates users via Discord OAuth2 using the **direct PKCE flow** (no proxy).

### How the flow works

```
Raycast (oauth.ts)
  → OAuth.PKCEClient (RedirectMethod.Web) generates PKCE values
  → Opens https://discord.com/oauth2/authorize?...&redirect_uri=https://raycast.com/redirect?packageName=Extension
  → User approves in browser; Discord redirects to raycast.com
  → Raycast hands authorization code back to extension
  → OAuthService POSTs to https://discord.com/api/oauth2/token (form-encoded) to exchange code for token
  → Token stored by Raycast; attached as Authorization: Bearer <token> on every API call
  → FastAPI (api/deps.py) validates the token by forwarding to https://discord.com/api/v10/users/@me
```

### Discord Developer Portal configuration

In your Discord app (client ID `1484564963996598413`), under **OAuth2 → Redirects**, register **exactly**:

```
https://raycast.com/redirect?packageName=Extension
```

This is the static redirect URI that Raycast's `OAuth.RedirectMethod.Web` uses for all extensions.

### Why no proxy?

The `oauth.raycast.com` PKCE proxy exists for providers that don't support PKCE natively. Discord
**does** support PKCE (code_challenge / code_verifier on its standard authorization endpoint), so
the proxy is unnecessary and introduces confusion about which redirect URI to register.

### Key implementation details

- `bodyEncoding: "url-encoded"` is required — Discord's token endpoint only accepts
  `application/x-www-form-urlencoded` bodies and returns an error for JSON.
- The `DISCORD_CLIENT_SECRET` in `.env` is used by the server only; the Raycast extension
  never sees it. The extension uses only `clientId` (public).
- `api/deps.py` is fully stateless — it validates every request by forwarding the Bearer
  token to `https://discord.com/api/v10/users/@me`.

### Raycast extension API base URL

The extension (`raycast-extension/src/api.ts`) calls the Railway-hosted FastAPI server.
The URL must **not** include a port number:

```ts
// Correct — Railway's HTTPS ingress terminates TLS at port 443
const API_BASE_URL = "https://deadline-manager-production.up.railway.app";

// Wrong — port 8080 is the internal container port, not the public-facing one
// const API_BASE_URL = "https://deadline-manager-production.up.railway.app:8080";
```

The `api_port` setting in `config.py` (default `8000`) is for local development and is
the port uvicorn binds to inside the container. Railway routes external HTTPS traffic to
it automatically.

## Migrations (Alembic)

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
9. **Railway `$PORT`** — Railway injects a `PORT` env var telling the container which port to
   bind to. `config.py`'s `resolved_port` property reads `PORT` first, falling back to
   `api_port` (default `8000`) for local dev. `bot.py` passes `settings.resolved_port` to
   uvicorn. Never hardcode port `8000` or `8080` in the Railway service URL — Railway's HTTPS
   ingress always listens on 443 externally regardless of the container port.
10. **`notify_users` requires the live bot** — `discord_utils.notify_users(bot, ids, msg)` calls
    `bot.fetch_user()` which needs a connected `discord.Client`. The FastAPI layer receives the
    bot via `app.state.bot` (set in `create_app(bot=...)` in `api/main.py`) and retrieves it
    via the `get_bot` dependency in `api/deps.py`. If `bot` is `None` (e.g. in tests that don't
    use `mock_auth_and_bot`), any write endpoint that calls `notify_users` will raise at runtime.
11. **`delete_by_id` returns a snapshot, not the live row** — the deleted `Deadline` object is
    copied into a new in-memory `Deadline` instance before deletion so the caller can read fields
    (e.g. `title`, `due_date`) after the DB row is gone.
12. **PATCH member diff: `side_effect` must be plain values** — `get_deadline_members` is called
    twice in `PATCH /deadlines/{id}` (once for the diff, once for the final response). In tests,
    set `mock_get_members.side_effect = [list1, list2]` with plain list values, not pre-awaited
    coroutines. See patching pattern section above.
13. **Override `get_current_guild_member`, not `get_current_user` in API tests** — all routers
    use `get_current_guild_member` as their outermost auth dependency. Overriding the inner
    `get_current_user` has no effect because FastAPI resolves the outermost declared dependency
    and never reaches the inner one. Always use `app.dependency_overrides[get_current_guild_member]`.
14. **`get_current_guild_member` requires `get_settings`** — when testing the real auth chain
    (not using a fixture shortcut), also override `get_settings` with `lambda: FAKE_SETTINGS` to
    prevent pydantic-settings from failing on a missing `.env` file.

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
