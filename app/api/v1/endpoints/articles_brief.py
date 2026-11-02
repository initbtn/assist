from typing import Callable

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.deps import (
    get_article_store,
    get_base_ui_url,
    get_default_chat_id,
    get_llm_instance,
    get_retriever,
    get_telegram_sender,
)
from app.articles import (
    BriefingArticle,
    InMemoryArticleStore,
    build_briefing_article,
    compare_briefing_models,
    format_telegram_brief_message,
)
from app.config import settings
from app.rag import LLMProtocol, RetrieverProtocol, get_llm, resolve_ollama_model_name
from app.schemas import (
    BriefCompareRequest,
    BriefCompareResponse,
    BriefSendRequest,
    BriefSendResponse,
)

router = APIRouter()


@router.get("/articles", response_model=list[BriefingArticle])
def list_articles(
    a_store: InMemoryArticleStore = Depends(get_article_store),
) -> list[BriefingArticle]:
    return a_store.list_articles()


@router.get("/articles/{slug}", response_model=BriefingArticle)
def get_article(
    slug: str,
    a_store: InMemoryArticleStore = Depends(get_article_store),
) -> BriefingArticle:
    article = a_store.get(slug)
    if article is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Article not found: {slug}",
        )
    return article


@router.post("/brief/send", response_model=BriefSendResponse)
def send_brief_endpoint(
    payload: BriefSendRequest,
    mem_retriever: RetrieverProtocol = Depends(get_retriever),
    a_store: InMemoryArticleStore = Depends(get_article_store),
    llm: LLMProtocol = Depends(get_llm_instance),
    telegram_sender: Callable[[str, str], None] = Depends(get_telegram_sender),
    default_chat_id: str = Depends(get_default_chat_id),
    base_ui_url: str = Depends(get_base_ui_url),
) -> BriefSendResponse:
    target_chat = (
        payload.chat_id.strip()
        if payload.chat_id and payload.chat_id.strip()
        else default_chat_id
    )
    if not target_chat:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="chat_id is required",
        )
    docs = mem_retriever.search("brief", domain=payload.domain, k=30)
    article = build_briefing_article(
        docs,
        llm=llm,
        date_str=payload.date_str,
        base_ui_url=base_ui_url,
    )
    a_store.save(article)
    brief_text = format_telegram_brief_message(article)
    telegram_sender(target_chat, brief_text)
    return BriefSendResponse(
        sent=True,
        chat_id=target_chat,
        brief=brief_text,
        article_slug=article.slug,
        article_url=article.article_url,
        summary_lines=article.summary_lines,
    )


@router.post("/brief/compare", response_model=BriefCompareResponse)
def compare_brief_endpoint(
    payload: BriefCompareRequest,
    request: Request,
    mem_retriever: RetrieverProtocol = Depends(get_retriever),
    base_ui_url: str = Depends(get_base_ui_url),
) -> BriefCompareResponse:
    if not payload.models:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="models must not be empty",
        )
    model_llms: dict[str, LLMProtocol] = {}
    custom_llm = getattr(request.app.state, "llm", None)
    try:
        for item in payload.models:
            resolved_name = resolve_ollama_model_name(item)
            model_llms[resolved_name] = (
                custom_llm
                if custom_llm is not None
                else get_llm(settings, model_override=resolved_name)
            )
        docs = mem_retriever.search("brief", domain=payload.domain, k=30)
        comparisons = compare_briefing_models(
            docs,
            model_llms=model_llms,
            date_str=payload.date_str,
            base_ui_url=base_ui_url,
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
