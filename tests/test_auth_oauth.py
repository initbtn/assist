from __future__ import annotations

import time
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient

from app.auth_oauth import (
    OAuthAdminSessionStore,
    build_google_auth_url,
    verify_oauth_admin_token,
)
from app.config import settings
from app.main import app


def test_build_google_auth_url():
    url = build_google_auth_url(
        state="test-state-123",
        redirect_uri="https://assist-brief.vercel.app/v1/admin/auth/google/callback",
        client_id="mock-client-id.apps.googleusercontent.com",
    )
    assert "https://accounts.google.com/o/oauth2/v2/auth" in url
    assert "client_id=mock-client-id" in url
    assert "state=test-state-123" in url
    assert "scope=openid+email+profile" in url or "scope=openid%20email%20profile" in url


def test_oauth_session_store_lifecycle():
    store = OAuthAdminSessionStore(ttl_seconds=3600)
    token = store.create_session("cto.jsconn@gmail.com")
    assert token.startswith("ast_adm_")

    email = store.verify_session(token)
    assert email == "cto.jsconn@gmail.com"

    # Revoke
    store.revoke_session(token)
    assert store.verify_session(token) is None


def test_oauth_login_redirect_endpoint(monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "test-client-id")
    monkeypatch.setattr(settings, "google_client_secret", "test-client-secret")
    client = TestClient(app)

    res = client.get("/v1/admin/auth/google/login", follow_redirects=False)
    assert res.status_code == 302
    location = res.headers.get("location", "")
    assert "accounts.google.com/o/oauth2/v2/auth" in location
    assert "client_id=test-client-id" in location


def test_oauth_callback_success_and_forbidden(monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "test-client-id")
    monkeypatch.setattr(settings, "google_client_secret", "test-client-secret")
    monkeypatch.setattr(settings, "admin_emails", "cto.jsconn@gmail.com")
    client = TestClient(app)

    # 1. State mismatch / invalid
    res = client.get("/v1/admin/auth/google/callback?code=mock_code&state=invalid_state", follow_redirects=False)
    assert res.status_code == 302
    assert "error=" in res.headers.get("location", "")

    # Initiate login to generate valid state in session
    login_res = client.get("/v1/admin/auth/google/login", follow_redirects=False)
    loc = login_res.headers["location"]
    # Extract state param
    import urllib.parse
    parsed = urllib.parse.urlparse(loc)
    qs = urllib.parse.parse_qs(parsed.query)
    valid_state = qs["state"][0]

    # 2. Successful authorized email (cto.jsconn@gmail.com)
    mock_user_info = {"email": "cto.jsconn@gmail.com", "email_verified": True}
    with patch("app.main.exchange_code_for_user_info", return_value=mock_user_info):
        res = client.get(f"/v1/admin/auth/google/callback?code=mock_code&state={valid_state}", follow_redirects=False)
        assert res.status_code == 302
        target = res.headers.get("location", "")
        assert "/admin#admin_token=" in target
        assert "cto.jsconn" in target
        assert "gmail.com" in target

        # Extract token and test admin API access
        admin_token = target.split("admin_token=")[1].split("&")[0]
        api_res = client.get("/v1/admin/apps", headers={"Authorization": f"Bearer {admin_token}"})
        assert api_res.status_code == 200

    # 3. Unverified email -> Forbidden
    login_res2 = client.get("/v1/admin/auth/google/login", follow_redirects=False)
    valid_state2 = urllib.parse.parse_qs(urllib.parse.urlparse(login_res2.headers["location"]).query)["state"][0]
    with patch("app.main.exchange_code_for_user_info", return_value={"email": "cto.jsconn@gmail.com", "email_verified": False}):
        res = client.get(f"/v1/admin/auth/google/callback?code=mock_code&state={valid_state2}", follow_redirects=False)
        assert res.status_code == 302
        assert "error=" in res.headers.get("location", "")
        assert "email_not_verified" in res.headers.get("location", "")

    # 4. Non-whitelisted email -> Forbidden
    login_res3 = client.get("/v1/admin/auth/google/login", follow_redirects=False)
    valid_state3 = urllib.parse.parse_qs(urllib.parse.urlparse(login_res3.headers["location"]).query)["state"][0]
    with patch("app.main.exchange_code_for_user_info", return_value={"email": "attacker@gmail.com", "email_verified": True}):
        res = client.get(f"/v1/admin/auth/google/callback?code=mock_code&state={valid_state3}", follow_redirects=False)
        assert res.status_code == 302
        assert "unauthorized_email" in res.headers.get("location", "")
