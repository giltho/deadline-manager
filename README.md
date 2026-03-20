# Deadline Bot

A Discord bot for research group deadline management. Members with designated roles can create and manage deadlines, assign group members, and receive automatic reminders at 14, 7, and 3 days before each due date.

## Features

- Slash commands for creating, editing, listing, and deleting deadlines
- Assign/unassign Discord members to specific deadlines
- Automatic reminders posted to a configured channel at 14, 7, and 3 days before the due date
- Reminders survive restarts — all future jobs are rescheduled on startup
- Role-based access control: only members with allowed roles can manage deadlines
- Paginated `/deadline list` with Prev/Next buttons
- Flexible date parsing (`2026-06-15`, `15 Jun 2026 17:00`, etc.)
- SQLite database via SQLModel — zero external database required
- Optional Microsoft Graph calendar sync (stubbed, ready to implement)

## Commands

All commands are guild-scoped slash commands under the `/deadline` group.

| Command | Description |
|---|---|
| `/deadline add` | Create a new deadline |
| `/deadline list` | List upcoming deadlines (paginated, 10 per page) |
| `/deadline info` | Show full details for a deadline |
| `/deadline edit` | Update title, due date, or description |
| `/deadline assign` | Add or remove assigned members |
| `/deadline delete` | Delete a deadline (confirmation required) |

All `title` parameters support autocomplete.

## Tech Stack

- [discord.py](https://discordpy.readthedocs.io/) >= 2.4 — slash commands via `app_commands`
- [SQLModel](https://sqlmodel.tiangolo.com/) + [aiosqlite](https://aiosqlite.omnilib.dev/) — async SQLite ORM
- [APScheduler](https://apscheduler.readthedocs.io/) >= 3.10 — reminder scheduling
- [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) — environment-based config
- [python-dateutil](https://dateutil.readthedocs.io/) — flexible date parsing
- [uv](https://docs.astral.sh/uv/) — package and environment management
- [ruff](https://docs.astral.sh/ruff/) — linting and formatting

## Local Development

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/getting-started/installation/)

### Setup

```bash
# Clone and enter the project
git clone <repo-url>
cd deadline-manager

# Install all dependencies (including dev)
uv sync

# Copy the example env file and fill in your values
cp .env.example .env
```

Edit `.env` with your bot credentials (see [Configuration](#configuration) below).

### Running the bot

```bash
uv run python bot.py
```

### Running tests

```bash
uv run pytest
```

With coverage:

```bash
uv run pytest --cov
```

### Linting and formatting

```bash
uv run ruff check .
uv run ruff format .
```

## Configuration

All configuration is via environment variables (or a `.env` file at the project root).

| Variable | Required | Description |
|---|---|---|
| `DISCORD_TOKEN` | Yes | Bot token from the Discord Developer Portal |
| `DISCORD_GUILD_ID` | Yes | ID of the guild (server) to deploy commands to |
| `ALLOWED_ROLE_IDS` | Yes | Comma-separated role IDs permitted to manage deadlines, e.g. `123,456` |
| `REMINDER_CHANNEL_ID` | Yes | ID of the text channel where reminders are posted |
| `MS_TENANT_ID` | No | Azure AD tenant ID (for calendar sync — see below) |
| `MS_CLIENT_ID` | No | Azure AD app client ID |
| `MS_CLIENT_SECRET` | No | Azure AD app client secret |
| `MS_CALENDAR_ID` | No | Target calendar mailbox, e.g. `shared@example.com` |

### Getting the required IDs

**Bot token** — Create an application at [discord.com/developers/applications](https://discord.com/developers/applications), add a Bot, and copy the token. Enable the **Server Members Intent** under the bot's Privileged Gateway Intents.

**Guild, role, and channel IDs** — Enable Developer Mode in Discord (Settings → Advanced → Developer Mode), then right-click any server, role, or channel and select "Copy ID".

**Invite the bot** — Generate an invite URL with the `bot` and `applications.commands` scopes and the following permissions: Send Messages, Embed Links, Read Message History, Mention Everyone (for reminder pings).

## Deploying to Railway

The project includes a multi-stage `Dockerfile` ready for [Railway](https://railway.app).

### Steps

1. Push the repository to GitHub (or connect directly via the Railway CLI).

2. Create a new project in Railway and select **Deploy from GitHub repo** (or **Deploy from Dockerfile** if using the CLI).

3. Set the following environment variables in Railway's **Variables** tab — do not commit a `.env` file:

   ```
   DISCORD_TOKEN=...
   DISCORD_GUILD_ID=...
   ALLOWED_ROLE_IDS=...
   REMINDER_CHANNEL_ID=...
   ```

4. Railway will build the Docker image and start the bot automatically. The SQLite database file (`deadlines.db`) is written to the `/app` working directory inside the container.

> **Note on persistence:** Railway's filesystem is ephemeral by default — the database will be lost on redeploy. To persist data, attach a [Railway Volume](https://docs.railway.app/reference/volumes) and set the database path via an environment variable, or migrate to a hosted Postgres/SQLite-compatible service.

### Deploying with the Railway CLI

```bash
# Install the CLI
npm install -g @railway/cli

# Log in and link the project
railway login
railway link

# Deploy
railway up
```

## Microsoft Graph Calendar Sync (Optional)

Calendar sync is stubbed in `calendar_sync.py` and wired into all command handlers with `# calendar_sync TODO:` comments marking the integration points. The interface is complete and safe to call today (all methods return `None`/`False`).

To implement sync:

1. Register an application in the [Azure Portal](https://portal.azure.com) and grant it the `Calendars.ReadWrite` application permission (or delegated, depending on your setup).
2. Fill in the four `MS_*` environment variables.
3. Implement the methods in `calendar_sync.py` — the stubs document the expected behaviour.
4. Uncomment the `calendar_sync TODO:` blocks in `cogs/deadlines.py`.

## Project Structure

```
deadline-manager/
├── bot.py              # Entry point; bot setup and error handling
├── config.py           # pydantic-settings config with parsed_role_ids property
├── models.py           # SQLModel table definitions (Deadline, DeadlineMember)
├── db.py               # Async database engine and query helpers
├── checks.py           # has_allowed_role() app_commands check decorator
├── calendar_sync.py    # Microsoft Graph client stub
├── cogs/
│   ├── deadlines.py    # All six /deadline slash commands
│   └── reminders.py    # APScheduler-based reminder cog
├── tests/              # pytest test suite (68 tests)
├── Dockerfile          # Multi-stage Railway-ready build
├── pyproject.toml      # uv project, dependencies, ruff and pytest config
└── .env.example        # Template for required environment variables
```
