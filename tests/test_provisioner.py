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
async def test_ensure_ready_concurrent_failure_propagates_error():
    prov = ColabProvisioner(base_url="https://dom-slm.conn.ai.kr")

    async def fake_fail_spawn():
        await asyncio.sleep(0.05)
        return False

    with patch.object(prov, "check_health", return_value=False), \
         patch.object(prov, "_execute_provisioning", side_effect=fake_fail_spawn):

        results = await asyncio.gather(
            prov.ensure_ready(),
            prov.ensure_ready(),
            return_exceptions=True,
        )

        assert all(isinstance(r, RuntimeError) for r in results)
        assert prov.state == ProvisionerState.IDLE


def test_trigger_background_provision_state_transitions():
    import time
    prov = ColabProvisioner(base_url="https://dom-slm.conn.ai.kr")
    assert prov.state == ProvisionerState.IDLE

    with patch.object(prov, "_provision_sync", return_value=True):
        prov.trigger_background_provision()
        time.sleep(0.1)
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


@pytest.mark.anyio
async def test_notifier_called_on_state_transitions():
    notifications: list[tuple[str, str]] = []

    def mock_notifier(event: str, message: str) -> None:
        notifications.append((event, message))

    prov = ColabProvisioner(
        base_url="https://dom-slm.conn.ai.kr",
        notifier=mock_notifier,
    )

    with patch.object(prov, "check_health", side_effect=[False, True]), \
         patch.object(prov, "_execute_provisioning", return_value=True), \
         patch.object(prov, "_execute_stop", return_value=True):

        await prov.ensure_ready()
        assert len(notifications) == 2
        assert notifications[0][0] == "PROVISIONING_STARTED"
        assert "부팅 시작" in notifications[0][1] or "🟡" in notifications[0][1]
        assert notifications[1][0] == "PROVISIONING_READY"
        assert "준비 완료" in notifications[1][1] or "🟢" in notifications[1][1]

        await prov.stop()
        assert len(notifications) == 3
        assert notifications[2][0] == "SCALE_TO_ZERO"
        assert "회수 완료" in notifications[2][1] or "⚪" in notifications[2][1]


@pytest.mark.anyio
async def test_notifier_called_on_provisioning_error():
    notifications: list[tuple[str, str]] = []

    def mock_notifier(event: str, message: str) -> None:
        notifications.append((event, message))

    prov = ColabProvisioner(
        base_url="https://dom-slm.conn.ai.kr",
        notifier=mock_notifier,
    )

    with patch.object(prov, "check_health", return_value=False), \
         patch.object(prov, "_execute_provisioning", return_value=False):

        with pytest.raises(RuntimeError):
            await prov.ensure_ready()

        assert len(notifications) >= 2
        assert notifications[0][0] == "PROVISIONING_STARTED"
        error_events = [n for n in notifications if n[0] == "PROVISIONING_ERROR"]
        assert len(error_events) == 1
        assert "🔴" in error_events[0][1] or "장애" in error_events[0][1]

