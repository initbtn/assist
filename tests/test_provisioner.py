import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.provisioner import (
    ColabProvisioner,
    ProvisionerState,
)


@pytest.mark.anyio
async def test_initial_state_is_idle():
    prov = ColabProvisioner(base_url="https://dom-slm.conn.ai.kr")
    assert prov.state == ProvisionerState.IDLE


@pytest.mark.anyio
async def test_ensure_ready_returns_immediately_if_already_healthy():
    prov = ColabProvisioner(base_url="https://dom-slm.conn.ai.kr")
    prov._state = ProvisionerState.READY

    with patch.object(prov, "check_health", return_value=True) as mock_health:
        url = await prov.ensure_ready()
        assert url == "https://dom-slm.conn.ai.kr"
        assert prov.state == ProvisionerState.READY
        mock_health.assert_called_once()


@pytest.mark.anyio
async def test_ensure_ready_deduplicates_concurrent_calls():
    prov = ColabProvisioner(base_url="https://dom-slm.conn.ai.kr")
    spawn_count = 0

    async def fake_spawn():
        nonlocal spawn_count
        spawn_count += 1
        await asyncio.sleep(0.05)
        return True

    with patch.object(prov, "check_health", side_effect=[False, True, True]), \
         patch.object(prov, "_execute_provisioning", side_effect=fake_spawn):

        # Launch 3 concurrent calls
        results = await asyncio.gather(
            prov.ensure_ready(),
            prov.ensure_ready(),
            prov.ensure_ready(),
        )

        assert results == [
            "https://dom-slm.conn.ai.kr",
            "https://dom-slm.conn.ai.kr",
            "https://dom-slm.conn.ai.kr",
        ]
        assert spawn_count == 1
        assert prov.state == ProvisionerState.READY


@pytest.mark.anyio
async def test_stop_transitions_to_idle():
    prov = ColabProvisioner(base_url="https://dom-slm.conn.ai.kr")
    prov._state = ProvisionerState.READY

    with patch.object(prov, "_execute_stop", return_value=True) as mock_stop:
        stopped = await prov.stop()
        assert stopped is True
        assert prov.state == ProvisionerState.IDLE
        mock_stop.assert_called_once()
