"""SolarEdge Warmwater API client with OAuth2 PKCE authentication."""

from __future__ import annotations

import base64
import hashlib
import logging
import secrets
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlencode, urlparse

import aiohttp

from .const import (
    API_TIMEOUT,
    BASE_URL,
    DEVICE_ACTIVATION_PATH,
    DEVICE_INFO_PATH,
    DEVICE_STATE_PATH,
    DEVICES_LIST_INFO_PATH,
    DEVICES_LIST_STATE_PATH,
    HTTP_STATUS_BAD_REQUEST,
    HTTP_STATUS_NO_CONTENT,
    HTTP_STATUS_OK,
    HTTP_STATUS_UNAUTHORIZED,
    LOGIN_BASE_URL,
    MFE_AUTH_CALLBACK_PATH,
    SOLAREDGE_ONE_CLIENT_ID,
    TOKEN_PATH,
)

_LOGGER = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

MFE_AUTH_CALLBACK = f"{BASE_URL}{MFE_AUTH_CALLBACK_PATH}"
TOKEN_URL = f"{LOGIN_BASE_URL}{TOKEN_PATH}"


class AuthenticationError(Exception):
    """Raised when authentication fails."""


class ApiError(Exception):
    """Raised when an API call fails."""


class _FormParser(HTMLParser):
    """Extract first form action and all input name/value pairs from HTML."""

    def __init__(self) -> None:
        super().__init__()
        self.form_action: str | None = None
        self.form_method: str = "GET"
        self.inputs: dict[str, str] = {}
        self._in_form = False
        self._form_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_d = dict(attrs)
        if tag == "form":
            if not self._in_form:
                self.form_action = attrs_d.get("action", "")
                self.form_method = (attrs_d.get("method") or "GET").upper()
            self._in_form = True
            self._form_depth += 1
        if self._in_form and tag == "input":
            name = attrs_d.get("name")
            if name:
                self.inputs[name] = attrs_d.get("value") or ""

    def handle_endtag(self, tag: str) -> None:
        if tag == "form" and self._in_form:
            self._form_depth -= 1
            if self._form_depth <= 0:
                self._in_form = False


def _parse_login_form(html: str) -> tuple[str | None, str, dict[str, str]]:
    """Return form_action, form_method, dict of input name->value."""
    parser = _FormParser()
    try:
        parser.feed(html)
    except Exception:  # noqa: BLE001
        _LOGGER.debug("HTML form parse error (non-fatal)", exc_info=True)
    return parser.form_action, parser.form_method, parser.inputs


