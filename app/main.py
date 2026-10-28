from typing import Any, Callable

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.auth import ApiTokenRecord, TokenManager
from app.articles import (
    BriefingArticle,
    InMemoryArticleStore,
    ModelBriefComparison,
    build_briefing_article,
    compare_briefing_models,
    format_telegram_brief_message,
)
from app.collectors import (
    CollectionSummary,
    _default_github_get,
    collect_and_ingest_targets,
    seed_initial_knowledge,
)
from app.config import settings
from app.ingest import ingest_document
from app.rag import (
    FakeMemoryRetriever,
    LLMProtocol,
    PGVectorRetriever,
    QueryResult,
    answer_question,
    get_llm,
    resolve_ollama_model_name,
)
from app.targets import (
    InMemoryDeduplicationStore,
    InMemoryTargetStore,
    ResearchTarget,
    ResearchTargetCreate,
)
from app.telegram import handle_telegram_update, send_telegram_message


class TargetStatusPatch(BaseModel):
    is_active: bool


class IngestRequest(BaseModel):
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    chunk_size: int = 1000
    chunk_overlap: int = 200


class IngestResponse(BaseModel):
    ingested_chunks: int
    skipped_duplicate: bool


class QueryRequest(BaseModel):
    question: str
    domain: str | None = None
    target_name: str | None = None
    k: int = 4


class CollectRequest(BaseModel):
    domain: str | None = None
    include_seed: bool = False
    per_target_limit: int = 3


class BriefSendRequest(BaseModel):
    chat_id: str | None = None
    domain: str | None = None
    date_str: str | None = None


class BriefSendResponse(BaseModel):
    sent: bool
    chat_id: str
    brief: str
    article_slug: str
    article_url: str
    summary_lines: list[str]


class BriefCompareRequest(BaseModel):
    models: list[str] = Field(default_factory=lambda: ["A", "C"])
    domain: str | None = None
    date_str: str | None = None


class BriefCompareResponse(BaseModel):
    date: str
    comparisons: dict[str, ModelBriefComparison]


class AppCreateRequest(BaseModel):
    name: str
    description: str = ""


class TokenCreateRequest(BaseModel):
    name: str
    ttl_days: int = 30


class TokenRefreshRequest(BaseModel):
    refresh_token: str


class BotConfigUpdateRequest(BaseModel):
    allowed_chat_ids: list[str] | None = None
    enable_colab_gpu: bool | None = None
    rate_limit_rpm: int | None = None


