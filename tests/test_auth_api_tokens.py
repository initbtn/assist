from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
import pytest

from app.auth import (
    TokenManager,
    InMemoryTokenStore,
    generate_api_token_pair,
    hash_token,
)
from app.config import settings
from app.main import create_app


def test_generate_and_hash_token_pair():
    token_pair = generate_api_token_pair(app_id="app-1", name="Test Key", ttl_days=30)
    assert token_pair.api_key.startswith("ast_live_")
    assert token_pair.refresh_token.startswith("ast_ref_")
    assert token_pair.key_prefix == token_pair.api_key[:17]
    assert token_pair.key_hash == hash_token(token_pair.api_key)
    assert token_pair.refresh_token_hash == hash_token(token_pair.refresh_token)
    assert token_pair.expires_at > datetime.now(timezone.utc)


def test_token_store_validation_and_expiration():
    store = InMemoryTokenStore()
    app = store.create_app("Partner App", "B2B client app")
    
    # 1. Valid token
    token = store.create_token(app.id, name="Key 1", ttl_days=30)
    validated = store.validate_api_key(token.api_key)
    assert validated is not None
    assert validated.app_id == app.id

    # 2. Expired token
    expired_token = store.create_token(app.id, name="Expired Key", ttl_days=-1)
    assert store.validate_api_key(expired_token.api_key) is None

    # 3. Revoked token
    store.revoke_token(token.id)
    assert store.validate_api_key(token.api_key) is None


def test_token_store_refresh_rotation():
    store = InMemoryTokenStore()
    app = store.create_app("Finance Bot", "Internal assistant")
    token = store.create_token(app.id, name="Rotatable Key", ttl_days=30)
    
    # Refresh token
    new_token = store.refresh_token_pair(token.refresh_token)
    assert new_token is not None
    assert new_token.api_key != token.api_key
    assert new_token.refresh_token != token.refresh_token
    
    # Old token must now be revoked
    assert store.validate_api_key(token.api_key) is None
    # New token must be valid
    assert store.validate_api_key(new_token.api_key) is not None

    # Reusing the old refresh token must fail
    assert store.refresh_token_pair(token.refresh_token) is None


def test_admin_api_endpoints():
    app = create_app()
    client = TestClient(app)
    admin_headers = {"X-Admin-Key": settings.resolved_admin_api_key()}

    # 1. Create app
    resp = client.post("/v1/admin/apps", json={"name": "Alpha App", "description": "Test App"}, headers=admin_headers)
    assert resp.status_code == 200
    app_data = resp.json()
    app_id = app_data["id"]

    # 2. List apps
    resp = client.get("/v1/admin/apps", headers=admin_headers)
    assert resp.status_code == 200
    assert any(a["id"] == app_id for a in resp.json())

    # 3. Create token for app
    resp = client.post(
        f"/v1/admin/apps/{app_id}/tokens",
        json={"name": "Alpha Key", "ttl_days": 30},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    token_data = resp.json()
    api_key = token_data["api_key"]
    refresh_token = token_data["refresh_token"]
    assert api_key.startswith("ast_live_")

    # 4. List tokens for app
    resp = client.get(f"/v1/admin/apps/{app_id}/tokens", headers=admin_headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    # Plain API key must NEVER be returned in listing
    assert "api_key" not in resp.json()[0]
    assert resp.json()[0]["key_prefix"].startswith("ast_live_")

    # 5. Call B2B protected endpoint with X-API-Key
    resp = client.get("/v1/chat/models", headers={"X-API-Key": api_key})
    assert resp.status_code == 200

    # 6. Call with invalid key
    resp = client.get("/v1/chat/models", headers={"X-API-Key": "invalid_key"})
    assert resp.status_code == 401

    # 7. Refresh token
    resp = client.post("/v1/auth/tokens/refresh", json={"refresh_token": refresh_token})
    assert resp.status_code == 200
    new_token_data = resp.json()
    new_api_key = new_token_data["api_key"]

    # 8. Old key should fail, new key should work
    assert client.get("/v1/chat/models", headers={"X-API-Key": api_key}).status_code == 401
    assert client.get("/v1/chat/models", headers={"X-API-Key": new_api_key}).status_code == 200

    # 9. Configure bot telegram ACL & GPU toggle
    resp = client.put(
        f"/v1/admin/apps/{app_id}/config",
        json={"allowed_chat_ids": ["123456", "789012"], "enable_colab_gpu": True, "rate_limit_rpm": 60},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    config = resp.json()
    assert config["allowed_chat_ids"] == ["123456", "789012"]
    assert config["enable_colab_gpu"] is True

    # 10. Revoke token
    new_token_id = new_token_data["id"]
    resp = client.delete(f"/v1/admin/tokens/{new_token_id}", headers=admin_headers)
    assert resp.status_code == 200
    assert client.get("/v1/chat/models", headers={"X-API-Key": new_api_key}).status_code == 401


def test_admin_api_authentication_guard(monkeypatch):
    monkeypatch.setattr(settings, "admin_api_key", "secret-admin-pass")
    app = create_app()
    client = TestClient(app)

    # 1. Access without Admin Key -> 401
    resp = client.get("/v1/admin/apps")
    assert resp.status_code == 401
    assert "Unauthorized admin access" in resp.json()["detail"]

    # 2. Access with wrong Admin Key -> 401
    resp = client.get("/v1/admin/apps", headers={"X-Admin-Key": "wrong-key"})
    assert resp.status_code == 401

    # 3. Access with valid X-Admin-Key -> 200
    resp = client.get("/v1/admin/apps", headers={"X-Admin-Key": "secret-admin-pass"})
    assert resp.status_code == 200

    # 4. Access with valid Bearer Authorization header -> 200
    resp = client.get("/v1/admin/apps", headers={"Authorization": "Bearer secret-admin-pass"})
    assert resp.status_code == 200
