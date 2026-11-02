from typing import Any, Callable

from fastapi import Header, HTTPException, Request, status

from app.articles import InMemoryArticleStore
from app.auth_oauth import verify_oauth_admin_token
from app.collectors import _default_github_get
from app.config import settings
from app.firebase_auth import verify_firebase_id_token
from app.rag import FakeMemoryRetriever, LLMProtocol, PGVectorRetriever, RetrieverProtocol, get_llm
from app.targets import InMemoryDeduplicationStore, InMemoryTargetStore
from app.telegram import send_telegram_message


def verify_admin_key(
    x_admin_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> str:
    raw_token = x_admin_key
    if not raw_token and authorization:
        parts = authorization.strip().split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            raw_token = parts[1]

    # 1. Try OAuth Admin Session Token
    if raw_token:
        oauth_email = verify_oauth_admin_token(raw_token)
        if oauth_email:
            allowed_emails = settings.resolved_admin_emails()
            if oauth_email in allowed_emails:
                return oauth_email
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Forbidden: email {oauth_email} is not an authorized administrator",
            )

    # 2. Try Firebase Auth ID Token verification (backward compatibility)
    if raw_token:
        fb_payload = verify_firebase_id_token(raw_token, settings.firebase_project_id)
        if fb_payload:
            email = str(fb_payload.get("email") or "").strip().lower()
            email_verified = fb_payload.get("email_verified") is True
            allowed_emails = settings.resolved_admin_emails()
            if email and email_verified and email in allowed_emails:
                return email
            if email and not email_verified and email in allowed_emails:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Forbidden: email {email} is not verified",
                )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Forbidden: email {email} is not an authorized administrator",
            )

    # 3. Fallback to API Key authentication (for CI/CD or CLI usage)
    expected_key = settings.resolved_admin_api_key().strip()
    if expected_key and raw_token and raw_token.strip() == expected_key:
        return "admin_key_user"

    # If neither matched
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Unauthorized admin access: invalid or missing OAuth Session token / Admin key",
    )


def get_target_store(request: Request) -> InMemoryTargetStore:
    store = getattr(request.app.state, "target_store", None)
    if store is not None:
        return store
    return InMemoryTargetStore(seed=True)


def get_dedup_store(request: Request) -> InMemoryDeduplicationStore:
    store = getattr(request.app.state, "dedup_store", None)
    if store is not None:
        return store
    return InMemoryDeduplicationStore()


def get_retriever(request: Request) -> RetrieverProtocol:
    retriever = getattr(request.app.state, "retriever", None)
    if retriever is not None:
        return retriever
    if settings.use_pgvector:
        return PGVectorRetriever.from_settings(settings)
    return FakeMemoryRetriever()


def get_article_store(request: Request) -> InMemoryArticleStore:
    store = getattr(request.app.state, "article_store", None)
    if store is not None:
        return store
    return InMemoryArticleStore()


def get_llm_instance(request: Request) -> LLMProtocol:
    llm = getattr(request.app.state, "llm", None)
    if llm is not None:
        return llm
    return get_llm(settings)


def get_telegram_sender(request: Request) -> Callable[[str, str], None]:
    sender = getattr(request.app.state, "telegram_sender", None)
    if sender is not None:
        return sender

    def _default_sender(chat_id: str, text: str) -> None:
        send_telegram_message(
            text=text,
            bot_token=settings.resolved_telegram_bot_token(),
            chat_id=chat_id,
        )

    return _default_sender


def get_github_http_get(request: Request) -> Callable[[str], list[dict[str, Any]]]:
    gh_get = getattr(request.app.state, "github_http_get", None)
    if gh_get is not None:
        return gh_get
    return _default_github_get


def get_webhook_secret(request: Request) -> str:
    secret = getattr(request.app.state, "webhook_secret", None)
    if secret is not None:
        return secret
    return settings.telegram_webhook_secret


def get_default_chat_id(request: Request) -> str:
    chat_id = getattr(request.app.state, "default_chat_id", None)
    if chat_id is not None and str(chat_id).strip():
        return str(chat_id).strip()
    return settings.resolved_telegram_chat_id()


def get_base_ui_url(request: Request) -> str:
    ui_url = getattr(request.app.state, "base_ui_url", None)
    if ui_url is not None and str(ui_url).strip():
        return str(ui_url).strip()
    return settings.public_ui_base_url
