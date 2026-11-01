from __future__ import annotations

import base64
import json
import logging
import time
import urllib.request
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding

logger = logging.getLogger(__name__)

GOOGLE_CERTS_URL = "https://www.googleapis.com/robot/v1/metadata/x509/securetoken@system.gserviceaccount.com"

_CERTS_CACHE: dict[str, str] = {}
_CERTS_CACHE_EXPIRY: float = 0.0


def _fetch_google_public_certs(force_refresh: bool = False) -> dict[str, str]:
    global _CERTS_CACHE, _CERTS_CACHE_EXPIRY
    now = time.time()
    if not force_refresh and _CERTS_CACHE and now < _CERTS_CACHE_EXPIRY:
        return _CERTS_CACHE

    try:
        req = urllib.request.Request(GOOGLE_CERTS_URL, headers={"User-Agent": "assist-auth-verifier"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            # Parse max-age from Cache-Control header if present
            cache_control = resp.headers.get("Cache-Control", "")
            max_age = 3600
            for part in cache_control.split(","):
                part = part.strip()
                if part.startswith("max-age="):
                    try:
                        max_age = int(part.split("=")[1])
                    except Exception:
                        pass
            _CERTS_CACHE = data
            _CERTS_CACHE_EXPIRY = now + max_age
            return _CERTS_CACHE
    except Exception as exc:
        logger.error("Failed to fetch Google public certs: %s", exc)
        return _CERTS_CACHE


def _urlsafe_b64decode(s: str) -> bytes:
    rem = len(s) % 4
    if rem > 0:
        s += "=" * (4 - rem)
    return base64.urlsafe_b64decode(s.encode("utf-8"))


def verify_firebase_id_token(
    id_token: str,
    expected_project_id: str,
    *,
    certs_fetcher: Any = None,
) -> dict[str, Any] | None:
    """Verifies a Firebase Authentication ID token according to Google specifications:

    1. Must have 3 dot-separated base64 segments: header, payload, signature.
    2. Header 'alg' must be 'RS256', 'kid' must match one of Google's public certs.
    3. 'aud' must match expected_project_id.
    4. 'iss' must be 'https://securetoken.google.com/<expected_project_id>'.
    5. 'sub' must be non-empty user id.
    6. 'exp' must be in the future.
    7. Signature must be cryptographically valid using Google's public key.
    """
    if not id_token or not id_token.strip():
        return None

    parts = id_token.strip().split(".")
    if len(parts) != 3:
        return None

    raw_header, raw_payload, raw_sig = parts
    try:
        header = json.loads(_urlsafe_b64decode(raw_header).decode("utf-8"))
        payload = json.loads(_urlsafe_b64decode(raw_payload).decode("utf-8"))
        signature = _urlsafe_b64decode(raw_sig)
        if not isinstance(header, dict) or not isinstance(payload, dict):
            return None
    except Exception as exc:
        logger.debug("Failed to decode token parts: %s", exc)
        return None

    if header.get("alg") != "RS256":
        return None

    kid = header.get("kid")
    if not kid or not isinstance(kid, str):
        return None

    now = int(time.time())
    if payload.get("exp", 0) < now:
        logger.debug("Firebase ID token expired: %s < %s", payload.get("exp"), now)
        return None

    # Clock skew tolerance (5 minutes) for issue time
    clock_skew = 300
    if payload.get("iat") and payload.get("iat") > now + clock_skew:
        logger.debug("Token issued in the future: %s > %s", payload.get("iat"), now)
        return None
    if payload.get("auth_time") and payload.get("auth_time") > now + clock_skew:
        logger.debug("Auth time in the future: %s > %s", payload.get("auth_time"), now)
        return None

    if payload.get("aud") != expected_project_id:
        logger.debug("Invalid aud: expected %s, got %s", expected_project_id, payload.get("aud"))
        return None

    expected_iss = f"https://securetoken.google.com/{expected_project_id}"
    if payload.get("iss") != expected_iss:
        logger.debug("Invalid iss: expected %s, got %s", expected_iss, payload.get("iss"))
        return None

    if not payload.get("sub"):
        return None

    # Fetch public certs
    fetcher = certs_fetcher if certs_fetcher is not None else _fetch_google_public_certs
    certs = fetcher()
    if kid not in certs and certs_fetcher is None:
        # Cache miss on key rotation: force refresh certs from Google
        certs = _fetch_google_public_certs(force_refresh=True)

    if kid not in certs:
        logger.debug("kid %s not found in Google public certs", kid)
        return None

    cert_pem = certs[kid]
    try:
        cert = x509.load_pem_x509_certificate(cert_pem.encode("utf-8"))
        pubkey = cert.public_key()
        signed_data = f"{raw_header}.{raw_payload}".encode("ascii")
        pubkey.verify(
            signature,
            signed_data,
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        return payload
    except Exception as exc:
        logger.debug("Cryptographic signature verification failed: %s", exc)
        return None
