"""SolarEdge Warmwater API client with OAuth2 PKCE authentication."""

from __future__ import annotations

import asyncio
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
    HTTP_STATUS_SERVER_ERROR,
    HTTP_STATUS_TOO_MANY_REQUESTS,
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


class LoginUnavailableError(ApiError):
    """
    Raised when the login flow itself does not work.

    Throttling, server errors, a page that is not a login form, or a failed
    token exchange: the stored credentials may well be correct, so callers
    retry like after any other communication error instead of asking the user
    to authenticate again.
    """


def _raise_if_login_unavailable(step: str, status: int) -> None:
    """Treat throttling and server errors during login as a temporary outage."""
    if status == HTTP_STATUS_TOO_MANY_REQUESTS or status >= HTTP_STATUS_SERVER_ERROR:
        msg = f"SolarEdge login unavailable: {step} returned {status}"
        raise LoginUnavailableError(msg)


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
    except Exception:
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
) -> tuple[dict[str, str], str]:
    """
    GET the login page. Returns (form_inputs, final_url).

    Anything that is not a login form on LOGIN_BASE_URL means the login is
    unavailable, not that the credentials are wrong.
    """
    login_url = f"{LOGIN_BASE_URL}/login?{urlencode(login_params)}"
    async with session.get(login_url, timeout=timeout) as resp:
        _LOGGER.debug("GET login page -> %s", resp.status)
        _raise_if_login_unavailable("login page", resp.status)
        html = await resp.text()
        final_url = str(resp.url)
    if not final_url.startswith(LOGIN_BASE_URL):
        msg = f"Login page redirected to unexpected URL: {final_url}"
        raise LoginUnavailableError(msg)
    form_action, _, form_inputs = _parse_login_form(html)
    if form_action is None:
        msg = "Login page did not contain a form"
        raise LoginUnavailableError(msg)
    return form_inputs, final_url


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
        _raise_if_login_unavailable("credential POST", resp.status)
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
                _raise_if_login_unavailable("auth callback", resp2.status)
                final_url = str(resp2.url)

    return final_url


def _oauth_extract_code(final_url: str) -> str:
    """
    Extract the authorization code from the OAuth callback URL.

    Ending up back on the login host is how SolarEdge rejects credentials: it
    simply serves the login page again. Ending up anywhere else means the login
    flow broke, which is not the user's problem to fix.
    """
    if MFE_AUTH_CALLBACK not in final_url:
        _LOGGER.debug("Did not reach callback (final URL: %s)", final_url)
        if final_url.startswith(LOGIN_BASE_URL):
            _LOGGER.warning(
                "SolarEdge served the login page again, credentials rejected"
            )
            msg = "Credentials rejected by SolarEdge"
            raise AuthenticationError(msg)
        msg = f"OAuth callback not reached, login ended on {urlparse(final_url).netloc}"
        raise LoginUnavailableError(msg)
    parsed = urlparse(final_url)
    q = parse_qs(parsed.query)
    code = (q.get("code") or [None])[0]
    if not code:
        msg = "OAuth callback URL missing authorization code"
        raise LoginUnavailableError(msg)
    return code


async def _oauth_exchange_code(
    code: str,
    code_verifier: str,
    timeout: aiohttp.ClientTimeout,
) -> tuple[str, str | None]:
    """Exchange authorization code for (access_token, refresh_token)."""
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
            raise LoginUnavailableError(msg)
        tok = await resp.json()

    access_token = tok.get("access_token")
    if not access_token:
        msg = "Token response missing access_token"
        raise LoginUnavailableError(msg)
    return access_token, tok.get("refresh_token")


