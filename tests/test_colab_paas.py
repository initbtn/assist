import asyncio
import time
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import create_app
from app.provisioner import ColabProvisioner, ProvisionerState


@pytest.mark.anyio
async def test_idle_watcher_scale_to_zero():
    provisioner = ColabProvisioner(base_url="http://mock-ollama:11434")
    provisioner._state = ProvisionerState.READY
    # Mock health check to be True
    provisioner.check_health = MagicMock(return_value=True)

    stopped = asyncio.Event()

    async def mock_stop():
        provisioner._state = ProvisionerState.IDLE
        stopped.set()
        return True

    provisioner.stop = mock_stop
    # Set last used time to 10 seconds ago
    provisioner._last_used_at = time.time() - 10.0

    # Start watcher with 2.0s idle timeout and 0.05s check interval
    task = asyncio.create_task(
        provisioner.start_idle_watcher(idle_timeout_sec=2.0, check_interval_sec=0.05)
    )

    try:
        await asyncio.wait_for(stopped.wait(), timeout=2.0)
        assert provisioner.state == ProvisionerState.IDLE
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


@pytest.mark.anyio
async def test_idle_watcher_resets_on_touch():
    provisioner = ColabProvisioner(base_url="http://mock-ollama:11434")
    provisioner._state = ProvisionerState.READY
    provisioner.check_health = MagicMock(return_value=True)
    stop_called = False

    async def mock_stop():
        nonlocal stop_called
        stop_called = True
        return True

    provisioner.stop = mock_stop
    provisioner._last_used_at = time.time()

    task = asyncio.create_task(
        provisioner.start_idle_watcher(idle_timeout_sec=0.3, check_interval_sec=0.05)
    )

    # Touch before timeout
    await asyncio.sleep(0.15)
    provisioner.touch()
    await asyncio.sleep(0.15)
    assert not stop_called

    # Now let it expire
    await asyncio.sleep(0.25)
    assert stop_called
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


def test_paas_rest_endpoints(monkeypatch):
    monkeypatch.setattr(settings, "admin_api_key", "test-admin-key")
    app = create_app()
    client = TestClient(app)

    # 1. Unauthorized request
    res_unauth = client.get("/v1/admin/paas/colab")
    assert res_unauth.status_code == 401

    headers = {"Authorization": "Bearer test-admin-key"}

    # 2. GET /v1/admin/paas/colab
    res = client.get("/v1/admin/paas/colab", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert "state" in data
    assert "healthy" in data
    assert "last_used_at" in data
    assert "idle_seconds" in data

    # 3. POST /v1/admin/paas/colab/stop
    with patch("app.provisioner.ColabProvisioner.stop", return_value=True):
        res_stop = client.post("/v1/admin/paas/colab/stop", headers=headers)
        assert res_stop.status_code == 200
        assert res_stop.json()["status"] == "stopped"

    # 4. POST /v1/admin/paas/colab/boot
    with patch("app.provisioner.ColabProvisioner.trigger_background_provision"):
        res_boot = client.post("/v1/admin/paas/colab/boot", headers=headers)
        assert res_boot.status_code == 200
        assert res_boot.json()["status"] in ("booting", "ready")


def test_lifespan_integration():
    with patch("app.provisioner.ColabProvisioner.start_idle_watcher") as mock_watcher:
        app = create_app()
        with TestClient(app) as client:
            res = client.get("/health")
            assert res.status_code == 200
            assert mock_watcher.called
