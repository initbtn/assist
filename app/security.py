from contextlib import contextmanager
import gc
import json
import logging
import os
from typing import Generator

logger = logging.getLogger(__name__)


def zeroize_bytearray(buf: bytearray) -> None:
    for i in range(len(buf)):
        buf[i] = 0


def fetch_raw_colab_secrets() -> dict[str, str]:
    token_json = ""
    cf_token = ""

    # 1. Check GCP Secret Manager if google-cloud-secret-manager is installed
    secret_name = os.getenv("GCP_COLAB_SECRET_NAME", "assist-colab-credentials")
    gcp_project = os.getenv("GCP_PROJECT") or os.getenv("GOOGLE_CLOUD_PROJECT")
    if gcp_project:
        try:
            from google.cloud import secretmanager  # type: ignore

            client = secretmanager.SecretManagerServiceClient()
            resource_name = f"projects/{gcp_project}/secrets/{secret_name}/versions/latest"
            response = client.access_secret_version(request={"name": resource_name})
            payload_str = response.payload.data.decode("utf-8")
            data = json.loads(payload_str)
            token_json = str(data.get("token_json") or "").strip()
            cf_token = str(data.get("cf_token") or "").strip()
            del payload_str
            del data
        except Exception as exc:
            logger.debug("Failed to fetch Colab secret from GCP Secret Manager: %s", exc)

    # 2. Local fallback via pass or local config (development / agent runner mode)
    if not token_json:
        token_path = os.path.expanduser("~/.config/colab-cli/token.json")
        if os.path.exists(token_path):
            try:
                with open(token_path, "r", encoding="utf-8") as f:
                    token_json = f.read().strip()
            except Exception as exc:
                logger.debug("Could not read local colab token.json: %s", exc)

    if not cf_token:
        try:
            import subprocess

            proc = subprocess.run(
                ["pass", "show", "cloudflare/colab-tunnel-token"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if proc.returncode == 0:
                cf_token = proc.stdout.splitlines()[0].strip()
        except Exception as exc:
            logger.debug("Could not read cf_token from pass: %s", exc)

    return {
        "token_json": token_json,
        "cf_token": cf_token,
    }


class EphemeralColabAuth:
    def __init__(self, token_bytes: bytearray, cf_token_bytes: bytearray) -> None:
        self.token_bytes = token_bytes
        self.cf_token_bytes = cf_token_bytes
        self.is_active = True

    def zeroize(self) -> None:
        if self.token_bytes:
            zeroize_bytearray(self.token_bytes)
        if self.cf_token_bytes:
            zeroize_bytearray(self.cf_token_bytes)
        self.is_active = False
        gc.collect()


@contextmanager
def ephemeral_colab_credentials() -> Generator[EphemeralColabAuth, None, None]:
    raw = fetch_raw_colab_secrets()
    token_str = raw.get("token_json", "")
    cf_token_str = raw.get("cf_token", "")

    token_b = bytearray(token_str.encode("utf-8"))
    cf_token_b = bytearray(cf_token_str.encode("utf-8"))

    # Immediately delete references to plaintext Python strings
    del token_str
    del cf_token_str
    del raw

    auth = EphemeralColabAuth(token_b, cf_token_b)
    try:
        yield auth
    finally:
        auth.zeroize()
