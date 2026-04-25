# Deadline Bot

A Discord bot for research group deadline management. Members with designated roles can create and manage deadlines, assign group members, and receive automatic reminders at 14, 7, and 3 days before each due date.

## Features

- Slash commands for creating, editing, listing, and deleting deadlines
- User-scoped privacy: you only see deadlines you are assigned to — others cannot access them
- Assign/unassign Discord members to specific deadlines
- Automatic reminders posted to a configured channel at 14, 7, and 3 days before the due date
- Reminders survive restarts — all future jobs are rescheduled on startup
- Role-based access control: only members with allowed roles can manage deadlines
- Paginated `/deadline list` with Prev/Next buttons
- Flexible date parsing with smart time defaulting (see below)
- SQLite database via SQLModel — zero external database required
- Optional Microsoft Graph calendar sync (stubbed, ready to implement)

## Commands

All commands are guild-scoped slash commands under the `/deadline` group.

| Command | Description |
|---|---|
| `/deadline help` | Show a usage guide (only visible to you) |
| `/deadline add` | Create a new deadline |
| `/deadline list` | List your upcoming deadlines (paginated, 10 per page) |
| `/deadline info` | Show full details for a deadline |
| `/deadline edit` | Update title, due date, or description |
| `/deadline assign` | Add or remove assigned members |
| `/deadline delete` | Delete a deadline (confirmation required) |
| `/deadline show-everyone` | Post your deadlines publicly in the channel |
| `/deadline test-dms` | Verify the bot can DM you (required for reminders) |

All `title` parameters support autocomplete, filtered to your own deadlines.

### Due date formats

The `due_date` parameter on `/deadline add` and `/deadline edit` accepts flexible input:

| Input | Interpreted as |
|---|---|
| `2026-06-15` | 23:59:59 UK time on 15 Jun 2026 (BST or GMT, DST-aware) |
| `15 Jun 2026` | 23:59:59 UK time on 15 Jun 2026 |
| `2026-06-15 17:00` | 17:00:00 UTC on 15 Jun 2026 (explicit time, treated as UTC) |
| `15 Jun 2026 17:00` | 17:00:00 UTC on 15 Jun 2026 |
| `2026-06-15 AoE` | 23:59:59 Anywhere on Earth (UTC−12) = 11:59:59 UTC on 16 Jun 2026 |
| `15 Jun 2026 aoe` | Same as above (`AoE` is case-insensitive) |

**No time given** — defaults to **23:59:59 UK time** (`Europe/London`), which is BST (UTC+1) in summer and GMT (UTC+0) in winter.

**AoE (Anywhere on Earth)** — append `AoE` after the date to use the latest timezone on Earth (UTC−12). This means the deadline is not considered passed until the clock strikes midnight everywhere on the planet — a common convention for academic paper submissions.

### Privacy model

All bot replies are **ephemeral** (visible only to you) except `/deadline show-everyone`. Deadline data is user-scoped at the database layer — autocomplete, list, info, edit, assign, and delete all enforce that you must be assigned to a deadline before you can see or modify it.

## Tech Stack

- [discord.py](https://discordpy.readthedocs.io/) >= 2.4 — slash commands via `app_commands`
- [SQLModel](https://sqlmodel.tiangolo.com/) + [aiosqlite](https://aiosqlite.omnilib.dev/) — async SQLite ORM
- [APScheduler](https://apscheduler.readthedocs.io/) >= 3.10 — reminder scheduling
- [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) — environment-based config
- [python-dateutil](https://dateutil.readthedocs.io/) — flexible date parsing
- [uv](https://docs.astral.sh/uv/) — package and environment management
- [ruff](https://docs.astral.sh/ruff/) — linting and formatting
- [ty](https://docs.astral.sh/ty/) — type checking

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

### Linting, formatting, and type-checking

```bash
uv run ruff check .
uv run ruff format .
uv run ty check
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

**Bot token** — Create an application at [discord.com/developers/applications](https://discord.com/developers/applications), add a Bot, and copy the token.

**Guild, role, and channel IDs** — Enable Developer Mode in Discord (Settings → Advanced → Developer Mode), then right-click any server, role, or channel and select "Copy ID".

**Invite the bot** — Generate an invite URL with the `bot` and `applications.commands` scopes and the following permissions: Send Messages, Embed Links, Read Message History, Mention Everyone (for reminder pings).

## Deploying with Docker Compose

The project includes a `Dockerfile` and `docker-compose.yml` designed to run behind a [Traefik](https://traefik.io/) reverse proxy with automatic TLS via Let's Encrypt.

### Prerequisites

- A server with Docker and Docker Compose installed
- A Traefik instance running and connected to a Docker network named `traefik`
- A domain pointed at the server

### Steps

1. Copy the example env file and fill in your values:

   ```bash
   cp .env.example .env
   ```

   Set `DEADLINE_HOSTNAME` to your public domain (e.g. `deadlines.example.com`). This is used by Traefik to route HTTPS traffic to the container.

2. Create the data directory for the SQLite database:

   ```bash
   mkdir -p deadline_manager
   ```

3. Build and start the service:

   ```bash
   docker compose up -d --build
   ```

The bot will apply any pending database migrations automatically on startup before accepting connections.

## Microsoft Graph Calendar Sync (Optional)

Calendar sync is stubbed in `calendar_sync.py` and wired into all command handlers with `# calendar_sync TODO:` comments marking the integration points. The interface is complete and safe to call today (all methods return `None`/`False`).

To implement sync:

1. Register an application in the [Azure Portal](https://portal.azure.com) and grant it the `Calendars.ReadWrite` application permission.
2. Fill in the four `MS_*` environment variables.
3. Implement the methods in `calendar_sync.py` — the stubs document the expected behaviour.
4. Uncomment the `calendar_sync TODO:` blocks in `cogs/deadlines.py`.

## Project Structure

```
deadline-manager/
├── bot.py              # Entry point; bot setup and cog loading
├── config.py           # pydantic-settings config; parsed_role_ids property
├── models.py           # SQLModel table definitions (Deadline, DeadlineMember)
├── db.py               # Async DB engine, DeadlineAccess class, module-level helpers
├── checks.py           # has_allowed_role() app_commands check decorator
├── calendar_sync.py    # Microsoft Graph client stub
├── cogs/
│   ├── deadlines.py    # All /deadline slash commands
│   └── reminders.py    # APScheduler-based reminder cog
├── tests/              # pytest test suite (86 tests)
├── Dockerfile          # Multi-stage build
├── pyproject.toml      # uv project, dependencies, ruff and pytest config
└── .env.example        # Template for required environment variables
```
