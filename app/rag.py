from collections import defaultdict
from typing import Any, Callable, Protocol

import httpx
from langchain_core.documents import Document
from pydantic import BaseModel

from app.config import Settings, settings
from app.ingest import get_vector_store

OLLAMA_MODEL_PRESETS: dict[str, str] = {
    "A": "gemma3:12b",
    "C": "hermes3:8b",
}

_EXCLUDED_MODEL_PREFIXES: tuple[str, ...] = (
    "qwen",
    "deepseek",
    "baai",
    "bge",
    "yi",
    "glm",
    "baichuan",
)


def resolve_ollama_model_name(model_or_preset: str) -> str:
    cleaned = (model_or_preset or "").strip()
    if not cleaned:
        raise ValueError("OLLAMA_MODEL_NAME (or model preset) must not be empty")

    upper_key = cleaned.upper()
    if upper_key == "B":
        raise ValueError("Excluded model preset 'B': Chinese-origin models are not permitted")
    if upper_key in OLLAMA_MODEL_PRESETS:
        return OLLAMA_MODEL_PRESETS[upper_key]

    lower_val = cleaned.lower()
    if any(lower_val.startswith(prefix) for prefix in _EXCLUDED_MODEL_PREFIXES):
        raise ValueError(f"Excluded model '{cleaned}': Chinese-origin models are not permitted")

    if ":" in cleaned:
        name_part, tag_part = cleaned.split(":", 1)
        if not name_part.strip() or not tag_part.strip():
            raise ValueError(f"Invalid model tag format: {cleaned}")

    return cleaned



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


class PGVectorRetriever:
    def __init__(
        self,
        *,
        vector_store: Any | None = None,
        cfg: Settings = settings,
    ) -> None:
        self._store = vector_store if vector_store is not None else get_vector_store(cfg)

    def add_documents(self, documents: list[Document]) -> list[str]:
        return self._store.add_documents(documents)

    def search(
        self,
        query: str,
        *,
        domain: str | None = None,
        target_name: str | None = None,
        k: int = 4,
    ) -> list[Document]:
        metadata_filter: dict[str, Any] = {}
        if domain and domain.strip():
            metadata_filter["domain"] = domain.strip()
        if target_name and target_name.strip():
            metadata_filter["target_name"] = target_name.strip()
        resolved_filter = metadata_filter if metadata_filter else None
        return self._store.similarity_search(query, k=k, filter=resolved_filter)


def _default_ollama_post(url: str, json_payload: dict[str, Any]) -> dict[str, Any]:
    resp = httpx.post(url, json=json_payload, timeout=60.0)
    resp.raise_for_status()
    return resp.json()


class OllamaLLMWrapper:
    def __init__(
        self,
        cfg: Settings,
        *,
        http_post: Callable[[str, dict[str, Any]], dict[str, Any]] = _default_ollama_post,
        model_override: str | None = None,
    ) -> None:
        self.base_url = cfg.ollama_base_url.strip().rstrip("/")
        raw_model = model_override if model_override is not None else cfg.ollama_model_name
        self.model_name = resolve_ollama_model_name(raw_model)
        self._http_post = http_post

    def generate(self, prompt: str) -> str:
        cleaned_prompt = prompt.strip()
        if not cleaned_prompt:
            raise ValueError("prompt must not be empty")
        url = f"{self.base_url}/api/generate"
        payload = {
            "model": self.model_name,
            "prompt": cleaned_prompt,
            "stream": False,
        }
        data = self._http_post(url, payload)
        return str(data.get("response") or "").strip()


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


def get_llm(
    cfg: Settings = settings,
    *,
    ollama_http_post: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
    model_override: str | None = None,
) -> LLMProtocol:
    provider = (cfg.llm_provider or "").strip().lower()
    if provider == "ollama":
        if not cfg.ollama_base_url or not cfg.ollama_base_url.strip():
            raise ValueError("OLLAMA_BASE_URL must not be empty")
        raw_model = model_override if model_override is not None else cfg.ollama_model_name
        if not raw_model or not raw_model.strip():
            raise ValueError("OLLAMA_MODEL_NAME must not be empty")
        post_fn = ollama_http_post if ollama_http_post is not None else _default_ollama_post
        return OllamaLLMWrapper(cfg, http_post=post_fn, model_override=model_override)

    if provider == "anthropic":
        if not cfg.anthropic_api_key or not cfg.anthropic_api_key.strip():
            raise ValueError("ANTHROPIC_API_KEY must be configured")
        return AnthropicLLMWrapper(cfg)

    raise ValueError(f"Unsupported llm_provider: {cfg.llm_provider}")


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
