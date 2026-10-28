import gc
import os
from unittest.mock import MagicMock, patch

import pytest

from app.security import (
    EphemeralColabAuth,
    ephemeral_colab_credentials,
    zeroize_bytearray,
)


def test_zeroize_bytearray_wipes_all_bytes():
    data = bytearray(b"super_secret_oauth_token_12345")
    length = len(data)
    assert data != bytearray(length)

    zeroize_bytearray(data)

    assert len(data) == length
    assert all(b == 0 for b in data)


def test_ephemeral_colab_credentials_zeroizes_on_normal_exit():
    fake_token_json = '{"refresh_token": "rt_test_secret", "client_id": "cid_test"}'
    fake_cf_token = "cf_tunnel_test_token"

    with patch("app.security.fetch_raw_colab_secrets") as mock_fetch:
        mock_fetch.return_value = {
            "token_json": fake_token_json,
            "cf_token": fake_cf_token,
        }

        with ephemeral_colab_credentials() as auth:
            assert isinstance(auth, EphemeralColabAuth)
            assert auth.token_bytes == bytearray(fake_token_json.encode("utf-8"))
            assert auth.cf_token_bytes == bytearray(fake_cf_token.encode("utf-8"))
            assert auth.is_active is True

            # Data should still be intact inside context
            assert b"rt_test_secret" in auth.token_bytes
            assert b"cf_tunnel_test_token" in auth.cf_token_bytes

        # After exiting context
        assert auth.is_active is False
        assert all(b == 0 for b in auth.token_bytes)
        assert all(b == 0 for b in auth.cf_token_bytes)


def test_ephemeral_colab_credentials_zeroizes_on_exception():
    fake_token_json = '{"refresh_token": "err_secret"}'
    fake_cf_token = "err_cf_token"

    captured_auth = None

    with patch("app.security.fetch_raw_colab_secrets") as mock_fetch:
        mock_fetch.return_value = {
            "token_json": fake_token_json,
            "cf_token": fake_cf_token,
        }

        with pytest.raises(RuntimeError, match="Simulated crash during provisioning"):
            with ephemeral_colab_credentials() as auth:
                captured_auth = auth
                assert auth.is_active is True
                raise RuntimeError("Simulated crash during provisioning")

        assert captured_auth is not None
        assert captured_auth.is_active is False
        assert all(b == 0 for b in captured_auth.token_bytes)
        assert all(b == 0 for b in captured_auth.cf_token_bytes)
