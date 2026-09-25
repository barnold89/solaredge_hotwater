"""Tests that tell a broken SolarEdge login from rejected credentials."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from custom_components.solaredge_hotwater.api import (
    MFE_AUTH_CALLBACK,
    AuthenticationError,
    LoginUnavailableError,
    SolarEdgeWarmwaterAPI,
    _oauth_exchange_code,
    _oauth_extract_code,
    _oauth_get_login_page,
    _oauth_post_credentials,
)
from custom_components.solaredge_hotwater.const import BASE_URL, LOGIN_BASE_URL

TIMEOUT = aiohttp.ClientTimeout(total=1)
LOGIN_FORM = (
    '<form action="/login" method="POST">'
    '<input name="csrf" value="abc"><input name="username" value="">'
    "</form>"
)


def _response(
    status: int, *, text: str = "", url: str = LOGIN_BASE_URL, headers: Any = None
) -> MagicMock:
    """Build a mocked aiohttp response."""
    response = MagicMock()
    response.status = status
    response.text = AsyncMock(return_value=text)
    response.url = url
    response.headers = headers or {}
    return response


def _get_page(response: MagicMock) -> tuple[dict[str, str], str]:
    """Fetch the login page from a session answering with that response."""
    session = MagicMock()
    session.get.return_value.__aenter__.return_value = response
    return asyncio.run(_oauth_get_login_page(session, {"lang": "en"}, TIMEOUT))


@pytest.mark.parametrize("status", [429, 500, 503])
def test_login_page_outage_is_unavailable(status: int) -> None:
    """Throttling and server errors on the login page are not auth failures."""
    with pytest.raises(LoginUnavailableError, match=str(status)):
        _get_page(_response(status, text=LOGIN_FORM))


def test_login_page_without_form_is_unavailable() -> None:
    """A page that is not a login form means the login is unavailable."""
    with pytest.raises(LoginUnavailableError, match="form"):
        _get_page(_response(200, text="<html>Service unavailable</html>"))


def test_login_page_redirected_off_host_is_unavailable() -> None:
    """Being sent away from the login host means the login is unavailable."""
    with pytest.raises(LoginUnavailableError, match="unexpected URL"):
        _get_page(_response(200, text=LOGIN_FORM, url=f"{BASE_URL}/maintenance"))


def test_login_page_returns_form_inputs() -> None:
    """Hand the hidden form fields to the credential POST."""
    inputs, final_url = _get_page(
        _response(200, text=LOGIN_FORM, url=f"{LOGIN_BASE_URL}/login?lang=en")
    )

    assert inputs == {"csrf": "abc", "username": ""}
    assert final_url == f"{LOGIN_BASE_URL}/login?lang=en"


def _post_credentials(session: MagicMock) -> str:
    """POST the credentials with that session."""
    return asyncio.run(
        _oauth_post_credentials(
            session, {"lang": "en"}, {"username": "u"}, LOGIN_BASE_URL, TIMEOUT
        )
    )


@pytest.mark.parametrize("status", [429, 502])
def test_credential_post_outage_is_unavailable(status: int) -> None:
    """A server error on the credential POST is not a rejected password."""
    session = MagicMock()
    session.post.return_value.__aenter__.return_value = _response(status)

    with pytest.raises(LoginUnavailableError, match=str(status)):
        _post_credentials(session)


def test_callback_hop_outage_is_unavailable() -> None:
    """A server error while following the 204 Location header is an outage."""
    session = MagicMock()
    session.post.return_value.__aenter__.return_value = _response(
        204, headers={"Location": f"{MFE_AUTH_CALLBACK}?code=abc"}
    )
    session.get.return_value.__aenter__.return_value = _response(503)

    with pytest.raises(LoginUnavailableError, match="503"):
        _post_credentials(session)


def test_login_page_served_again_means_rejected() -> None:
    """Landing back on the login host is how SolarEdge rejects credentials."""
    with pytest.raises(AuthenticationError, match="rejected"):
        _oauth_extract_code(f"{LOGIN_BASE_URL}/login?lang=en")


def test_landing_elsewhere_is_unavailable() -> None:
    """Ending up on another host says nothing about the credentials."""
    with pytest.raises(LoginUnavailableError, match="login ended on"):
        _oauth_extract_code(f"{BASE_URL}/maintenance")


def test_callback_without_code_is_unavailable() -> None:
    """A callback without a code is a broken flow, not a wrong password."""
    with pytest.raises(LoginUnavailableError, match="missing authorization code"):
        _oauth_extract_code(f"{MFE_AUTH_CALLBACK}?state=x")


def test_callback_with_code_returns_it() -> None:
    """Return the authorization code from the callback URL."""
    assert _oauth_extract_code(f"{MFE_AUTH_CALLBACK}?code=abc123") == "abc123"


def _exchange_code(response: MagicMock) -> str:
    """Exchange the code against a token endpoint answering with that response."""
    token_session = MagicMock()
    token_session.post.return_value.__aenter__.return_value = response
    with patch("custom_components.solaredge_hotwater.api.aiohttp.ClientSession") as cls:
        cls.return_value.__aenter__.return_value = token_session
        return asyncio.run(_oauth_exchange_code("code", "verifier", TIMEOUT))


def test_token_exchange_failure_is_unavailable() -> None:
    """After the code, the credentials were accepted: never blame them again."""
    response = _response(500, text="boom")

    with pytest.raises(LoginUnavailableError, match="500"):
        _exchange_code(response)


def test_token_response_without_token_is_unavailable() -> None:
    """A token response without a token is a protocol problem."""
    response = _response(200)
    response.json = AsyncMock(return_value={"token_type": "Bearer"})

    with pytest.raises(LoginUnavailableError, match="missing access_token"):
        _exchange_code(response)


def test_token_exchange_returns_access_token() -> None:
    """Return the access token from a good response."""
    response = _response(200)
    response.json = AsyncMock(return_value={"access_token": "token"})

    assert _exchange_code(response) == "token"


def test_authenticate_runs_the_whole_flow_and_reports_rejection() -> None:
    """Drive authenticate() end to end: form, credential POST, login page again."""
    login_session = MagicMock()
    login_session.get.return_value.__aenter__.return_value = _response(
        200, text=LOGIN_FORM, url=f"{LOGIN_BASE_URL}/login?lang=en"
    )
    login_session.post.return_value.__aenter__.return_value = _response(
        200, url=f"{LOGIN_BASE_URL}/login?lang=en"
    )

    with patch("custom_components.solaredge_hotwater.api.aiohttp.ClientSession") as cls:
        cls.return_value.__aenter__.return_value = login_session
        api = SolarEdgeWarmwaterAPI("user", "password", MagicMock())

        with pytest.raises(AuthenticationError, match="rejected"):
            asyncio.run(api.authenticate())

    post_body = login_session.post.call_args.kwargs["data"]
    assert post_body["csrf"] == "abc"
    assert post_body["username"] == "user"
