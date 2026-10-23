from typing import Any, Protocol

from langchain_core.documents import Document

from app.chunking import chunk_text
from app.config import Settings, settings
from app.targets import DeduplicationStoreProtocol, compute_content_hash


class VectorStoreProtocol(Protocol):
    def add_documents(self, documents: list[Document]) -> list[str]: ...


def get_embeddings(cfg: Settings = settings):
    from langchain_huggingface import HuggingFaceEmbeddings

    return HuggingFaceEmbeddings(model_name=cfg.embedding_model_name)


def get_vector_store(cfg: Settings = settings) -> VectorStoreProtocol:
    from langchain_postgres import PGVector

    return PGVector(
        embeddings=get_embeddings(cfg),
        collection_name=cfg.vector_collection_name,
        connection=cfg.supabase_db_url,
        use_jsonb=True,
    )


def ingest_document(
    text: str,
    metadata: dict[str, Any] | None = None,
    *,
    vector_store: VectorStoreProtocol | None = None,
    dedup_store: DeduplicationStoreProtocol | None = None,
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
) -> int:
    docs = chunk_text(
        text=text,
        metadata=metadata,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    if not docs:
        return 0

    meta = metadata or {}
    source_url = str(meta.get("source_url") or "").strip()
    content_hash = compute_content_hash(text)

    if dedup_store is not None and source_url:
        if dedup_store.is_duplicate(source_url, content_hash):
            return 0

    store = vector_store if vector_store is not None else get_vector_store()
    store.add_documents(docs)

    if dedup_store is not None and source_url:
        dedup_store.record(
            source_url=source_url,
            content_hash=content_hash,
            domain=str(meta.get("domain") or ""),
            target_name=str(meta.get("target_name") or ""),
        )

    return len(docs)
