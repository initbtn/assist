from __future__ import annotations

import json
import logging
import secrets
import time
import urllib.parse
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"


class OAuthAdminSessionStore:
    def __init__(self, ttl_seconds: int = 86400):
        self.ttl_seconds = ttl_seconds
        # token -> {"email": email, "expires_at": expires_at}
        self._sessions: dict[str, dict[str, Any]] = {}
        # state -> expires_at
        self._states: dict[str, float] = {}

    def create_state(self, ttl: int = 600) -> str:
        state = secrets.token_urlsafe(32)
        now = time.time()
        self._cleanup_states()
        self._states[state] = now + ttl
        return state

    def verify_and_consume_state(self, state: str) -> bool:
        self._cleanup_states()
        if not state:
            return False
        expiry = self._states.pop(state, None)
        if expiry is None:
            return False
        return time.time() <= expiry

    def _cleanup_states(self) -> None:
        now = time.time()
        expired = [s for s, exp in self._states.items() if exp < now]
        for s in expired:
            self._states.pop(s, None)

    def create_session(self, email: str) -> str:
        token = f"ast_adm_{secrets.token_urlsafe(32)}"
        now = time.time()
        self._sessions[token] = {
            "email": email.strip().lower(),
            "expires_at": now + self.ttl_seconds,
            "created_at": now,
        }
        return token

    def verify_session(self, token: str) -> str | None:
        if not token:
            return None
        sess = self._sessions.get(token)
        if not sess:
            return None
        now = time.time()
        if sess["expires_at"] < now:
            self._sessions.pop(token, None)
            return None
        return sess["email"]

    def revoke_session(self, token: str) -> bool:
        return self._sessions.pop(token, None) is not None


_default_oauth_store = OAuthAdminSessionStore()


def get_oauth_store() -> OAuthAdminSessionStore:
    return _default_oauth_store


def build_google_auth_url(state: str, redirect_uri: str, client_id: str) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    return f"{GOOGLE_AUTH_URL}?{urllib.parse.urlencode(params)}"


def exchange_code_for_user_info(
    code: str,
    redirect_uri: str,
    client_id: str,
    client_secret: str,
) -> dict[str, Any]:
    # 1. Exchange code for tokens
    payload = urllib.parse.urlencode({
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }).encode("utf-8")

    req = urllib.request.Request(
        GOOGLE_TOKEN_URL,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        token_data = json.loads(resp.read().decode("utf-8"))

    access_token = token_data.get("access_token")
    if not access_token:
        raise ValueError("Missing access_token from Google OAuth response")

    # 2. Fetch userinfo using access_token
    userinfo_req = urllib.request.Request(
        GOOGLE_USERINFO_URL,
        headers={"Authorization": f"Bearer {access_token}"},
    )
    with urllib.request.urlopen(userinfo_req, timeout=10) as user_resp:
        user_info = json.loads(user_resp.read().decode("utf-8"))

    return user_info


def verify_oauth_admin_token(token: str) -> str | None:
    return get_oauth_store().verify_session(token)
