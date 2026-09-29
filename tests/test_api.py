"""Tests for the API client's HTTP error handling and token renewal."""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from custom_components.solaredge_hotwater.api import (
    TOKEN_URL,
    ApiError,
    AuthenticationError,
    LoginUnavailableError,
    SolarEdgeWarmwaterAPI,
)
from custom_components.solaredge_hotwater.const import (
    BASE_URL,
    SOLAREDGE_ONE_CLIENT_ID,
)


def _api(status: int) -> SolarEdgeWarmwaterAPI:
    """Return a logged-in API client whose session answers with the given status."""
    session = MagicMock()
    response = session.request.return_value.__aenter__.return_value
    response.status = status
    response.text = AsyncMock(return_value="Internal Server Error")
    api = SolarEdgeWarmwaterAPI("user", "password", session)
    api._access_token = "token"  # noqa: S105
    return api


async def test_http_500_on_fetch_raises_api_error() -> None:
    """Turn HTTP 500 on /state into ApiError."""
    with pytest.raises(ApiError, match="500"):
        await _api(500).get_device_state("site", "device")


async def test_http_500_on_switch_raises_api_error() -> None:
    """Turn HTTP 500 on the activation PUT into ApiError."""
    with pytest.raises(ApiError, match="500"):
        await _api(500).set_activation_state("site", "device", "AUTO")


# ── Token renewal on 401 ────────────────────────────────────────────

OLD_TOKEN = "old-access-token"  # noqa: S105
REFRESHED_TOKEN = "refreshed-access-token"  # noqa: S105
LOGIN_TOKEN = "login-access-token"  # noqa: S105
REFRESH_TOKEN = "first-refresh-token"  # noqa: S105
LOGIN_REFRESH_TOKEN = "login-refresh-token"  # noqa: S105
ALL_TOKENS = (
    OLD_TOKEN,
    REFRESHED_TOKEN,
    LOGIN_TOKEN,
    REFRESH_TOKEN,
    LOGIN_REFRESH_TOKEN,
    "id-token",
)
LOGIN = "custom_components.solaredge_hotwater.api._perform_oauth_pkce_login"


def _context(response: MagicMock) -> MagicMock:
    """Wrap a response like `async with session.request(...)` does."""

    async def enter(*_args: Any) -> MagicMock:
        # Yield like real I/O, so parallel requests interleave
        await asyncio.sleep(0)
        return response

    context = MagicMock()
    context.__aenter__.side_effect = enter
    return context


def _token_response(status: int, body: dict[str, Any] | None = None) -> MagicMock:
    """Build the token endpoint's answer to the refresh grant."""
    response = MagicMock()
    response.status = status
    response.json = AsyncMock(return_value=body or {})
    return response


# Recorded shape of a refresh response: no new refresh token
REFRESHED = _token_response(
    200,
    {
        "access_token": REFRESHED_TOKEN,
        "expires_in": 86400,
        "id_token": "id-token",
        "token_type": "Bearer",
    },
)


def _renewing_api(
    accepted: set[str], refresh: MagicMock | Exception
) -> tuple[SolarEdgeWarmwaterAPI, MagicMock]:
    """
    Return a client holding an expired token, and its session.

    The API answers 200 for accepted bearer tokens and 401 otherwise; the token
    endpoint answers the refresh with the given response or raises the error.
    """
    session = MagicMock()

    def request(_method: str, _url: str, **kwargs: Any) -> MagicMock:
        token = kwargs["headers"]["Authorization"].removeprefix("Bearer ")
        response = MagicMock()
        response.status = 200 if token in accepted else 401
        response.json = AsyncMock(return_value={"token": token})
        return _context(response)

    session.request.side_effect = request
    if isinstance(refresh, Exception):
        session.post.side_effect = refresh
    else:
        session.post.return_value = _context(refresh)

    api = SolarEdgeWarmwaterAPI("user", "password", session)
    api._access_token = OLD_TOKEN
    api._refresh_token = REFRESH_TOKEN
    return api, session


async def test_401_is_answered_by_refresh_without_login() -> None:
    """Refresh the token on 401 and repeat the request, without a password login."""
    api, session = _renewing_api({REFRESHED_TOKEN}, REFRESHED)

    with patch(LOGIN, AsyncMock()) as login:
        data = await api.get_device_state("site", "device")

    assert data == {"token": REFRESHED_TOKEN}
    login.assert_not_awaited()
    assert session.request.call_count == 2
    assert session.post.call_args.args == (TOKEN_URL,)
    assert session.post.call_args.kwargs["data"] == {
        "grant_type": "refresh_token",
        "refresh_token": REFRESH_TOKEN,
        "client_id": SOLAREDGE_ONE_CLIENT_ID,
    }
    assert session.post.call_args.kwargs["headers"]["Origin"] == BASE_URL


async def test_refresh_without_new_refresh_token_keeps_the_old_one() -> None:
    """SolarEdge does not rotate the refresh token, so it stays usable."""
    api, _ = _renewing_api({REFRESHED_TOKEN}, REFRESHED)

    await api.get_device_state("site", "device")

    assert api._refresh_token == REFRESH_TOKEN


