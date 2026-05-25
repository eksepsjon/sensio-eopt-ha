"""
Authentication against unity.eopthome.no.

Flow:
  1. GET Portal login page to harvest VIEWSTATE tokens
  2. POST credentials to Portal login form
  3. Portal sets a session cookie and redirects; we follow until we find
     an OAuth2 authorization code in a redirect URL
  4. POST the code to /api/v1/tokens/oauth/delegation to get an access_token
  5. Store credentials in the system keyring

The client_id / client_secret for the delegation endpoint are not shipped
in the SDK binary but CAN be obtained by capturing live traffic (mitmproxy).
Once known, set them via `sensio login --client-id ... --client-secret ...`
or the environment variables SENSIO_CLIENT_ID / SENSIO_CLIENT_SECRET.
"""

from __future__ import annotations

import os
import re
import urllib.parse
from pathlib import Path
from typing import Optional

import httpx
import keyring

SERVICE = "sensio-control"
KEY_ACCESS_TOKEN = "access_token"
KEY_BASE_URL = "base_url"

DEFAULT_BASE_URL = "https://unity.eopthome.no/api"
PORTAL_LOGIN_URL = "https://unity.eopthome.no/Portal/Account/Login.aspx"
DELEGATION_URL = "/v1/tokens/oauth/delegation"


# ---------------------------------------------------------------------------
# Keyring helpers
# ---------------------------------------------------------------------------

def save_token(token: str, base_url: str = DEFAULT_BASE_URL) -> None:
    keyring.set_password(SERVICE, KEY_ACCESS_TOKEN, token)
    keyring.set_password(SERVICE, KEY_BASE_URL, base_url)


def load_token() -> Optional[str]:
    return keyring.get_password(SERVICE, KEY_ACCESS_TOKEN)


def load_base_url() -> str:
    return keyring.get_password(SERVICE, KEY_BASE_URL) or DEFAULT_BASE_URL


def clear_token() -> None:
    try:
        keyring.delete_password(SERVICE, KEY_ACCESS_TOKEN)
    except keyring.errors.PasswordDeleteError:
        pass
    try:
        keyring.delete_password(SERVICE, KEY_BASE_URL)
    except keyring.errors.PasswordDeleteError:
        pass


# ---------------------------------------------------------------------------
# Portal form login + code extraction
# ---------------------------------------------------------------------------

def _harvest_viewstate(html: str) -> dict[str, str]:
    """Extract ASP.NET anti-XSRF hidden fields from a login page."""
    fields: dict[str, str] = {}
    for name in ("__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION"):
        m = re.search(
            rf'<input[^>]+name="{re.escape(name)}"[^>]+value="([^"]*)"',
            html,
        )
        if m:
            fields[name] = m.group(1)
    return fields


def _extract_code_from_url(url: str) -> Optional[str]:
    """Return the `code` query parameter if present in a URL."""
    qs = urllib.parse.urlparse(url).query
    params = urllib.parse.parse_qs(qs)
    codes = params.get("code")
    return codes[0] if codes else None


def portal_login(
    username: str,
    password: str,
    client_id: str,
    client_secret: str,
    base_url: str = DEFAULT_BASE_URL,
) -> str:
    """
    Log in via the Portal form and exchange the resulting auth code for an
    access_token.  Returns the access_token string.
    """
    with httpx.Client(follow_redirects=True, timeout=30) as client:
        # Step 1: fetch login page and harvest VIEWSTATE tokens
        r = client.get(PORTAL_LOGIN_URL)
        r.raise_for_status()
        hidden = _harvest_viewstate(r.text)

        # Step 2: POST credentials
        payload = {
            "__EVENTTARGET": "",
            "__EVENTARGUMENT": "",
            "__VIEWSTATE": hidden.get("__VIEWSTATE", ""),
            "__VIEWSTATEGENERATOR": hidden.get("__VIEWSTATEGENERATOR", ""),
            "__EVENTVALIDATION": hidden.get("__EVENTVALIDATION", ""),
            "ctl00$MainContent$LoadOnceField": "",
            "ctl00$MainContent$Login1$UserName": username,
            "ctl00$MainContent$Login1$Password": password,
            "ctl00$MainContent$Login1$LoginButton": "Log In",
        }
        r2 = client.post(
            PORTAL_LOGIN_URL,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        r2.raise_for_status()

        # Step 3: look for auth code in the redirect chain
        code: Optional[str] = None
        for response in r2.history + [r2]:
            loc = response.headers.get("location", "")
            code = _extract_code_from_url(loc) or _extract_code_from_url(str(response.url))
            if code:
                break

        if not code:
            # Maybe the code is in the final page body (some implementations embed it)
            m = re.search(r'[?&]code=([^&"\'<\s]+)', r2.text)
            if m:
                code = m.group(1)

        if not code:
            raise RuntimeError(
                "Login succeeded but no OAuth2 authorization code was found in the "
                "response. The Portal may use a different redirect flow. "
                "Try capturing traffic with mitmproxy to find the correct code URL."
            )

    # Step 4: exchange code for access_token
    return _exchange_code(code, client_id, client_secret, base_url)


def _exchange_code(
    code: str,
    client_id: str,
    client_secret: str,
    base_url: str = DEFAULT_BASE_URL,
) -> str:
    """POST code to /v1/tokens/oauth/delegation → access_token."""
    url = base_url.rstrip("/") + DELEGATION_URL
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
    }
    r = httpx.post(url, json=payload, timeout=15)
    if not r.is_success:
        raise RuntimeError(
            f"Token exchange failed ({r.status_code}): {r.text}"
        )
    data = r.json()
    token = data.get("access_token")
    if not token:
        raise RuntimeError(f"No access_token in delegation response: {data}")
    return token
