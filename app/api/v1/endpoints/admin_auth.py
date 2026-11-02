import urllib.parse
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse

from app.api.deps import verify_admin_key
from app.auth_oauth import (
    build_google_auth_url,
    exchange_code_for_user_info,
    get_oauth_store,
)
from app.config import settings

router = APIRouter()


@router.get("/v1/admin/auth/google/login")
def google_oauth_login() -> RedirectResponse:
    client_id = settings.resolved_google_client_id()
    if not client_id:
        raise HTTPException(status_code=500, detail="Google OAuth client_id is not configured")
    store = get_oauth_store()
    state = store.create_state()
    redirect_uri = settings.resolved_google_redirect_uri()
    url = build_google_auth_url(state=state, redirect_uri=redirect_uri, client_id=client_id)
    return RedirectResponse(url=url, status_code=status.HTTP_302_FOUND)


@router.get("/v1/admin/auth/google/callback")
def google_oauth_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
) -> RedirectResponse:
    admin_ui = f"{settings.public_ui_base_url.rstrip('/')}/admin"
    if error:
        return RedirectResponse(
            url=f"{admin_ui}#error={urllib.parse.quote(error)}",
            status_code=status.HTTP_302_FOUND,
        )
    if not code or not state:
        return RedirectResponse(
            url=f"{admin_ui}#error=missing_code_or_state",
            status_code=status.HTTP_302_FOUND,
        )

    store = get_oauth_store()
    if not store.verify_and_consume_state(state):
        return RedirectResponse(
            url=f"{admin_ui}#error=invalid_or_expired_state",
            status_code=status.HTTP_302_FOUND,
        )

    client_id = settings.resolved_google_client_id()
    client_secret = settings.resolved_google_client_secret()
    redirect_uri = settings.resolved_google_redirect_uri()

    try:
        from app import main as app_main

        exchange_fn = getattr(app_main, "exchange_code_for_user_info", exchange_code_for_user_info)
        user_info = exchange_fn(
            code=code,
            redirect_uri=redirect_uri,
            client_id=client_id,
            client_secret=client_secret,
        )
    except Exception:
        return RedirectResponse(
            url=f"{admin_ui}#error=token_exchange_failed",
            status_code=status.HTTP_302_FOUND,
        )

    email = str(user_info.get("email") or "").strip().lower()
    email_verified = user_info.get("email_verified") is True
    if not email or not email_verified:
        return RedirectResponse(
            url=f"{admin_ui}#error=email_not_verified",
            status_code=status.HTTP_302_FOUND,
        )

    allowed = settings.resolved_admin_emails()
    if email not in allowed:
        return RedirectResponse(
            url=f"{admin_ui}#error=unauthorized_email",
            status_code=status.HTTP_302_FOUND,
        )

    session_token = store.create_session(email)
    return RedirectResponse(
        url=f"{admin_ui}#admin_token={session_token}&email={urllib.parse.quote(email)}",
        status_code=status.HTTP_302_FOUND,
    )


@router.get("/v1/admin/auth/me")
def get_current_admin(admin_email: str = Depends(verify_admin_key)) -> dict[str, Any]:
    return {"email": admin_email, "role": "admin"}
