from typing import Any

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter


def chunk_text(
    text: str,
    metadata: dict[str, Any] | None = None,
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
) -> list[Document]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if chunk_overlap < 0 or chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be >= 0 and < chunk_size")

    stripped = text.strip()
    if not stripped:
        return []

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    chunks = splitter.split_text(stripped)
    base_meta = dict(metadata) if metadata else {}

    return [
        Document(
            page_content=chunk,
            metadata={**base_meta, "chunk_index": idx},
        )
        for idx, chunk in enumerate(chunks)
    ]
