"""
Tests for calendar_sync.py stub.

These tests verify the no-op behaviour of the stub implementation.
When the full MS Graph integration is implemented, these tests should be
expanded to cover HTTP interactions (mocked via respx).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from calendar_sync import SYNC_FAILED, CalendarClient, make_calendar_client


def _settings_no_calendar():
    s = MagicMock()
    s.calendar_sync_enabled = False
    s.ms_tenant_id = None
    s.ms_client_id = None
    s.ms_client_secret = None
    s.ms_calendar_id = None
    return s


def _settings_with_calendar():
    s = MagicMock()
    s.calendar_sync_enabled = True
    s.ms_tenant_id = "tenant"
    s.ms_client_id = "client"
    s.ms_client_secret = "secret"
    s.ms_calendar_id = "cal@example.com"
    return s


def test_make_calendar_client_returns_none_when_disabled():
    client = make_calendar_client(_settings_no_calendar())
    assert client is None


def test_make_calendar_client_returns_client_when_enabled():
    client = make_calendar_client(_settings_with_calendar())
    assert isinstance(client, CalendarClient)


async def test_create_event_stub_returns_none():
    client = CalendarClient(_settings_with_calendar())
    result = await client.create_event(
        title="Test",
        description=None,
        due_date=datetime.now(timezone.utc) + timedelta(days=5),
    )
    assert result is None


async def test_update_event_stub_returns_false():
    client = CalendarClient(_settings_with_calendar())
    result = await client.update_event("some-event-id", title="New Title")
    assert result is False


async def test_delete_event_stub_returns_false():
    client = CalendarClient(_settings_with_calendar())
    result = await client.delete_event("some-event-id")
    assert result is False


async def test_close_stub_does_not_raise():
    client = CalendarClient(_settings_with_calendar())
    await client.close()  # should not raise


def test_sync_failed_sentinel_value():
    assert SYNC_FAILED == "SYNC_FAILED"
