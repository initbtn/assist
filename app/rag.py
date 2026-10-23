from collections import defaultdict
from typing import Protocol

from langchain_core.documents import Document
from pydantic import BaseModel

from app.config import Settings, settings


class QueryResult(BaseModel):
    answer: str
    sources: list[str]


class RetrieverProtocol(Protocol):
    def search(
        self,
        query: str,
        *,
        domain: str | None = None,
        target_name: str | None = None,
        k: int = 4,
    ) -> list[Document]: ...


class LLMProtocol(Protocol):
    def generate(self, prompt: str) -> str: ...


class FakeMemoryRetriever:
    def __init__(self, docs: list[Document] | None = None) -> None:
        self.docs: list[Document] = list(docs) if docs else []

    def add_documents(self, documents: list[Document]) -> list[str]:
        self.docs.extend(documents)
        return [f"doc-{i}" for i in range(len(documents))]

    def search(
        self,
        query: str,
        *,
        domain: str | None = None,
        target_name: str | None = None,
        k: int = 4,
    ) -> list[Document]:
        items = self.docs
        if domain:
            items = [d for d in items if d.metadata.get("domain") == domain]
        if target_name:
            items = [d for d in items if d.metadata.get("target_name") == target_name]
        return items[:k]


class AnthropicLLMWrapper:
    def __init__(self, cfg: Settings) -> None:
        from langchain_anthropic import ChatAnthropic

        self._chat = ChatAnthropic(
            model=cfg.llm_model_name,
            api_key=cfg.anthropic_api_key,
        )

    def generate(self, prompt: str) -> str:
        msg = self._chat.invoke(prompt)
        return str(msg.content)


def get_llm(cfg: Settings = settings) -> LLMProtocol:
    if not cfg.anthropic_api_key or not cfg.anthropic_api_key.strip():
        raise ValueError("ANTHROPIC_API_KEY must be configured")
    return AnthropicLLMWrapper(cfg)


def answer_question(
    question: str,
    *,
    retriever: RetrieverProtocol,
    llm: LLMProtocol,
    domain: str | None = None,
    target_name: str | None = None,
    k: int = 4,
) -> QueryResult:
    cleaned_q = question.strip()
    if not cleaned_q:
        raise ValueError("question must not be empty")

    docs = retriever.search(
        cleaned_q,
        domain=domain,
        target_name=target_name,
        k=k,
    )
    if not docs:
        return QueryResult(
            answer="저장된 지식 베이스에서 관련된 동향 문서를 찾지 못했습니다.",
            sources=[],
        )

    sources: list[str] = []
    context_blocks: list[str] = []
    for idx, doc in enumerate(docs, start=1):
        url = str(doc.metadata.get("source_url") or "").strip()
        if url and url not in sources:
            sources.append(url)
        context_blocks.append(
            f"[{idx}] ({doc.metadata.get('domain', 'unknown')} / "
            f"{doc.metadata.get('target_name', 'unknown')} | {url})\n{doc.page_content}"
        )

    prompt = (
        "아래 수집된 기술 동향 문서 컨텍스트만을 근거로 질문에 한국어로 명확히 답변하세요.\n\n"
        f"### 컨텍스트\n{chr(10).join(context_blocks)}\n\n"
        f"### 질문\n{cleaned_q}"
    )
    answer = llm.generate(prompt)
    return QueryResult(answer=answer, sources=sources)


def build_morning_brief(
    documents: list[Document],
    *,
    llm: LLMProtocol,
) -> str:
    if not documents:
        return "신규 수집된 동향 문서가 없습니다."

    grouped: dict[str, list[str]] = defaultdict(list)
    for doc in documents:
        domain = str(doc.metadata.get("domain") or "general")
        target = str(doc.metadata.get("target_name") or "unknown")
        url = str(doc.metadata.get("source_url") or "")
        grouped[domain].append(f"- [{target}] ({url}): {doc.page_content}")

    sections = [
        f"## 도메인: {domain}\n" + "\n".join(lines)
        for domain, lines in grouped.items()
    ]
    prompt = (
        "당신은 개발자의 아침 기술 동향 브리핑 어시스턴트입니다.\n"
        "아래 도메인별 신규 수집 내용을 바탕으로 핵심 변화, 실무 영향, 원문 링크를 포함한 아침 브리핑 리포트를 작성하세요.\n\n"
        + "\n\n".join(sections)
    )
    return llm.generate(prompt)
