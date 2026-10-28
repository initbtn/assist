import asyncio
from enum import Enum
import logging
import os
import subprocess
import time
from typing import Any

import httpx

from app.config import settings
from app.security import ephemeral_colab_credentials

logger = logging.getLogger(__name__)


class ProvisionerState(str, Enum):
    IDLE = "IDLE"
    PROVISIONING = "PROVISIONING"
    READY = "READY"
    STOPPING = "STOPPING"


class ColabProvisioner:
    def __init__(
        self,
        base_url: str | None = None,
        runner_script: str | None = None,
    ) -> None:
        self.base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self.runner_script = runner_script or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "scripts",
            "run_colab_llm.sh",
        )
        self._state = ProvisionerState.IDLE
        self._lock = asyncio.Lock()
        self._in_flight_task: asyncio.Task[bool] | None = None
        self._last_used_at: float = time.time()

    @property
    def state(self) -> ProvisionerState:
        return self._state

    def check_health(self) -> bool:
        try:
            resp = httpx.get(
                f"{self.base_url}/api/version",
                headers={"User-Agent": "curl/7.81.0"},
                timeout=2.0,
            )
            return resp.status_code == 200
        except Exception:
            return False

    async def ensure_ready(self, timeout_sec: float = 180.0) -> str:
        if self._state == ProvisionerState.READY and self.check_health():
            self._last_used_at = time.time()
            return self.base_url

        if self._state == ProvisionerState.PROVISIONING and self._in_flight_task is not None:
            logger.info("Awaiting in-flight Colab provisioning task...")
            success = await self._in_flight_task
            if not success or self._state != ProvisionerState.READY:
                raise RuntimeError("Concurrent Colab provisioning failed")
            self._last_used_at = time.time()
            return self.base_url

        async with self._lock:
            # Double-check after acquiring lock
            if self.check_health():
                self._state = ProvisionerState.READY
                self._last_used_at = time.time()
                return self.base_url

            self._state = ProvisionerState.PROVISIONING
            logger.info("Triggering Colab on-demand provisioning...")

            loop = asyncio.get_running_loop()
            self._in_flight_task = loop.create_task(self._execute_provisioning())
            try:
                success = await asyncio.wait_for(self._in_flight_task, timeout=timeout_sec)
                if not success:
                    self._state = ProvisionerState.IDLE
                    raise RuntimeError("Failed to provision Colab GPU instance")
                self._state = ProvisionerState.READY
                self._last_used_at = time.time()
                return self.base_url
            except Exception as exc:
                self._state = ProvisionerState.IDLE
                logger.error("Error during Colab provisioning: %s", exc)
                raise
            finally:
                self._in_flight_task = None

    async def _execute_provisioning(self) -> bool:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._provision_sync)

    def _provision_sync(self) -> bool:
        logger.info("Executing on-demand Colab launcher with ephemeral credentials...")
        with ephemeral_colab_credentials() as auth:
            if not auth.is_active:
                logger.error("Ephemeral Colab auth failed to activate")
                return False

            env = dict(os.environ)
            # Inject Cloudflare tunnel token if present in ephemeral credentials
            if auth.cf_token_bytes:
                env["CLOUDFLARE_TUNNEL_TOKEN"] = auth.cf_token_bytes.decode("utf-8")

            if os.path.exists(self.runner_script):
                cmd = [self.runner_script]
            else:
                cmd = ["colab", "new", "--gpu", "T4"]

            try:
                proc = subprocess.run(
                    cmd,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=180,
                )
                logger.info("Colab provisioning stdout: %s", proc.stdout[-300:] if proc.stdout else "")
                if proc.returncode != 0:
                    logger.error("Colab launcher failed with code %d: %s", proc.returncode, proc.stderr)
                    return False
            except Exception as exc:
                logger.error("Exception running Colab launcher: %s", exc)
                return False

        # Credentials wiped after exiting with block
        logger.info("Ephemeral credentials wiped from memory. Checking Ollama health...")
        for _ in range(15):
            if self.check_health():
                logger.info("Colab Ollama instance is online and healthy!")
                return True
            time.sleep(2.0)

        return self.check_health()

    async def stop(self) -> bool:
        async with self._lock:
            self._state = ProvisionerState.STOPPING
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, self._execute_stop)
            self._state = ProvisionerState.IDLE
            return result

    def trigger_background_provision(self) -> None:
        import threading

        if self._state in (ProvisionerState.PROVISIONING, ProvisionerState.READY):
            return

        self._state = ProvisionerState.PROVISIONING

        def _runner() -> None:
            try:
                success = self._provision_sync()
                self._state = ProvisionerState.READY if success else ProvisionerState.IDLE
            except Exception as exc:
                logger.error("Background Colab provisioning failed: %s", exc)
                self._state = ProvisionerState.IDLE

        t = threading.Thread(target=_runner, daemon=True)
        t.start()

    def _execute_stop(self) -> bool:
        logger.info("Stopping Colab instance (Scale-to-Zero)...")
        try:
            proc = subprocess.run(
                ["colab", "stop"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            return proc.returncode == 0
        except Exception as exc:
            logger.warning("Failed to execute colab stop: %s", exc)
            return False
