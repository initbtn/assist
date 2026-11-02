import base64
import datetime
import json
import time

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID
from fastapi.testclient import TestClient

from app.auth_oauth import get_oauth_store
from app.config import settings
from app.main import app


def _generate_test_rsa_key_and_cert():
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "test-google-signer"),
    ])
    cert = x509.CertificateBuilder().subject_name(
        subject
    ).issuer_name(
        issuer
    ).public_key(
        private_key.public_key()
    ).serial_number(
        x509.random_serial_number()
    ).not_valid_before(
        datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)
    ).not_valid_after(
        datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1)
    ).sign(private_key, hashes.SHA256())

    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode("utf-8")
    return private_key, cert_pem


def _build_test_jwt(private_key, kid: str, project_id: str, email: str, email_verified: bool = True, exp_offset: int = 3600):
    header = {"alg": "RS256", "kid": kid, "typ": "JWT"}
    payload = {
        "iss": f"https://securetoken.google.com/{project_id}",
        "aud": project_id,
        "sub": "uid-12345",
        "email": email,
        "email_verified": email_verified,
        "exp": int(time.time()) + exp_offset,
        "iat": int(time.time()),
    }
    raw_h = base64.urlsafe_b64encode(json.dumps(header).encode()).rstrip(b"=").decode()
    raw_p = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    to_sign = f"{raw_h}.{raw_p}".encode()
    sig = private_key.sign(to_sign, padding.PKCS1v15(), hashes.SHA256())
    raw_s = base64.urlsafe_b64encode(sig).rstrip(b"=").decode()
    return f"{raw_h}.{raw_p}.{raw_s}"


def test_auth_v2_stateless_firebase_token_primary(monkeypatch):
    client = TestClient(app)
    priv_key, cert_pem = _generate_test_rsa_key_and_cert()
    kid = "google-cert-kid-v2"
    fake_certs = {kid: cert_pem}

    monkeypatch.setattr(settings, "firebase_project_id", "waffle-dominic")
    monkeypatch.setattr(settings, "admin_emails", "cto.jsconn@gmail.com")
    import app.firebase_auth as f_auth
    monkeypatch.setattr(f_auth, "_fetch_google_public_certs", lambda force=False: fake_certs)

    valid_token = _build_test_jwt(priv_key, kid, "waffle-dominic", "cto.jsconn@gmail.com")

    # 1. Primary Stateless Firebase ID Token in Authorization: Bearer
    res = client.get("/v1/admin/auth/me", headers={"Authorization": f"Bearer {valid_token}"})
    assert res.status_code == 200
    data = res.json()
    assert data["email"] == "cto.jsconn@gmail.com"
    assert data["role"] == "admin"

    # 2. Primary Stateless Firebase ID Token in X-Admin-Key
    res_x = client.get("/v1/admin/auth/me", headers={"X-Admin-Key": valid_token})
    assert res_x.status_code == 200
    assert res_x.json()["email"] == "cto.jsconn@gmail.com"


def test_auth_v2_unauthorized_cases(monkeypatch):
    client = TestClient(app)
    priv_key, cert_pem = _generate_test_rsa_key_and_cert()
    kid = "google-cert-kid-v2"
    fake_certs = {kid: cert_pem}

    monkeypatch.setattr(settings, "firebase_project_id", "waffle-dominic")
    monkeypatch.setattr(settings, "admin_emails", "cto.jsconn@gmail.com")
    import app.firebase_auth as f_auth
    monkeypatch.setattr(f_auth, "_fetch_google_public_certs", lambda force=False: fake_certs)

    # 1. Unverified email -> 403 Forbidden
    unverified_token = _build_test_jwt(priv_key, kid, "waffle-dominic", "cto.jsconn@gmail.com", email_verified=False)
    res1 = client.get("/v1/admin/auth/me", headers={"Authorization": f"Bearer {unverified_token}"})
    assert res1.status_code == 403
    assert "not verified" in res1.json()["detail"]

    # 2. Non-admin email -> 403 Forbidden
    other_token = _build_test_jwt(priv_key, kid, "waffle-dominic", "attacker@evil.com", email_verified=True)
    res2 = client.get("/v1/admin/auth/me", headers={"Authorization": f"Bearer {other_token}"})
    assert res2.status_code == 403
    assert "not an authorized administrator" in res2.json()["detail"]

    # 3. Expired token -> 401 Unauthorized
    expired_token = _build_test_jwt(priv_key, kid, "waffle-dominic", "cto.jsconn@gmail.com", exp_offset=-60)
    res3 = client.get("/v1/admin/auth/me", headers={"Authorization": f"Bearer {expired_token}"})
    assert res3.status_code == 401

    # 4. Forged signature -> 401 Unauthorized
    priv_key2, _ = _generate_test_rsa_key_and_cert()
    forged_token = _build_test_jwt(priv_key2, kid, "waffle-dominic", "cto.jsconn@gmail.com")
    res4 = client.get("/v1/admin/auth/me", headers={"Authorization": f"Bearer {forged_token}"})
    assert res4.status_code == 401


def test_auth_v2_backward_compatibility(monkeypatch):
    client = TestClient(app)
    monkeypatch.setattr(settings, "admin_emails", "cto.jsconn@gmail.com")
    monkeypatch.setattr(settings, "admin_api_key", "secret-ci-admin-key")

    # 1. Legacy in-memory OAuth session token fallback
    oauth_store = get_oauth_store()
    legacy_token = oauth_store.create_session("cto.jsconn@gmail.com")
    res_legacy = client.get("/v1/admin/auth/me", headers={"Authorization": f"Bearer {legacy_token}"})
    assert res_legacy.status_code == 200
    assert res_legacy.json()["email"] == "cto.jsconn@gmail.com"

    # 2. Static Admin API key fallback
    res_static = client.get("/v1/admin/auth/me", headers={"Authorization": "Bearer secret-ci-admin-key"})
    assert res_static.status_code == 200
    assert res_static.json()["email"] == "admin_key_user"

    # 3. Missing credentials -> 401
    res_none = client.get("/v1/admin/auth/me")
    assert res_none.status_code == 401
