from typing import Any

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter


def chunk_text(
    text: str,
    metadata: dict[str, Any] | None = None,
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
    *,
    inject_header: bool = False,
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
    chunk_count = len(chunks)

    header = ""
    if inject_header:
        domain = str(base_meta.get("domain") or "unknown").strip()
        target_name = str(base_meta.get("target_name") or "unknown").strip()
        title = str(base_meta.get("title") or "untitled").strip()
        header = f"[도메인: {domain} | 주제: {target_name} | 제목: {title}]\n"

    return [
        Document(
            page_content=f"{header}{chunk}" if header else chunk,
            metadata={
                **base_meta,
                "chunk_index": idx,
                **({"chunk_count": chunk_count} if inject_header else {}),
            },
        )
        for idx, chunk in enumerate(chunks)
    ]
