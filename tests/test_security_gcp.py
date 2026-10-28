import json
import os
from unittest.mock import MagicMock, patch
import pytest

from app.security import fetch_raw_colab_secrets


def test_fetch_raw_colab_secrets_from_gcp_secret_manager(monkeypatch):
    monkeypatch.setenv("GCP_PROJECT", "test-project")
    monkeypatch.setenv("GCP_COLAB_SECRET_NAME", "test-secret")

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.payload.data.decode.return_value = json.dumps({
        "token_json": '{"access_token": "fake-oauth-token"}',
        "cf_token": "fake-cf-tunnel-token"
    })
    mock_client.access_secret_version.return_value = mock_response

    with patch("google.cloud.secretmanager.SecretManagerServiceClient", return_value=mock_client):
        secrets = fetch_raw_colab_secrets()

    assert secrets["token_json"] == '{"access_token": "fake-oauth-token"}'
    assert secrets["cf_token"] == "fake-cf-tunnel-token"
    mock_client.access_secret_version.assert_called_once_with(
        request={"name": "projects/test-project/secrets/test-secret/versions/latest"}
    )


def test_fetch_raw_colab_secrets_fallback_to_google_auth_default(monkeypatch):
    monkeypatch.delenv("GCP_PROJECT", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.setenv("GCP_COLAB_SECRET_NAME", "assist-colab-credentials")

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.payload.data.decode.return_value = json.dumps({
        "token_json": "auth-token",
        "cf_token": "cf-token"
    })
    mock_client.access_secret_version.return_value = mock_response

    with patch("google.auth.default", return_value=(None, "auto-detected-project")), \
         patch("google.cloud.secretmanager.SecretManagerServiceClient", return_value=mock_client):
        secrets = fetch_raw_colab_secrets()

    assert secrets["token_json"] == "auth-token"
    assert secrets["cf_token"] == "cf-token"
    mock_client.access_secret_version.assert_called_once_with(
        request={"name": "projects/auto-detected-project/secrets/assist-colab-credentials/versions/latest"}
    )