def _pkce_verifier_and_challenge() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) for S256 PKCE."""
    verifier = (
        base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")
    )
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


async def _oauth_get_login_page(
    session: aiohttp.ClientSession,
    login_params: dict,
    timeout: aiohttp.ClientTimeout,
) -> tuple[str, str]:
    """
    GET the login page. Returns (html, final_url).

    Raises if not on LOGIN_BASE_URL.
    """
    login_url = f"{LOGIN_BASE_URL}/login?{urlencode(login_params)}"
    async with session.get(login_url, timeout=timeout) as resp:
        _LOGGER.debug("GET login page -> %s", resp.status)
        html = await resp.text()
        final_url = str(resp.url)
    if not final_url.startswith(LOGIN_BASE_URL):
        msg = f"Login page redirected to unexpected URL: {final_url}"
        raise AuthenticationError(msg)
    return html, final_url


async def _oauth_post_credentials(
    session: aiohttp.ClientSession,
    login_params: dict,
    post_body: dict,
    login_page_url: str,
    timeout: aiohttp.ClientTimeout,
) -> str:
    """POST credentials and follow redirects (including 204 + Location). Returns final URL."""  # noqa: E501
    post_url = f"{LOGIN_BASE_URL}/login?{urlencode(login_params)}"
    post_headers = {
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        "Accept": "*/*",
        "Origin": LOGIN_BASE_URL,
        "Referer": login_page_url,
    }
    async with session.post(
        post_url,
        data=post_body,
        headers=post_headers,
        timeout=timeout,
        allow_redirects=True,
    ) as resp:
        _LOGGER.debug("POST login -> %s, URL: %s", resp.status, resp.url)
        final_url = str(resp.url)

        # Handle 204 with Location header (SolarEdge specific)
        if resp.status == HTTP_STATUS_NO_CONTENT and "Location" in resp.headers:
            callback_url = resp.headers["Location"]
            _LOGGER.debug("204 response, following Location: %s", callback_url)
            async with session.get(
                callback_url,
                timeout=timeout,
                allow_redirects=True,
            ) as resp2:
                final_url = str(resp2.url)

    return final_url


def _oauth_extract_code(final_url: str) -> str:
    """Extract authorization code from OAuth callback URL."""
    if MFE_AUTH_CALLBACK not in final_url:
        _LOGGER.debug("Did not reach callback (final URL: %s)", final_url)
        msg = "OAuth callback not reached - invalid credentials or network error"
        raise AuthenticationError(msg)
    parsed = urlparse(final_url)
    q = parse_qs(parsed.query)
    code = (q.get("code") or [None])[0]
    if not code:
        msg = "OAuth callback URL missing authorization code"
        raise AuthenticationError(msg)
    return code


async def _oauth_exchange_code(
    code: str,
    code_verifier: str,
    timeout: aiohttp.ClientTimeout,
) -> str:
    """Exchange authorization code for access token."""
    token_data = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": SOLAREDGE_ONE_CLIENT_ID,
        "redirect_uri": MFE_AUTH_CALLBACK,
        "code_verifier": code_verifier,
    }
    token_headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "*/*",
        "Origin": BASE_URL,
        "Referer": f"{BASE_URL}/",
        "User-Agent": USER_AGENT,
    }

    async with (
        aiohttp.ClientSession() as token_session,
        token_session.post(
            TOKEN_URL,
            data=token_data,
            headers=token_headers,
            timeout=timeout,
        ) as resp,
    ):
            _LOGGER.debug("POST oauth2/token -> %s", resp.status)
            if resp.status != HTTP_STATUS_OK:
                text = await resp.text()
                msg = f"Token exchange failed with status {resp.status}: {text}"
                raise AuthenticationError(msg)
            tok = await resp.json()

    access_token = tok.get("access_token")
    if not access_token:
        msg = "Token response missing access_token"
        raise AuthenticationError(msg)
    return access_token


async def _perform_oauth_pkce_login(username: str, password: str) -> str:
    """
    Perform full OAuth2 PKCE login flow.

    Steps: GET login page → POST credentials → extract code → exchange for token.
    Returns access_token.
    """
    code_verifier, code_challenge = _pkce_verifier_and_challenge()
    login_params = {
        "lang": "en",
        "response_type": "code",
        "client_id": SOLAREDGE_ONE_CLIENT_ID,
        "scope": "email openid",
        "redirect_uri": MFE_AUTH_CALLBACK,
        "code_challenge_method": "S256",
        "code_challenge": code_challenge,
    }
    timeout = aiohttp.ClientTimeout(total=API_TIMEOUT)

    # Use a dedicated session so cookies from the GET are sent with the POST
    async with aiohttp.ClientSession(
        cookie_jar=aiohttp.CookieJar(),
        headers={"User-Agent": USER_AGENT},
    ) as login_session:
        html, login_page_url = await _oauth_get_login_page(
            login_session, login_params, timeout
        )

        _, _, form_inputs = _parse_login_form(html)
        post_body = {
            k: v
            for k, v in form_inputs.items()
            if k not in ("username", "password", "email")
        }
        post_body["username"] = username
        post_body["password"] = password

        final_url = await _oauth_post_credentials(
            login_session, login_params, post_body, login_page_url, timeout
        )

    code = _oauth_extract_code(final_url)
    access_token = await _oauth_exchange_code(code, code_verifier, timeout)

    _LOGGER.debug("OAuth PKCE login successful")
    return access_token


class SolarEdgeWarmwaterAPI:
    """Async API client for SolarEdge hot water controller."""

    def __init__(
        self, username: str, password: str, session: aiohttp.ClientSession
    ) -> None:
        """Initialize the API client with credentials and an aiohttp session."""
        self._username = username
        self._password = password
        self._session = session
        self._access_token: str | None = None

    async def authenticate(self) -> bool:
        """Perform OAuth2 PKCE login. Returns True on success, raises on failure."""
        self._access_token = await _perform_oauth_pkce_login(
            self._username, self._password
        )
        return True

    def _request_headers(self) -> dict[str, str]:
        """Build headers for authenticated API requests."""
        if not self._access_token:
            msg = "Not authenticated"
            raise AuthenticationError(msg)
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._access_token}",
            "User-Agent": USER_AGENT,
            "Origin": BASE_URL,
            "Referer": f"{BASE_URL}/",
        }

    async def _request(
        self,
        method: str,
        path: str,
        json_data: dict | None = None,
        *,
        retry_auth: bool = True,
    ) -> dict:
        """Make an authenticated API request with automatic re-auth on 401."""
        url = f"{BASE_URL}{path}"
        timeout = aiohttp.ClientTimeout(total=API_TIMEOUT)

        try:
            headers = self._request_headers()
        except AuthenticationError:
            if not retry_auth:
                raise
            await self.authenticate()
            headers = self._request_headers()

        kwargs: dict = {"headers": headers, "timeout": timeout}
        if json_data is not None:
            kwargs["json"] = json_data

        async with self._session.request(method, url, **kwargs) as resp:
            _LOGGER.debug("%s %s -> %s", method, path, resp.status)

            if resp.status == HTTP_STATUS_UNAUTHORIZED and retry_auth:
                _LOGGER.debug("401 on %s %s, re-authenticating", method, path)
                self._access_token = None
                await self.authenticate()
                return await self._request(method, path, json_data, retry_auth=False)

            if resp.status == HTTP_STATUS_UNAUTHORIZED:
                self._access_token = None
                msg = f"Authentication failed for {method} {path}"
                raise AuthenticationError(msg)

            if resp.status >= HTTP_STATUS_BAD_REQUEST:
                text = await resp.text()
                msg = f"API request failed: {method} {path} -> {resp.status}: {text}"
                raise ApiError(msg)

            return await resp.json()

    # ── Data endpoints ──────────────────────────────────────────────

    async def get_devices_info(self, site_id: str) -> dict:
        """Get device list with info for a site."""
        path = DEVICES_LIST_INFO_PATH.format(site_id=site_id)
        return await self._request("GET", path)

    async def get_devices_state(self, site_id: str) -> dict:
        """Get device list with state for a site."""
        path = DEVICES_LIST_STATE_PATH.format(site_id=site_id)
        return await self._request("GET", path)

    async def get_device_info(self, site_id: str, device_id: str) -> dict:
        """Get detailed info for a specific device."""
        path = DEVICE_INFO_PATH.format(site_id=site_id, device_id=device_id)
        return await self._request("GET", path)

    async def get_device_state(self, site_id: str, device_id: str) -> dict:
        """Get current state for a specific device."""
        path = DEVICE_STATE_PATH.format(site_id=site_id, device_id=device_id)
        return await self._request("GET", path)

    # ── Control endpoint ────────────────────────────────────────────

    async def set_activation_state(
        self,
        site_id: str,
        device_id: str,
        mode: str,
        level: int | None = None,
        duration: int | None = None,
    ) -> dict:
        """Set the activation state of a device."""
        path = DEVICE_ACTIVATION_PATH.format(site_id=site_id, device_id=device_id)
        payload = {
            "mode": mode,
            "level": level,
            "duration": duration,
        }
        return await self._request("PUT", path, json_data=payload)
