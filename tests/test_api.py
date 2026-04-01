"""
Tests for the FastAPI REST API.

Covers:
- GET  /health
- GET  /deadlines
- POST /deadlines
- GET  /guild/members/search
- Authentication (missing token, invalid token, Discord unreachable)
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from api.main import create_app
from api.schemas import DiscordUser
from config import get_settings
from models import Deadline, DeadlineMember

# ── Helpers ───────────────────────────────────────────────────────────────────

FAKE_USER = DiscordUser(id="123456789", username="testuser", global_name="Test User")
FAKE_TOKEN = "fake-discord-oauth-token"
AUTH_HEADERS = {"Authorization": f"Bearer {FAKE_TOKEN}"}


def _future(days: int = 10) -> datetime:
    return datetime.now(UTC).replace(tzinfo=None) + timedelta(days=days)


def _make_deadline(
    id: int = 1,
    title: str = "Test Deadline",
    days: int = 10,
    created_by: int = 123456789,
    description: str | None = None,
) -> Deadline:
    return Deadline(
        id=id,
        title=title,
        description=description,
        due_date=_future(days),
        created_by=created_by,
        created_at=datetime.now(UTC).replace(tzinfo=None),
    )


@asynccontextmanager
async def _make_session_ctx(session: AsyncSession):
    yield session


# ── App fixture ───────────────────────────────────────────────────────────────


@pytest.fixture()
def app():
    return create_app()


@pytest.fixture()
def client(app):
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


# ── Fixture: mock get_current_user ────────────────────────────────────────────


@pytest.fixture()
def mock_auth(app):
    """Override the get_current_user dependency to return FAKE_USER."""
    from api.deps import get_current_user

    app.dependency_overrides[get_current_user] = lambda: FAKE_USER
    yield
    app.dependency_overrides.clear()


FAKE_SETTINGS = MagicMock()
FAKE_SETTINGS.discord_guild_id = 98765
FAKE_SETTINGS.discord_token = "bot-test-token"


@pytest.fixture()
def mock_auth_and_settings(app):
    """Override both get_current_user and get_settings dependencies."""
    from api.deps import get_current_user

    app.dependency_overrides[get_current_user] = lambda: FAKE_USER
    app.dependency_overrides[get_settings] = lambda: FAKE_SETTINGS
    yield
    app.dependency_overrides.clear()


# ══════════════════════════════════════════════════════════════════════════════
# Health
# ══════════════════════════════════════════════════════════════════════════════


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ══════════════════════════════════════════════════════════════════════════════
# Authentication
# ══════════════════════════════════════════════════════════════════════════════


class TestAuth:
    def test_missing_token_returns_401(self, client):
        """No Authorization header → 401 (FastAPI HTTPBearer default)."""
        resp = client.get("/deadlines")
        assert resp.status_code == 401

    def test_invalid_token_returns_401(self, client):
        """Discord returns 401 → our API returns 401."""
        with patch("api.deps.httpx.AsyncClient") as mock_cls:
            mock_resp = MagicMock()
            mock_resp.status_code = 401
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            resp = client.get("/deadlines", headers=AUTH_HEADERS)

        assert resp.status_code == 401

    def test_discord_api_502_on_unexpected_status(self, client):
        """Discord returns an unexpected status code → 502."""
        with patch("api.deps.httpx.AsyncClient") as mock_cls:
            mock_resp = MagicMock()
            mock_resp.status_code = 500
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            resp = client.get("/deadlines", headers=AUTH_HEADERS)

        assert resp.status_code == 502

    def test_discord_network_error_returns_503(self, client):
        """Network error reaching Discord → 503."""
        with patch("api.deps.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(
                side_effect=httpx.ConnectError("connection refused")
            )
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            resp = client.get("/deadlines", headers=AUTH_HEADERS)

        assert resp.status_code == 503

    def test_valid_token_calls_discord_users_me(self, client):
        """A valid token calls /users/@me and the request proceeds."""
        discord_user_payload = {
            "id": "123456789",
            "username": "testuser",
            "global_name": "Test User",
            "avatar": None,
        }
        with patch("api.deps.httpx.AsyncClient") as mock_cls:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json = MagicMock(return_value=discord_user_payload)
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch("api.routers.deadlines.DeadlineAccess") as mock_access_cls:
                mock_access = AsyncMock()
                mock_access.list_upcoming = AsyncMock(return_value=[])
                mock_access_cls.return_value = mock_access

                resp = client.get("/deadlines", headers=AUTH_HEADERS)

        assert resp.status_code == 200
        # Verify the correct Discord endpoint was called
        call_args = mock_client.get.call_args
        assert "/users/@me" in call_args[0][0]
        assert call_args[1]["headers"]["Authorization"] == f"Bearer {FAKE_TOKEN}"


# ══════════════════════════════════════════════════════════════════════════════
# GET /deadlines
# ══════════════════════════════════════════════════════════════════════════════


class TestListDeadlines:
    def test_returns_empty_list(self, client, mock_auth):
        with patch("api.routers.deadlines.DeadlineAccess") as mock_cls:
            mock_access = AsyncMock()
            mock_access.list_upcoming = AsyncMock(return_value=[])
            mock_cls.return_value = mock_access

            resp = client.get("/deadlines", headers=AUTH_HEADERS)

        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_deadlines_with_member_ids(self, client, mock_auth):
        dl = _make_deadline(id=1)
        members = [DeadlineMember(deadline_id=1, user_id=123456789)]

        with (
            patch("api.routers.deadlines.DeadlineAccess") as mock_cls,
            patch(
                "api.routers.deadlines.get_deadline_members",
                new_callable=AsyncMock,
                return_value=members,
            ),
        ):
            mock_access = AsyncMock()
            mock_access.list_upcoming = AsyncMock(return_value=[dl])
            mock_cls.return_value = mock_access

            resp = client.get("/deadlines", headers=AUTH_HEADERS)

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["title"] == "Test Deadline"
        assert data[0]["member_ids"] == ["123456789"]

    def test_days_param_passed_to_access(self, client, mock_auth):
        with patch("api.routers.deadlines.DeadlineAccess") as mock_cls:
            mock_access = AsyncMock()
            mock_access.list_upcoming = AsyncMock(return_value=[])
            mock_cls.return_value = mock_access

            resp = client.get("/deadlines?days=7", headers=AUTH_HEADERS)

        assert resp.status_code == 200
        mock_access.list_upcoming.assert_awaited_once_with(days=7)

    def test_uses_authenticated_user_id(self, client, mock_auth):
        """DeadlineAccess must be instantiated with the caller's Discord user ID."""
        with patch("api.routers.deadlines.DeadlineAccess") as mock_cls:
            mock_access = AsyncMock()
            mock_access.list_upcoming = AsyncMock(return_value=[])
            mock_cls.return_value = mock_access

            client.get("/deadlines", headers=AUTH_HEADERS)

        mock_cls.assert_called_once_with(int(FAKE_USER.id))

    def test_days_must_be_positive(self, client, mock_auth):
        resp = client.get("/deadlines?days=0", headers=AUTH_HEADERS)
        assert resp.status_code == 422

    def test_multiple_deadlines_returned(self, client, mock_auth):
        deadlines = [
            _make_deadline(id=i, title=f"DL {i}", days=i + 1) for i in range(1, 4)
        ]
        members = [
            DeadlineMember(deadline_id=i, user_id=123456789) for i in range(1, 4)
        ]

        async def _fake_get_members(dl_id: int) -> list[DeadlineMember]:
            return [m for m in members if m.deadline_id == dl_id]

        with (
            patch("api.routers.deadlines.DeadlineAccess") as mock_cls,
            patch(
                "api.routers.deadlines.get_deadline_members",
                side_effect=_fake_get_members,
            ),
        ):
            mock_access = AsyncMock()
            mock_access.list_upcoming = AsyncMock(return_value=deadlines)
            mock_cls.return_value = mock_access

            resp = client.get("/deadlines", headers=AUTH_HEADERS)

        assert resp.status_code == 200
        assert len(resp.json()) == 3


