import pytest
from langchain_core.documents import Document

from app.ingest import ingest_document
from app.targets import InMemoryDeduplicationStore


class FakeVectorStore:
    def __init__(self) -> None:
        self.calls: list[list[Document]] = []

    def add_documents(self, documents: list[Document]) -> list[str]:
        self.calls.append(list(documents))
        return [f"id-{i}" for i in range(len(documents))]


def test_ingest_document_normal_splits_and_stores_all_chunks():
    store = FakeVectorStore()
    meta = {
        "domain": "infra_devops",
        "target_name": "Terraform",
        "source_url": "https://github.com/hashicorp/terraform/releases",
    }

    count = ingest_document(
        text="0123456789" * 3,
        metadata=meta,
        vector_store=store,
        chunk_size=12,
        chunk_overlap=2,
    )

    assert count == 3
    assert len(store.calls) == 1
    stored_docs = store.calls[0]
    assert [d.page_content for d in stored_docs] == [
        "012345678901",
        "012345678901",
        "0123456789",
    ]
    assert [d.metadata for d in stored_docs] == [
        {
            "domain": "infra_devops",
            "target_name": "Terraform",
            "source_url": "https://github.com/hashicorp/terraform/releases",
            "chunk_index": 0,
        },
        {
            "domain": "infra_devops",
            "target_name": "Terraform",
            "source_url": "https://github.com/hashicorp/terraform/releases",
            "chunk_index": 1,
        },
        {
            "domain": "infra_devops",
            "target_name": "Terraform",
            "source_url": "https://github.com/hashicorp/terraform/releases",
            "chunk_index": 2,
        },
    ]
    assert meta == {
        "domain": "infra_devops",
        "target_name": "Terraform",
        "source_url": "https://github.com/hashicorp/terraform/releases",
    }


@pytest.mark.parametrize("blank_text", ["", "   ", "\n\t"])
def test_ingest_document_empty_text_skips_vector_store_call(blank_text: str):
    store = FakeVectorStore()

    count = ingest_document(
        text=blank_text,
        metadata={"domain": "ai_agent_llm"},
        vector_store=store,
    )

    assert count == 0
    assert store.calls == []


def test_ingest_document_invalid_chunk_params_raises_before_storing():
    store = FakeVectorStore()

    with pytest.raises(ValueError, match="chunk"):
        ingest_document(
            text="Some valid trend report content",
            metadata={"domain": "fullstack_web"},
            vector_store=store,
            chunk_size=50,
            chunk_overlap=50,
        )

    assert store.calls == []


def test_ingest_document_skips_duplicate_source_and_allows_updated_content():
    store = FakeVectorStore()
    dedup = InMemoryDeduplicationStore()
    meta = {
        "domain": "fullstack_web",
        "target_name": "Next.js",
        "source_url": "https://nextjs.org/blog/next-16",
    }

    first_count = ingest_document(
        text="Next.js 16 adds Cache Components.",
        metadata=meta,
        vector_store=store,
        dedup_store=dedup,
        chunk_size=100,
        chunk_overlap=10,
    )
    duplicate_count = ingest_document(
        text="  Next.js 16   adds Cache Components. \n",
        metadata=meta,
        vector_store=store,
        dedup_store=dedup,
        chunk_size=100,
        chunk_overlap=10,
    )
    updated_count = ingest_document(
        text="Next.js 16.3 adds native Rust React Compiler.",
        metadata=meta,
        vector_store=store,
        dedup_store=dedup,
        chunk_size=100,
        chunk_overlap=10,
    )

    assert first_count == 1
    assert duplicate_count == 0
    assert updated_count == 1
    assert len(store.calls) == 2
