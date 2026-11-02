from typing import Any, Callable
from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import (
    get_dedup_store,
    get_github_http_get,
    get_llm_instance,
    get_retriever,
    get_target_store,
)
from app.collectors import CollectionSummary, collect_and_ingest_targets, seed_initial_knowledge
from app.ingest import ingest_document
from app.rag import LLMProtocol, QueryResult, RetrieverProtocol, answer_question
from app.schemas import CollectRequest, IngestRequest, IngestResponse, QueryRequest
from app.targets import InMemoryDeduplicationStore, InMemoryTargetStore

router = APIRouter()


@router.post("/ingest", response_model=IngestResponse)
def ingest_endpoint(
    payload: IngestRequest,
    mem_retriever: RetrieverProtocol = Depends(get_retriever),
    d_store: InMemoryDeduplicationStore = Depends(get_dedup_store),
) -> IngestResponse:
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


@router.post("/collect", response_model=CollectionSummary)
def collect_endpoint(
    payload: CollectRequest,
    t_store: InMemoryTargetStore = Depends(get_target_store),
    mem_retriever: RetrieverProtocol = Depends(get_retriever),
    d_store: InMemoryDeduplicationStore = Depends(get_dedup_store),
    gh_get: Callable[[str], list[dict[str, Any]]] = Depends(get_github_http_get),
) -> CollectionSummary:
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


@router.post("/query", response_model=QueryResult)
def query_endpoint(
    payload: QueryRequest,
    mem_retriever: RetrieverProtocol = Depends(get_retriever),
    llm: LLMProtocol = Depends(get_llm_instance),
) -> QueryResult:
    try:
        return answer_question(
            payload.question,
            retriever=mem_retriever,
            llm=llm,
            domain=payload.domain,
            target_name=payload.target_name,
            k=payload.k,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
