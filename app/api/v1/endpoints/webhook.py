from typing import Any, Callable

from fastapi import APIRouter, Depends, Header, HTTPException, status

from app.api.deps import (
    get_article_store,
    get_base_ui_url,
    get_llm_instance,
    get_retriever,
    get_target_store,
    get_telegram_sender,
    get_webhook_secret,
)
from app.articles import InMemoryArticleStore
from app.auth import TokenManager
from app.config import settings
from app.rag import LLMProtocol, RetrieverProtocol
from app.targets import InMemoryTargetStore
from app.telegram import handle_telegram_update

router = APIRouter()


@router.post("/webhook/telegram")
def telegram_webhook(
    update: dict[str, Any],
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
    t_store: InMemoryTargetStore = Depends(get_target_store),
    mem_retriever: RetrieverProtocol = Depends(get_retriever),
    a_store: InMemoryArticleStore = Depends(get_article_store),
    llm: LLMProtocol = Depends(get_llm_instance),
    telegram_sender: Callable[[str, str], None] = Depends(get_telegram_sender),
    expected_secret: str = Depends(get_webhook_secret),
    base_ui_url: str = Depends(get_base_ui_url),
) -> dict[str, Any]:
    if expected_secret and x_telegram_bot_api_secret_token != expected_secret:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid webhook secret token",
        )

    store = TokenManager.get_store()
    raw_env_chats = (
        [c.strip() for c in settings.telegram_allowed_chat_ids.split(",") if c.strip()]
        if settings.telegram_allowed_chat_ids.strip()
        else []
    )
    app_chats = list(store.get_all_allowed_chat_ids()) if hasattr(store, "get_all_allowed_chat_ids") else []
    effective_chats = list(set(raw_env_chats + app_chats)) if (raw_env_chats or app_chats) else None
    colab_enabled = store.is_colab_gpu_enabled() if hasattr(store, "is_colab_gpu_enabled") else True

    reply = handle_telegram_update(
        update,
        target_store=t_store,
        retriever=mem_retriever,
        llm=llm,
        sender=telegram_sender,
        article_store=a_store,
        base_ui_url=base_ui_url,
        allowed_chat_ids=effective_chats,
        enable_colab_gpu=colab_enabled,
    )
    return {"ok": True, "reply": reply}
