from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import verify_admin_key
from app.auth import TokenManager
from app.schemas import (
    AppCreateRequest,
    BotConfigUpdateRequest,
    TokenCreateRequest,
    TokenRefreshRequest,
)

router = APIRouter()


@router.post("/v1/admin/apps")
def create_admin_app(
    payload: AppCreateRequest,
    _admin_guard: str = Depends(verify_admin_key),
) -> dict[str, Any]:
    store = TokenManager.get_store()
    rec = store.create_app(payload.name, payload.description)
    return {
        "id": rec.id,
        "name": rec.name,
        "description": rec.description,
        "created_at": rec.created_at.isoformat(),
    }


@router.get("/v1/admin/apps")
def list_admin_apps(_admin_guard: str = Depends(verify_admin_key)) -> list[dict[str, Any]]:
    store = TokenManager.get_store()
    return [
        {
            "id": a.id,
            "name": a.name,
            "description": a.description,
            "is_active": a.is_active,
            "created_at": a.created_at.isoformat(),
        }
        for a in store.list_apps()
    ]


@router.post("/v1/admin/apps/{app_id}/tokens")
def create_admin_app_token(
    app_id: str,
    payload: TokenCreateRequest,
    _admin_guard: str = Depends(verify_admin_key),
) -> dict[str, Any]:
    store = TokenManager.get_store()
    app_rec = store.get_app(app_id)
    if not app_rec:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="App not found")
    pair = store.create_token(app_id, payload.name, payload.ttl_days)
    return {
        "id": pair.id,
        "app_id": pair.app_id,
        "name": pair.name,
        "api_key": pair.api_key,
        "refresh_token": pair.refresh_token,
        "key_prefix": pair.key_prefix,
        "expires_at": pair.expires_at.isoformat(),
    }


@router.get("/v1/admin/apps/{app_id}/tokens")
def list_admin_app_tokens(
    app_id: str,
    _admin_guard: str = Depends(verify_admin_key),
) -> list[dict[str, Any]]:
    store = TokenManager.get_store()
    tokens = store.list_tokens(app_id)
    return [
        {
            "id": t.id,
            "app_id": t.app_id,
            "name": t.name,
            "key_prefix": t.key_prefix,
            "expires_at": t.expires_at.isoformat(),
            "is_active": t.is_active,
            "created_at": t.created_at.isoformat(),
            "last_used_at": t.last_used_at.isoformat() if t.last_used_at else None,
        }
        for t in tokens
    ]


@router.delete("/v1/admin/tokens/{token_id}")
def revoke_admin_token(
    token_id: str,
    _admin_guard: str = Depends(verify_admin_key),
) -> dict[str, Any]:
    store = TokenManager.get_store()
    success = store.revoke_token(token_id)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Token not found")
    return {"revoked": True, "token_id": token_id}


@router.post("/v1/auth/tokens/refresh")
def refresh_auth_token(payload: TokenRefreshRequest) -> dict[str, Any]:
    store = TokenManager.get_store()
    new_pair = store.refresh_token_pair(payload.refresh_token)
    if not new_pair:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )
    return {
        "id": new_pair.id,
        "app_id": new_pair.app_id,
        "name": new_pair.name,
        "api_key": new_pair.api_key,
        "refresh_token": new_pair.refresh_token,
        "key_prefix": new_pair.key_prefix,
        "expires_at": new_pair.expires_at.isoformat(),
    }


@router.get("/v1/admin/apps/{app_id}/config")
def get_admin_bot_config(
    app_id: str,
    _admin_guard: str = Depends(verify_admin_key),
) -> dict[str, Any]:
    store = TokenManager.get_store()
    cfg = store.get_bot_config(app_id)
    return {
        "app_id": cfg.app_id,
        "allowed_chat_ids": cfg.allowed_chat_ids,
        "enable_colab_gpu": cfg.enable_colab_gpu,
        "rate_limit_rpm": cfg.rate_limit_rpm,
    }


@router.put("/v1/admin/apps/{app_id}/config")
def update_admin_bot_config(
    app_id: str,
    payload: BotConfigUpdateRequest,
    _admin_guard: str = Depends(verify_admin_key),
) -> dict[str, Any]:
    store = TokenManager.get_store()
    cfg = store.update_bot_config(
        app_id,
        allowed_chat_ids=payload.allowed_chat_ids,
        enable_colab_gpu=payload.enable_colab_gpu,
        rate_limit_rpm=payload.rate_limit_rpm,
    )
    return {
        "app_id": cfg.app_id,
        "allowed_chat_ids": cfg.allowed_chat_ids,
        "enable_colab_gpu": cfg.enable_colab_gpu,
        "rate_limit_rpm": cfg.rate_limit_rpm,
    }