def verify_api_key(
    x_api_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> ApiTokenRecord:
    raw_key = x_api_key
    if not raw_key and authorization:
        parts = authorization.strip().split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            raw_key = parts[1]
    if not raw_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API Key. Provide via X-API-Key or Authorization: Bearer <key>",
        )
    token_store = TokenManager.get_store()
    token_rec = token_store.validate_api_key(raw_key)
    if not token_rec:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid, expired, or revoked API Key",
        )
    return token_rec



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
    app = FastAPI(title="assist — Personal Dev Trend RAG Assistant")

    t_store = target_store if target_store is not None else InMemoryTargetStore(seed=True)
    d_store = dedup_store if dedup_store is not None else InMemoryDeduplicationStore()
    mem_retriever = (
        retriever
        if retriever is not None
        else (PGVectorRetriever() if settings.use_pgvector else FakeMemoryRetriever())
    )
    a_store = article_store if article_store is not None else InMemoryArticleStore()
    gh_get = github_http_get if github_http_get is not None else _default_github_get
    expected_secret = (
        webhook_secret
        if webhook_secret is not None
        else settings.telegram_webhook_secret
    )
    resolved_ui_url = (
        base_ui_url.strip()
        if base_ui_url is not None and base_ui_url.strip()
        else settings.public_ui_base_url
    )

    def _resolve_llm() -> LLMProtocol:
        return llm if llm is not None else get_llm(settings)

    def _resolve_chat_id(explicit_chat_id: str | None = None) -> str:
        if explicit_chat_id and explicit_chat_id.strip():
            return explicit_chat_id.strip()
        if default_chat_id is not None and default_chat_id.strip():
            return default_chat_id.strip()
        return settings.resolved_telegram_chat_id()

    def _send_telegram(chat_id: str, text: str) -> None:
        if telegram_sender is not None:
            telegram_sender(chat_id, text)
            return
        send_telegram_message(
            text=text,
            bot_token=settings.resolved_telegram_bot_token(),
            chat_id=chat_id,
        )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/targets", response_model=list[ResearchTarget])
    def list_targets(
        domain: str | None = Query(default=None),
        active_only: bool = Query(default=True),
    ) -> list[ResearchTarget]:
        return t_store.list_targets(domain=domain, active_only=active_only)

    @app.post(
        "/targets",
        response_model=ResearchTarget,
        status_code=status.HTTP_201_CREATED,
    )
    def create_target(payload: ResearchTargetCreate) -> ResearchTarget:
        try:
            return t_store.add_target(payload)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc

    @app.patch("/targets/{target_id}", response_model=ResearchTarget)
    def patch_target(
        target_id: str,
        payload: TargetStatusPatch,
    ) -> ResearchTarget:
        try:
            return t_store.set_active(target_id, is_active=payload.is_active)
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            ) from exc

    @app.post("/ingest", response_model=IngestResponse)
    def ingest_endpoint(payload: IngestRequest) -> IngestResponse:
        try:
            count = ingest_document(
                text=payload.text,
                metadata=payload.metadata,
                vector_store=mem_retriever,
                dedup_store=d_store,
                chunk_size=payload.chunk_size,
                chunk_overlap=payload.chunk_overlap,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc

        skipped = count == 0 and bool(payload.text.strip())
        return IngestResponse(
            ingested_chunks=count,
            skipped_duplicate=skipped,
        )

    @app.post("/collect", response_model=CollectionSummary)
    def collect_endpoint(payload: CollectRequest) -> CollectionSummary:
        seeded = 0
        if payload.include_seed:
            seeded = seed_initial_knowledge(
                vector_store=mem_retriever,
                dedup_store=d_store,
            )
        summary = collect_and_ingest_targets(
            target_store=t_store,
            vector_store=mem_retriever,
            dedup_store=d_store,
            http_get=gh_get,
            domain=payload.domain,
            per_target_limit=payload.per_target_limit,
        )
        return summary.model_copy(update={"seeded_chunks": seeded})

    @app.post("/query", response_model=QueryResult)
    def query_endpoint(payload: QueryRequest) -> QueryResult:
        try:
            return answer_question(
                payload.question,
                retriever=mem_retriever,
                llm=_resolve_llm(),
                domain=payload.domain,
                target_name=payload.target_name,
                k=payload.k,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc

    @app.get("/articles", response_model=list[BriefingArticle])
    def list_articles() -> list[BriefingArticle]:
        return a_store.list_articles()

    @app.get("/articles/{slug}", response_model=BriefingArticle)
    def get_article(slug: str) -> BriefingArticle:
        article = a_store.get(slug)
        if article is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Article not found: {slug}",
            )
        return article

    @app.post("/brief/send", response_model=BriefSendResponse)
    def send_brief_endpoint(payload: BriefSendRequest) -> BriefSendResponse:
        target_chat = _resolve_chat_id(payload.chat_id)
        if not target_chat:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="chat_id is required",
            )
        docs = mem_retriever.search("brief", domain=payload.domain, k=30)
        article = build_briefing_article(
            docs,
            llm=_resolve_llm(),
            date_str=payload.date_str,
            base_ui_url=resolved_ui_url,
        )
        a_store.save(article)
        brief_text = format_telegram_brief_message(article)
        _send_telegram(target_chat, brief_text)
        return BriefSendResponse(
            sent=True,
            chat_id=target_chat,
            brief=brief_text,
            article_slug=article.slug,
            article_url=article.article_url,
            summary_lines=article.summary_lines,
        )

    @app.post("/brief/compare", response_model=BriefCompareResponse)
    def compare_brief_endpoint(payload: BriefCompareRequest) -> BriefCompareResponse:
        if not payload.models:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="models must not be empty",
            )
        model_llms: dict[str, LLMProtocol] = {}
        try:
            for item in payload.models:
                resolved_name = resolve_ollama_model_name(item)
                model_llms[resolved_name] = (
                    llm
                    if llm is not None
                    else get_llm(settings, model_override=resolved_name)
                )
            docs = mem_retriever.search("brief", domain=payload.domain, k=30)
            comparisons = compare_briefing_models(
                docs,
                model_llms=model_llms,
                date_str=payload.date_str,
                base_ui_url=resolved_ui_url,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc

        resolved_date = (
            next(iter(comparisons.values())).article_url.rsplit("/", 1)[-1]
            if comparisons
            else (payload.date_str or "")
        )
        return BriefCompareResponse(
            date=resolved_date,
            comparisons=comparisons,
        )


    @app.post("/webhook/telegram")
    def telegram_webhook(
        update: dict[str, Any],
        x_telegram_bot_api_secret_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        if expected_secret and x_telegram_bot_api_secret_token != expected_secret:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid webhook secret token",
            )

        allowed_chats = (
            settings.resolved_telegram_allowed_chat_ids()
            if settings.telegram_allowed_chat_ids.strip()
            else None
        )
        reply = handle_telegram_update(
            update,
            target_store=t_store,
            retriever=mem_retriever,
            llm=_resolve_llm(),
            sender=_send_telegram,
            article_store=a_store,
            base_ui_url=resolved_ui_url,
            allowed_chat_ids=allowed_chats,
        )
        return {"ok": True, "reply": reply}

    @app.post("/v1/admin/apps")
    def create_admin_app(payload: AppCreateRequest) -> dict[str, Any]:
        store = TokenManager.get_store()
        rec = store.create_app(payload.name, payload.description)
        return {
            "id": rec.id,
            "name": rec.name,
            "description": rec.description,
            "created_at": rec.created_at.isoformat(),
        }

    @app.get("/v1/admin/apps")
    def list_admin_apps() -> list[dict[str, Any]]:
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

    @app.post("/v1/admin/apps/{app_id}/tokens")
    def create_admin_app_token(app_id: str, payload: TokenCreateRequest) -> dict[str, Any]:
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

    @app.get("/v1/admin/apps/{app_id}/tokens")
    def list_admin_app_tokens(app_id: str) -> list[dict[str, Any]]:
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

    @app.delete("/v1/admin/tokens/{token_id}")
    def revoke_admin_token(token_id: str) -> dict[str, Any]:
        store = TokenManager.get_store()
        success = store.revoke_token(token_id)
        if not success:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Token not found")
        return {"revoked": True, "token_id": token_id}

    @app.post("/v1/auth/tokens/refresh")
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

    @app.get("/v1/admin/apps/{app_id}/config")
    def get_admin_bot_config(app_id: str) -> dict[str, Any]:
        store = TokenManager.get_store()
        cfg = store.get_bot_config(app_id)
        return {
            "app_id": cfg.app_id,
            "allowed_chat_ids": cfg.allowed_chat_ids,
            "enable_colab_gpu": cfg.enable_colab_gpu,
            "rate_limit_rpm": cfg.rate_limit_rpm,
        }

    @app.put("/v1/admin/apps/{app_id}/config")
    def update_admin_bot_config(app_id: str, payload: BotConfigUpdateRequest) -> dict[str, Any]:
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

    @app.get("/v1/chat/models")
    def list_chat_models(token: ApiTokenRecord = Depends(verify_api_key)) -> dict[str, Any]:
        return {
            "models": [settings.llm_model_name, settings.ollama_model_name],
            "authenticated_app_id": token.app_id,
        }

    return app


app = create_app()
