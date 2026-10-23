from typing import Any, Callable

from fastapi import FastAPI, Header, HTTPException, Query, status
from pydantic import BaseModel, Field

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

        reply = handle_telegram_update(
            update,
            target_store=t_store,
            retriever=mem_retriever,
            llm=_resolve_llm(),
            sender=_send_telegram,
            article_store=a_store,
            base_ui_url=resolved_ui_url,
        )
        return {"ok": True, "reply": reply}

    return app


app = create_app()