async def _perform_oauth_pkce_login(
    username: str, password: str
) -> tuple[str, str | None]:
    """
    Perform full OAuth2 PKCE login flow.

    Steps: GET login page → POST credentials → extract code → exchange for token.
    Returns (access_token, refresh_token); the refresh token may be missing.
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
        form_inputs, login_page_url = await _oauth_get_login_page(
            login_session, login_params, timeout
        )

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
    tokens = await _oauth_exchange_code(code, code_verifier, timeout)

    _LOGGER.debug("OAuth PKCE login successful")
    return tokens


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
        # Kept in memory only: after a restart the integration logs in again
        self._refresh_token: str | None = None
        # Whether the access token came from a password login, not a refresh
        self._token_from_login = False
        # Serializes refresh and login, so parallel requests share one renewal
        self._token_lock = asyncio.Lock()

    async def authenticate(self) -> bool:
        """Perform OAuth2 PKCE login. Returns True on success, raises on failure."""
        async with self._token_lock:
            await self._login()
        return True

    async def _login(self) -> None:
        """Log in with the password. Callers hold the token lock."""
        self._access_token, self._refresh_token = await _perform_oauth_pkce_login(
            self._username, self._password
        )
        self._token_from_login = True

    async def _refresh(self) -> bool:
        """
        Renew the access token with the refresh token. Callers hold the token lock.

        The lifetime of the refresh token is unknown, so a failure is the normal
        way it ends: drop it and return False, the caller then logs in again.
        """
        token_data = {
            "grant_type": "refresh_token",
            "refresh_token": self._refresh_token,
            "client_id": SOLAREDGE_ONE_CLIENT_ID,
        }
        token_headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "*/*",
            "Origin": BASE_URL,
            "Referer": f"{BASE_URL}/",
            "User-Agent": USER_AGENT,
        }
        timeout = aiohttp.ClientTimeout(total=API_TIMEOUT)
        tok: dict | None = None
        try:
            async with self._session.post(
                TOKEN_URL, data=token_data, headers=token_headers, timeout=timeout
            ) as resp:
                _LOGGER.debug("POST oauth2/token (refresh) -> %s", resp.status)
                if resp.status == HTTP_STATUS_OK:
                    tok = await resp.json()
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            _LOGGER.debug("Token refresh failed: %s", type(err).__name__)

        access_token = tok.get("access_token") if isinstance(tok, dict) else None
        if not access_token:
            _LOGGER.debug("Token refresh unsuccessful, falling back to login")
            self._refresh_token = None
            return False

        self._access_token = access_token
        # SolarEdge does not rotate the refresh token; take a new one if it does
        self._refresh_token = tok.get("refresh_token") or self._refresh_token
        self._token_from_login = False
        _LOGGER.debug("Token refresh successful")
        return True

    async def _renew_token(
        self, stale_token: str | None, *, allow_refresh: bool = True
    ) -> tuple[str, bool]:
        """
        Replace a rejected access token. Returns (token, came from a login).

        A caller that waited on the lock reuses the token the other caller
        obtained instead of renewing again. Without allow_refresh, only a token
        from a login counts, because a refreshed one was just rejected.
        """
        async with self._token_lock:
            if (
                self._access_token
                and self._access_token != stale_token
                and (allow_refresh or self._token_from_login)
            ):
                return self._access_token, self._token_from_login
            if not allow_refresh:
                self._refresh_token = None
            if not (self._refresh_token and await self._refresh()):
                await self._login()
            # Both paths set the access token or raise
            return self._access_token or "", self._token_from_login

    def _request_headers(self, token: str) -> dict[str, str]:
        """Build headers for authenticated API requests."""
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": USER_AGENT,
            "Origin": BASE_URL,
            "Referer": f"{BASE_URL}/",
        }

    async def _send(
        self, method: str, path: str, json_data: dict | None, token: str
    ) -> dict | None:
        """Send one request with that token. Returns None on 401."""
        url = f"{BASE_URL}{path}"
        timeout = aiohttp.ClientTimeout(total=API_TIMEOUT)
        kwargs: dict = {"headers": self._request_headers(token), "timeout": timeout}
        if json_data is not None:
            kwargs["json"] = json_data

        async with self._session.request(method, url, **kwargs) as resp:
            _LOGGER.debug("%s %s -> %s", method, path, resp.status)

            if resp.status == HTTP_STATUS_UNAUTHORIZED:
                return None

            if resp.status >= HTTP_STATUS_BAD_REQUEST:
                text = await resp.text()
                msg = f"API request failed: {method} {path} -> {resp.status}: {text}"
                raise ApiError(msg)

            return await resp.json()

    async def _request(
        self, method: str, path: str, json_data: dict | None = None
    ) -> dict:
        """
        Make an authenticated API request, renewing the token on 401.

        On 401 the token is refreshed, or replaced by a login when that fails,
        and the request repeated once. A 401 on a refreshed token says nothing
        about the password, so it gets one more try with a fresh login. Only a
        401 that survives a fresh login raises AuthenticationError.
        """
        token = self._access_token
        if not token:
            token, _ = await self._renew_token(None)
        data = await self._send(method, path, json_data, token)
        if data is not None:
            return data

        _LOGGER.debug("401 on %s %s, renewing token", method, path)
        token, from_login = await self._renew_token(token)
        data = await self._send(method, path, json_data, token)
        if data is None and not from_login:
            _LOGGER.debug("401 on %s %s after token refresh, logging in", method, path)
            token, _ = await self._renew_token(token, allow_refresh=False)
            data = await self._send(method, path, json_data, token)
        if data is not None:
            return data

        if self._access_token == token:
            self._access_token = None
        msg = f"Authentication failed for {method} {path}"
        raise AuthenticationError(msg)

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