async def test_refresh_with_new_refresh_token_takes_it() -> None:
    """Take a rotated refresh token should SolarEdge start sending one."""
    rotated = _token_response(
        200, {"access_token": REFRESHED_TOKEN, "refresh_token": "rotated"}
    )
    api, _ = _renewing_api({REFRESHED_TOKEN}, rotated)

    await api.get_device_state("site", "device")

    assert api._refresh_token == "rotated"  # noqa: S105


@pytest.mark.parametrize(
    "refresh",
    [
        _token_response(400),
        _token_response(401),
        _token_response(429),
        _token_response(500),
        _token_response(503),
        _token_response(200, {"token_type": "Bearer"}),
        aiohttp.ClientConnectionError("connection reset"),
        TimeoutError(),
    ],
    ids=["400", "401", "429", "500", "503", "no-access-token", "network", "timeout"],
)
async def test_failed_refresh_falls_back_to_login(
    refresh: MagicMock | Exception,
) -> None:
    """Any failed refresh drops the refresh token and logs in with the password."""
    api, _ = _renewing_api({LOGIN_TOKEN}, refresh)

    with patch(
        LOGIN, AsyncMock(return_value=(LOGIN_TOKEN, LOGIN_REFRESH_TOKEN))
    ) as login:
        data = await api.get_device_state("site", "device")

    assert data == {"token": LOGIN_TOKEN}
    login.assert_awaited_once()
    assert api._refresh_token == LOGIN_REFRESH_TOKEN


async def test_login_outage_after_failed_refresh_is_not_an_auth_error() -> None:
    """If the login is down as well, report the outage, not rejected credentials."""
    api, _ = _renewing_api(set(), _token_response(503))

    with (
        patch(LOGIN, AsyncMock(side_effect=LoginUnavailableError("down"))),
        pytest.raises(LoginUnavailableError),
    ):
        await api.get_device_state("site", "device")


async def test_401_after_refresh_drops_refresh_token_and_logs_in() -> None:
    """A refreshed token that is rejected too gets one more try with a login."""
    api, session = _renewing_api({LOGIN_TOKEN}, REFRESHED)

    with patch(LOGIN, AsyncMock(return_value=(LOGIN_TOKEN, None))) as login:
        data = await api.get_device_state("site", "device")

    assert data == {"token": LOGIN_TOKEN}
    login.assert_awaited_once()
    assert session.post.call_count == 1
    assert api._refresh_token is None


async def test_401_surviving_login_after_refresh_raises_auth_error() -> None:
    """Only a 401 that survives a fresh login leads to reauthentication."""
    api, session = _renewing_api(set(), REFRESHED)

    with (
        patch(
            LOGIN, AsyncMock(return_value=(LOGIN_TOKEN, LOGIN_REFRESH_TOKEN))
        ) as login,
        pytest.raises(AuthenticationError),
    ):
        await api.get_device_state("site", "device")

    login.assert_awaited_once()
    assert session.request.call_count == 3
    assert api._access_token is None


async def test_401_surviving_login_without_refresh_token_raises_auth_error() -> None:
    """Without a refresh token, 401 → login → 401 raises like before."""
    api, session = _renewing_api(set(), REFRESHED)
    api._refresh_token = None

    with (
        patch(LOGIN, AsyncMock(return_value=(LOGIN_TOKEN, None))) as login,
        pytest.raises(AuthenticationError),
    ):
        await api.get_device_state("site", "device")

    login.assert_awaited_once()
    session.post.assert_not_called()
    assert session.request.call_count == 2


async def test_parallel_requests_share_one_refresh() -> None:
    """A switch command parallel to a poll reuses the token the poll renewed."""
    api, session = _renewing_api({REFRESHED_TOKEN}, REFRESHED)

    with patch(LOGIN, AsyncMock()) as login:
        results = await asyncio.gather(
            api.get_device_state("site", "device"),
            api.set_activation_state("site", "device", "AUTO"),
        )

    assert results == [{"token": REFRESHED_TOKEN}] * 2
    # Both got 401 on the old token, only one refreshed it
    assert session.request.call_count == 4
    assert session.post.call_count == 1
    login.assert_not_awaited()


async def test_parallel_requests_share_one_login() -> None:
    """Two requests that both get 401 without a refresh token log in only once."""
    api, session = _renewing_api({LOGIN_TOKEN}, REFRESHED)
    api._refresh_token = None

    with patch(LOGIN, AsyncMock(return_value=(LOGIN_TOKEN, None))) as login:
        await asyncio.gather(
            api.get_device_state("site", "device"),
            api.get_device_info("site", "device"),
        )

    assert session.request.call_count == 4
    login.assert_awaited_once()


async def test_token_values_never_reach_the_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Refresh, failed refresh and login log no token value, even at DEBUG."""
    caplog.set_level(logging.DEBUG, logger="custom_components.solaredge_hotwater")
    api, _ = _renewing_api({REFRESHED_TOKEN}, REFRESHED)
    await api.get_device_state("site", "device")

    api, _ = _renewing_api({LOGIN_TOKEN}, _token_response(400))
    with patch(LOGIN, AsyncMock(return_value=(LOGIN_TOKEN, LOGIN_REFRESH_TOKEN))):
        await api.get_device_state("site", "device")

    assert "refresh" in caplog.text.lower()
    for token in ALL_TOKENS:
        assert token not in caplog.text
