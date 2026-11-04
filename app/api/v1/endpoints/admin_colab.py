from typing import Any

from fastapi import APIRouter, Depends

from app.api.deps import verify_admin_key
from app.provisioner import ProvisionerState, get_provisioner

router = APIRouter()


@router.get("/v1/admin/paas/colab")
def get_colab_paas_status(_admin_guard: str = Depends(verify_admin_key)) -> dict[str, Any]:
    provisioner = get_provisioner()
    return provisioner.get_status()


@router.post("/v1/admin/paas/colab/boot")
def boot_colab_paas_instance(_admin_guard: str = Depends(verify_admin_key)) -> dict[str, Any]:
    provisioner = get_provisioner()
    if provisioner.check_health():
        provisioner.touch()
        return {"status": "ready", "state": provisioner.state.value}

    provisioner.trigger_background_provision()
    return {"status": "booting", "state": ProvisionerState.PROVISIONING.value}


@router.post("/v1/admin/paas/colab/stop")
async def stop_colab_paas_instance(_admin_guard: str = Depends(verify_admin_key)) -> dict[str, Any]:
    provisioner = get_provisioner()
    success = await provisioner.stop()
    return {
        "status": "stopped" if success else "failed",
        "state": provisioner.state.value,
    }
