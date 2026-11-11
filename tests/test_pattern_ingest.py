import os
import pytest
from langchain_core.documents import Document

from scripts.ingest_patterns import ingest_all_patterns, parse_pattern_markdown


class MockVectorStore:
    def __init__(self) -> None:
        self.added_docs: list[Document] = []

    def add_documents(self, documents: list[Document]) -> list[str]:
        self.added_docs.extend(documents)
        return [f"id-{i}" for i in range(len(documents))]


def test_parse_pattern_markdown_extracts_metadata(tmp_path):
    pattern_file = tmp_path / "test_pattern.md"
    pattern_file.write_text(
        """# [테스트 패턴]: 아키텍처 규칙
- **분류**: `frontend_architecture`
- **도메인**: `fullstack_web`
- **주제**: `FSD`
- **제목**: `단방향 의존성 규칙`
- **우선순위**: `critical`

### ❌ Anti-Pattern (Bad)
Bad code example

### ✅ Best Practice (Good)
Good code example
""",
        encoding="utf-8",
    )

    parsed = parse_pattern_markdown(str(pattern_file))
    meta = parsed["metadata"]

    assert meta["category"] == "frontend_architecture"
    assert meta["domain"] == "fullstack_web"
    assert meta["target_name"] == "FSD"
    assert meta["title"] == "단방향 의존성 규칙"
    assert meta["priority"] == "critical"
    assert "source_url" in meta


def test_ingest_all_patterns_with_contextual_headers():
    store = MockVectorStore()
    patterns_dir = os.path.join(
        os.path.dirname(__file__), "..", "patterns"
    )

    total_chunks = ingest_all_patterns(patterns_dir, vector_store=store)

    assert total_chunks >= 3
    assert len(store.added_docs) == total_chunks

    # Verify that each indexed chunk has contextual header injected
    for doc in store.added_docs:
        assert doc.page_content.startswith("[도메인:")
        assert "주제:" in doc.page_content
        assert "제목:" in doc.page_content
        assert doc.metadata.get("category") in (
            "frontend_architecture",
            "backend_architecture",
            "architecture_spec",
        )
        assert "chunk_count" in doc.metadata
