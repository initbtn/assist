import asyncio
from contextlib import asynccontextmanager
from typing import Any, Callable

from fastapi import FastAPI

from app.api.deps import verify_admin_key
from app.api.v1.api import api_router
from app.articles import InMemoryArticleStore
from app.auth_oauth import exchange_code_for_user_info
from app.collectors import _default_github_get
from app.config import settings
from app.gateway_chat import router as gateway_chat_router
from app.provisioner import get_provisioner
from app.rag import FakeMemoryRetriever, LLMProtocol, PGVectorRetriever
from app.schemas import (
    AppCreateRequest,
    BotConfigUpdateRequest,
    BriefCompareRequest,
    BriefCompareResponse,
    BriefSendRequest,
    BriefSendResponse,
    CollectRequest,
    IngestRequest,
    IngestResponse,
    QueryRequest,
    TargetStatusPatch,
    TokenCreateRequest,
    TokenRefreshRequest,
)
from app.targets import InMemoryDeduplicationStore, InMemoryTargetStore


@asynccontextmanager
async def lifespan(app: FastAPI):
    provisioner = get_provisioner()
    watcher_task = asyncio.create_task(
        provisioner.start_idle_watcher(idle_timeout_sec=900.0, check_interval_sec=30.0)
    )
    yield
    watcher_task.cancel()
    try:
        await watcher_task
    except asyncio.CancelledError:
        pass


def create_app(
    *,
    target_store: InMemoryTargetStore | None = None,
    dedup_store: InMemoryDeduplicationStore | None = None,
    retriever: FakeMemoryRetriever | None = None,
    article_store: InMemoryArticleStore | None = None,
    llm: LLMProtocol | None = None,
    telegram_sender: Callable[[str, str], None] | None = None,
    github_http_get: Callable[[str], list[dict[str, Any]]] | None = None,
    webhook_secret: str | None = None,
    default_chat_id: str | None = None,
    base_ui_url: str | None = None,
) -> FastAPI:
    app = FastAPI(
        title="assist — Personal Dev Trend RAG Assistant",
        lifespan=lifespan,
    )

    # State injection for dependency injection (DI) support
    app.state.target_store = (
        target_store if target_store is not None else InMemoryTargetStore(seed=True)
    )
    app.state.dedup_store = (
        dedup_store if dedup_store is not None else InMemoryDeduplicationStore()
    )
    app.state.retriever = (
        retriever
        if retriever is not None
        else (PGVectorRetriever() if settings.use_pgvector else FakeMemoryRetriever())
    )
    app.state.article_store = (
        article_store if article_store is not None else InMemoryArticleStore()
    )
    app.state.llm = llm
    app.state.telegram_sender = telegram_sender
    app.state.github_http_get = github_http_get
    app.state.webhook_secret = webhook_secret
    app.state.default_chat_id = default_chat_id
    app.state.base_ui_url = base_ui_url

    # Mount routers
    app.include_router(api_router)
    app.include_router(gateway_chat_router, prefix="/v1/gateway/chat", tags=["gateway_chat"])

    return app


app = create_app()

__all__ = [
    "app",
    "create_app",
    "verify_admin_key",
    "exchange_code_for_user_info",
    "TargetStatusPatch",
    "IngestRequest",
    "IngestResponse",
    "QueryRequest",
    "CollectRequest",
    "BriefSendRequest",
    "BriefSendResponse",
    "BriefCompareRequest",
    "BriefCompareResponse",
    "AppCreateRequest",
    "TokenCreateRequest",
    "TokenRefreshRequest",
    "BotConfigUpdateRequest",
]
