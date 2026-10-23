from typing import Any

import pytest
from langchain_core.documents import Document

from app.config import Settings
from app.rag import (
    OllamaLLMWrapper,
    PGVectorRetriever,
    answer_question,
    build_morning_brief,
    get_llm,
)


class FakeRetriever:
    def __init__(self, docs: list[Document]) -> None:
        self.docs = docs
        self.queries: list[tuple[str, str | None, str | None]] = []

    def search(
        self,
        query: str,
        *,
        domain: str | None = None,
        target_name: str | None = None,
        k: int = 4,
    ) -> list[Document]:
        self.queries.append((query, domain, target_name))
        results = self.docs
        if domain:
            results = [d for d in results if d.metadata.get("domain") == domain]
        if target_name:
            results = [
                d for d in results if d.metadata.get("target_name") == target_name
            ]
        return results[:k]


class FakeLLM:
    def __init__(self, response_text: str) -> None:
        self.response_text = response_text
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.response_text


def test_answer_question_filters_and_deduplicates_sources():
    docs = [
        Document(
            page_content="Next.js 16 introduces Cache Components with use cache.",
            metadata={
                "domain": "fullstack_web",
                "target_name": "Next.js",
                "source_url": "https://nextjs.org/blog/next-16",
                "chunk_index": 0,
            },
        ),
        Document(
            page_content="Next.js 16 also ships native DevTools MCP server.",
            metadata={
                "domain": "fullstack_web",
                "target_name": "Next.js",
                "source_url": "https://nextjs.org/blog/next-16",
                "chunk_index": 1,
            },
        ),
        Document(
            page_content="Terraform 1.10 adds state locking improvements.",
            metadata={
                "domain": "infra_devops",
                "target_name": "Terraform",
                "source_url": "https://github.com/hashicorp/terraform/releases",
                "chunk_index": 0,
            },
        ),
    ]
    retriever = FakeRetriever(docs)
    llm = FakeLLM("Next.js 16은 Cache Components와 MCP 서버를 도입했습니다.")

    result = answer_question(
        "Next.js 16의 핵심 변화는?",
        retriever=retriever,
        llm=llm,
        domain="fullstack_web",
    )

    assert result.answer == "Next.js 16은 Cache Components와 MCP 서버를 도입했습니다."
    assert result.sources == ["https://nextjs.org/blog/next-16"]
    assert len(llm.prompts) == 1
    assert "Cache Components" in llm.prompts[0]
    assert "Terraform" not in llm.prompts[0]


def test_answer_question_no_matching_docs_skips_llm():
    retriever = FakeRetriever([])
    llm = FakeLLM("Should not be called")

    result = answer_question(
        "존재하지 않는 기술 동향은?",
        retriever=retriever,
        llm=llm,
    )

    assert result.sources == []
    assert "관련된 동향 문서" in result.answer
    assert llm.prompts == []


@pytest.mark.parametrize("blank_q", ["", "   ", "\n\t"])
def test_answer_question_rejects_empty_question(blank_q: str):
    retriever = FakeRetriever([])
    llm = FakeLLM("unused")

    with pytest.raises(ValueError, match="question"):
        answer_question(blank_q, retriever=retriever, llm=llm)


def test_build_morning_brief_groups_by_domain_and_handles_empty():
    llm = FakeLLM("📊 아침 기술 동향 브리핑 요약본")
    docs = [
        Document(
            page_content="Claude Code adds subagent orchestration.",
            metadata={
                "domain": "ai_agent_llm",
                "target_name": "Claude Code",
                "source_url": "https://github.com/anthropics/claude-code",
            },
        ),
        Document(
            page_content="NestJS 12 migrates to ESM.",
            metadata={
                "domain": "fullstack_web",
                "target_name": "NestJS",
                "source_url": "https://github.com/nestjs/nest/pull/16391",
            },
        ),
    ]

    brief = build_morning_brief(docs, llm=llm)
    assert brief == "📊 아침 기술 동향 브리핑 요약본"
    assert len(llm.prompts) == 1
    assert "ai_agent_llm" in llm.prompts[0]
    assert "fullstack_web" in llm.prompts[0]

    empty_llm = FakeLLM("Should not run")
    empty_brief = build_morning_brief([], llm=empty_llm)
    assert "신규 수집된 동향 문서가 없습니다" in empty_brief
    assert empty_llm.prompts == []