# ══════════════════════════════════════════════════════════════════════════════
# POST /deadlines
# ══════════════════════════════════════════════════════════════════════════════


class TestCreateDeadline:
    def _body(self, **overrides):
        return {
            "title": "My Deadline",
            "due_date": "2030-01-15",
            **overrides,
        }

    def test_creates_deadline_returns_201(self, client, mock_auth):
        dl = _make_deadline(id=5, title="My Deadline")
        members = [DeadlineMember(deadline_id=5, user_id=123456789)]

        with (
            patch("api.routers.deadlines.DeadlineAccess") as mock_cls,
            patch(
                "api.routers.deadlines.get_deadline_members",
                new_callable=AsyncMock,
                return_value=members,
            ),
        ):
            mock_access = AsyncMock()
            mock_access.create = AsyncMock(return_value=dl)
            mock_cls.return_value = mock_access

            resp = client.post("/deadlines", json=self._body(), headers=AUTH_HEADERS)

        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "My Deadline"
        assert "123456789" in data["member_ids"]

    def test_creator_always_included_in_member_ids(self, client, mock_auth):
        """Creator (FAKE_USER.id=123456789) must be in user_ids even if not in body."""
        dl = _make_deadline(id=1)
        members = [DeadlineMember(deadline_id=1, user_id=123456789)]

        with (
            patch("api.routers.deadlines.DeadlineAccess") as mock_cls,
            patch(
                "api.routers.deadlines.get_deadline_members",
                new_callable=AsyncMock,
                return_value=members,
            ),
        ):
            mock_access = AsyncMock()
            mock_access.create = AsyncMock(return_value=dl)
            mock_cls.return_value = mock_access

            client.post(
                "/deadlines", json=self._body(member_ids=[]), headers=AUTH_HEADERS
            )

        call_kwargs = mock_access.create.call_args[1]
        assert int(FAKE_USER.id) in call_kwargs["user_ids"]

    def test_extra_member_ids_included(self, client, mock_auth):
        """Extra member IDs from the body are passed through alongside the creator."""
        dl = _make_deadline(id=1)
        members = [
            DeadlineMember(deadline_id=1, user_id=123456789),
            DeadlineMember(deadline_id=1, user_id=999),
        ]

        with (
            patch("api.routers.deadlines.DeadlineAccess") as mock_cls,
            patch(
                "api.routers.deadlines.get_deadline_members",
                new_callable=AsyncMock,
                return_value=members,
            ),
        ):
            mock_access = AsyncMock()
            mock_access.create = AsyncMock(return_value=dl)
            mock_cls.return_value = mock_access

            client.post(
                "/deadlines",
                json=self._body(member_ids=["999"]),
                headers=AUTH_HEADERS,
            )

        call_kwargs = mock_access.create.call_args[1]
        assert 999 in call_kwargs["user_ids"]
        assert int(FAKE_USER.id) in call_kwargs["user_ids"]

    def test_conflict_returns_409(self, client, mock_auth):
        """DeadlineAccess.create returning None → 409 Conflict."""
        with patch("api.routers.deadlines.DeadlineAccess") as mock_cls:
            mock_access = AsyncMock()
            mock_access.create = AsyncMock(return_value=None)
            mock_cls.return_value = mock_access

            resp = client.post("/deadlines", json=self._body(), headers=AUTH_HEADERS)

        assert resp.status_code == 409

    def test_invalid_due_date_returns_422(self, client, mock_auth):
        resp = client.post(
            "/deadlines",
            json=self._body(due_date="not-a-date"),
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 422

    def test_missing_title_returns_422(self, client, mock_auth):
        resp = client.post(
            "/deadlines",
            json={"due_date": "2030-01-15"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 422

    def test_empty_title_returns_422(self, client, mock_auth):
        resp = client.post(
            "/deadlines",
            json=self._body(title=""),
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 422

    def test_description_optional(self, client, mock_auth):
        dl = _make_deadline(id=1, description=None)
        members = [DeadlineMember(deadline_id=1, user_id=123456789)]

        with (
            patch("api.routers.deadlines.DeadlineAccess") as mock_cls,
            patch(
                "api.routers.deadlines.get_deadline_members",
                new_callable=AsyncMock,
                return_value=members,
            ),
        ):
            mock_access = AsyncMock()
            mock_access.create = AsyncMock(return_value=dl)
            mock_cls.return_value = mock_access

            resp = client.post("/deadlines", json=self._body(), headers=AUTH_HEADERS)

        assert resp.status_code == 201
        assert resp.json()["description"] is None

    @pytest.mark.parametrize(
        "due_date_str",
        [
            "2030-06-15",
            "15 Jun 2030",
            "2030-06-15 17:00",
            "15 Jun 2030 17:00",
            "2030-06-15 AoE",
            "15 Jun 2030 aoe",
        ],
    )
    def test_due_date_formats_accepted(self, client, mock_auth, due_date_str):
        dl = _make_deadline(id=1)
        members = [DeadlineMember(deadline_id=1, user_id=123456789)]

        with (
            patch("api.routers.deadlines.DeadlineAccess") as mock_cls,
            patch(
                "api.routers.deadlines.get_deadline_members",
                new_callable=AsyncMock,
                return_value=members,
            ),
        ):
            mock_access = AsyncMock()
            mock_access.create = AsyncMock(return_value=dl)
            mock_cls.return_value = mock_access

            resp = client.post(
                "/deadlines",
                json=self._body(due_date=due_date_str),
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 201, f"Failed for: {due_date_str!r}"

    def test_creator_not_duplicated_in_member_ids(self, client, mock_auth):
        """If creator ID is already in body.member_ids, it should only appear once."""
        dl = _make_deadline(id=1)
        members = [DeadlineMember(deadline_id=1, user_id=123456789)]

        with (
            patch("api.routers.deadlines.DeadlineAccess") as mock_cls,
            patch(
                "api.routers.deadlines.get_deadline_members",
                new_callable=AsyncMock,
                return_value=members,
            ),
        ):
            mock_access = AsyncMock()
            mock_access.create = AsyncMock(return_value=dl)
            mock_cls.return_value = mock_access

            client.post(
                "/deadlines",
                json=self._body(member_ids=[str(int(FAKE_USER.id))]),
                headers=AUTH_HEADERS,
            )

        call_kwargs = mock_access.create.call_args[1]
        assert call_kwargs["user_ids"].count(int(FAKE_USER.id)) == 1


# ══════════════════════════════════════════════════════════════════════════════
# GET /guild/members/search
# ══════════════════════════════════════════════════════════════════════════════


class TestSearchGuildMembers:
    DISCORD_MEMBERS_PAYLOAD = [
        {
            "user": {
                "id": "111",
                "username": "alice",
                "global_name": "Alice",
                "avatar": None,
            },
            "nick": "Ali",
        },
        {
            "user": {
                "id": "222",
                "username": "bob",
                "global_name": None,
                "avatar": None,
            },
            "nick": None,
        },
    ]

    def _mock_discord_search(self, payload):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json = MagicMock(return_value=payload)
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        return mock_ctx, mock_client

    def test_returns_members(self, client, mock_auth_and_settings):
        mock_ctx, _ = self._mock_discord_search(self.DISCORD_MEMBERS_PAYLOAD)
        with patch("api.routers.guild.httpx.AsyncClient", return_value=mock_ctx):
            resp = client.get("/guild/members/search?query=a", headers=AUTH_HEADERS)

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["id"] == "111"
        assert data[0]["username"] == "alice"
        assert data[0]["global_name"] == "Alice"
        assert data[0]["nick"] == "Ali"
        assert data[1]["id"] == "222"
        assert data[1]["nick"] is None

    def test_query_param_required(self, client, mock_auth_and_settings):
        resp = client.get("/guild/members/search", headers=AUTH_HEADERS)
        assert resp.status_code == 422

    def test_query_forwarded_to_discord(self, client, mock_auth_and_settings):
        mock_ctx, mock_client = self._mock_discord_search([])
        with patch("api.routers.guild.httpx.AsyncClient", return_value=mock_ctx):
            client.get(
                "/guild/members/search?query=alice&limit=10", headers=AUTH_HEADERS
            )

        call_kwargs = mock_client.get.call_args[1]
        assert call_kwargs["params"]["query"] == "alice"
        assert call_kwargs["params"]["limit"] == 10

    def test_uses_bot_token(self, client, mock_auth_and_settings):
        """The request to Discord must use the bot token, not the user token."""
        mock_ctx, mock_client = self._mock_discord_search([])
        with patch("api.routers.guild.httpx.AsyncClient", return_value=mock_ctx):
            client.get("/guild/members/search?query=a", headers=AUTH_HEADERS)

        call_kwargs = mock_client.get.call_args[1]
        assert (
            call_kwargs["headers"]["Authorization"]
            == f"Bot {FAKE_SETTINGS.discord_token}"
        )

    def test_discord_error_returns_502(self, client, mock_auth_and_settings):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("api.routers.guild.httpx.AsyncClient", return_value=mock_ctx):
            resp = client.get("/guild/members/search?query=a", headers=AUTH_HEADERS)

        assert resp.status_code == 502

    def test_network_error_returns_503(self, client, mock_auth_and_settings):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("api.routers.guild.httpx.AsyncClient", return_value=mock_ctx):
            resp = client.get("/guild/members/search?query=a", headers=AUTH_HEADERS)

        assert resp.status_code == 503

    def test_limit_defaults_to_25(self, client, mock_auth_and_settings):
        mock_ctx, mock_client = self._mock_discord_search([])
        with patch("api.routers.guild.httpx.AsyncClient", return_value=mock_ctx):
            client.get("/guild/members/search?query=a", headers=AUTH_HEADERS)

        call_kwargs = mock_client.get.call_args[1]
        assert call_kwargs["params"]["limit"] == 25

    def test_limit_max_25(self, client, mock_auth_and_settings):
        resp = client.get(
            "/guild/members/search?query=a&limit=26", headers=AUTH_HEADERS
        )
        assert resp.status_code == 422

    def test_limit_min_1(self, client, mock_auth_and_settings):
        resp = client.get("/guild/members/search?query=a&limit=0", headers=AUTH_HEADERS)
        assert resp.status_code == 422

    def test_empty_query_returns_422(self, client, mock_auth_and_settings):
        resp = client.get("/guild/members/search?query=", headers=AUTH_HEADERS)
        assert resp.status_code == 422

    def test_returns_empty_list_when_no_matches(self, client, mock_auth_and_settings):
        mock_ctx, _ = self._mock_discord_search([])
        with patch("api.routers.guild.httpx.AsyncClient", return_value=mock_ctx):
            resp = client.get("/guild/members/search?query=zzz", headers=AUTH_HEADERS)

        assert resp.status_code == 200
        assert resp.json() == []


# ══════════════════════════════════════════════════════════════════════════════
# Schemas
# ══════════════════════════════════════════════════════════════════════════════


class TestGuildMemberDisplayName:
    def test_nick_takes_priority(self):
        from api.schemas import GuildMember

        m = GuildMember(id="1", username="user", global_name="Global", nick="Nick")
        assert m.display_name == "Nick"

    def test_global_name_fallback(self):
        from api.schemas import GuildMember

        m = GuildMember(id="1", username="user", global_name="Global", nick=None)
        assert m.display_name == "Global"

    def test_username_fallback(self):
        from api.schemas import GuildMember

        m = GuildMember(id="1", username="user", global_name=None, nick=None)
        assert m.display_name == "user"
