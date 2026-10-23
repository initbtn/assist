import pytest
from langchain_core.documents import Document

from app.config import Settings
from app.rag import answer_question, build_morning_brief, get_llm


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


def test_get_llm_fails_fast_when_anthropic_api_key_missing():
    cfg = Settings(anthropic_api_key="   ")
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        get_llm(cfg)