def test_ollama_llm_wrapper_and_get_llm_four_boundary_cases():
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_post(url: str, payload: dict[str, Any]) -> dict[str, Any]:
        calls.append((url, payload))
        return {"response": "1. AI 요약\n2. 웹 요약\n3. 인프라 요약"}

    # 1) 정상값: 기본 ollama provider (hermes3:8b)
    cfg_normal = Settings(
        llm_provider="ollama",
        ollama_base_url="http://ollama-server:11434/",
        ollama_model_name="hermes3:8b",
    )
    llm_inst = get_llm(cfg_normal, ollama_http_post=fake_post)
    assert isinstance(llm_inst, OllamaLLMWrapper)
    out = llm_inst.generate("오늘 동향 3줄 요약")
    assert out == "1. AI 요약\n2. 웹 요약\n3. 인프라 요약"
    assert calls == [
        (
            "http://ollama-server:11434/api/generate",
            {
                "model": "hermes3:8b",
                "prompt": "오늘 동향 3줄 요약",
                "stream": False,
            },
        )
    ]

    # 2) 맞지만 헷갈리는 값: 대소문자 및 앞뒤 공백 포함 ("  OLLAMA  ")
    cfg_confusing = Settings(
        llm_provider="  OLLAMA  ",
        ollama_base_url="http://10.0.0.5:11434",
        ollama_model_name="llama3.3:8b",
    )
    llm_confusing = get_llm(cfg_confusing, ollama_http_post=fake_post)
    assert isinstance(llm_confusing, OllamaLLMWrapper)

    # 3) 일부만 맞는 값: provider는 ollama인데 base_url 또는 model_name이 비어 있음 / 빈 프롬프트
    with pytest.raises(ValueError, match="OLLAMA_BASE_URL"):
        get_llm(Settings(llm_provider="ollama", ollama_base_url="   "))
    with pytest.raises(ValueError, match="OLLAMA_MODEL_NAME"):
        get_llm(Settings(llm_provider="ollama", ollama_model_name="   "))
    with pytest.raises(ValueError, match="prompt"):
        llm_inst.generate("   ")

    # 4) 완전히 틀린 값: 지원하지 않는 provider 또는 anthropic 키 누락
    with pytest.raises(ValueError, match="Unsupported llm_provider"):
        get_llm(Settings(llm_provider="unknown_provider"))
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        get_llm(Settings(llm_provider="anthropic", anthropic_api_key="   "))


def test_pgvector_retriever_delegates_add_and_metadata_filtered_search():
    class FakePGVectorStore:
        def __init__(self) -> None:
            self.added: list[Document] = []
            self.search_calls: list[tuple[str, int, dict[str, Any] | None]] = []

        def add_documents(self, documents: list[Document]) -> list[str]:
            self.added.extend(documents)
            return [f"id-{i}" for i in range(len(documents))]

        def similarity_search(
            self,
            query: str,
            k: int = 4,
            filter: dict[str, Any] | None = None,
        ) -> list[Document]:
            self.search_calls.append((query, k, filter))
            return self.added[:k]

    fake_store = FakePGVectorStore()
    pg_retriever = PGVectorRetriever(vector_store=fake_store)

    doc = Document(
        page_content="Hermes 3 supports structured tool calling.",
        metadata={"domain": "ai_agent_llm", "target_name": "Hermes"},
    )
    ids = pg_retriever.add_documents([doc])
    assert ids == ["id-0"]

    res_filtered = pg_retriever.search(
        "Hermes tool calling",
        domain="ai_agent_llm",
        target_name="Hermes",
        k=3,
    )
    assert len(res_filtered) == 1
    assert fake_store.search_calls[-1] == (
        "Hermes tool calling",
        3,
        {"domain": "ai_agent_llm", "target_name": "Hermes"},
    )

    pg_retriever.search("general query", k=5)
    assert fake_store.search_calls[-1] == ("general query", 5, None)
