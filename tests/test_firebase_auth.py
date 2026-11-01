import base64
import json
import time
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography import x509
from cryptography.x509.oid import NameOID
import datetime

from app.firebase_auth import verify_firebase_id_token


from cryptography.hazmat.primitives import serialization

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


def test_verify_firebase_id_token_success_and_failures():
    priv_key, cert_pem = _generate_test_rsa_key_and_cert()
    kid = "test-kid-123"
    fake_certs = {kid: cert_pem}

    # 1. Generate valid token
    header = {"alg": "RS256", "kid": kid, "typ": "JWT"}
    payload = {
        "iss": "https://securetoken.google.com/test-project",
        "aud": "test-project",
        "sub": "user-uid-999",
        "email": "cto.jsconn@gmail.com",
        "email_verified": True,
        "exp": int(time.time()) + 3600,
        "iat": int(time.time()),
    }
    raw_h = base64.urlsafe_b64encode(json.dumps(header).encode()).rstrip(b"=").decode()
    raw_p = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    to_sign = f"{raw_h}.{raw_p}".encode()
    sig = priv_key.sign(to_sign, padding.PKCS1v15(), hashes.SHA256())
    raw_s = base64.urlsafe_b64encode(sig).rstrip(b"=").decode()
    valid_token = f"{raw_h}.{raw_p}.{raw_s}"

    verified = verify_firebase_id_token(valid_token, "test-project", certs_fetcher=lambda: fake_certs)
    assert verified is not None
    assert verified["email"] == "cto.jsconn@gmail.com"
    assert verified["sub"] == "user-uid-999"

    # 2. Expired token
    expired_payload = dict(payload, exp=int(time.time()) - 100)
    raw_ep = base64.urlsafe_b64encode(json.dumps(expired_payload).encode()).rstrip(b"=").decode()
    e_sig = priv_key.sign(f"{raw_h}.{raw_ep}".encode(), padding.PKCS1v15(), hashes.SHA256())
    expired_token = f"{raw_h}.{raw_ep}.{base64.urlsafe_b64encode(e_sig).rstrip(b'=').decode()}"
    assert verify_firebase_id_token(expired_token, "test-project", certs_fetcher=lambda: fake_certs) is None

    # 3. Wrong project audience
    assert verify_firebase_id_token(valid_token, "other-project", certs_fetcher=lambda: fake_certs) is None

    # 4. Tampered payload
    tampered_p = base64.urlsafe_b64encode(json.dumps(dict(payload, email="hacker@evil.com")).encode()).rstrip(b"=").decode()
    tampered_token = f"{raw_h}.{tampered_p}.{raw_s}"
    assert verify_firebase_id_token(tampered_token, "test-project", certs_fetcher=lambda: fake_certs) is None
