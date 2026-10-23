from typing import Any, Callable

import httpx
from pydantic import BaseModel

from app.ingest import VectorStoreProtocol, ingest_document
from app.targets import DeduplicationStoreProtocol, InMemoryTargetStore


class CollectedItem(BaseModel):
    title: str
    content: str
    source_url: str
    published_at: str = ""


class CollectionSummary(BaseModel):
    checked_targets: int
    fetched_items: int
    ingested_documents: int
    ingested_chunks: int
    skipped_duplicates: int
    seeded_chunks: int = 0


def _default_github_get(url: str) -> list[dict[str, Any]]:
    resp = httpx.get(
        url,
        headers={"Accept": "application/vnd.github+json"},
        timeout=15.0,
    )
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, list) else []


def _validate_github_repo(repo: str) -> str:
    cleaned = repo.strip()
    parts = cleaned.split("/")
    if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
        raise ValueError(f"Invalid GitHub repo format (expected 'owner/repo'): {repo}")
    return f"{parts[0].strip()}/{parts[1].strip()}"


def fetch_github_releases(
    repo: str,
    *,
    http_get: Callable[[str], list[dict[str, Any]]] = _default_github_get,
    per_page: int = 3,
) -> list[CollectedItem]:
    normalized_repo = _validate_github_repo(repo)
    url = f"https://api.github.com/repos/{normalized_repo}/releases?per_page={per_page}"
    raw_items = http_get(url)

    items: list[CollectedItem] = []
    for entry in raw_items:
        if entry.get("draft") is True:
            continue
        tag = str(entry.get("tag_name") or "").strip()
        name = str(entry.get("name") or "").strip()
        body = str(entry.get("body") or "").strip()
        html_url = str(entry.get("html_url") or "").strip()
        published_at = str(entry.get("published_at") or "").strip()

        if not (tag or name or body) or not (body or name):
            continue

        title = f"{name} ({tag})" if name and tag and name != tag else (name or tag)
        content = f"# {title}\n\n{body}".strip()
        items.append(
            CollectedItem(
                title=title,
                content=content,
                source_url=html_url,
                published_at=published_at,
            )
        )
    return items


def collect_and_ingest_targets(
    *,
    target_store: InMemoryTargetStore,
    vector_store: VectorStoreProtocol,
    dedup_store: DeduplicationStoreProtocol,
    http_get: Callable[[str], list[dict[str, Any]]] = _default_github_get,
    domain: str | None = None,
    per_target_limit: int = 3,
) -> CollectionSummary:
    targets = target_store.list_targets(domain=domain, active_only=True)
    checked = 0
    fetched = 0
    ingested_docs = 0
    ingested_chunks = 0
    skipped = 0

    for target in targets:
        if target.source_type != "github_repo":
            continue
        repo = str(target.source_config.get("repo") or "").strip()
        if not repo:
            continue

        checked += 1
        releases = fetch_github_releases(
            repo,
            http_get=http_get,
            per_page=per_target_limit,
        )
        fetched += len(releases)

        for item in releases:
            chunks = ingest_document(
                text=item.content,
                metadata={
                    "domain": target.domain,
                    "target_name": target.name,
                    "title": item.title,
                    "source_url": item.source_url,
                    "source_type": "github_release",
                    "published_at": item.published_at,
                },
                vector_store=vector_store,
                dedup_store=dedup_store,
            )
            if chunks > 0:
                ingested_docs += 1
                ingested_chunks += chunks
            else:
                skipped += 1

    return CollectionSummary(
        checked_targets=checked,
        fetched_items=fetched,
        ingested_documents=ingested_docs,
        ingested_chunks=ingested_chunks,
        skipped_duplicates=skipped,
    )


INITIAL_SEED_DOCUMENTS: tuple[dict[str, Any], ...] = (
    {
        "domain": "fullstack_web",
        "target_name": "Next.js",
        "source_url": "https://nextjs.org/blog/next-16",
        "source_type": "research_report",
        "published_at": "2026-10-23T00:00:00Z",
        "text": (
            "Next.js 16 ~ 16.3 핵심 동향: 암묵적 캐싱을 대체하는 명시적 Cache Components('use cache' 디렉티브), "
            "AI 에이전트 디버깅용 네이티브 DevTools MCP 서버(/_next/mcp), Server Actions read-your-writes를 위한 "
            "updateTag(), 실험적 Rust 기반 React Compiler(빌드 20~50% 가속). LLM/RAG 백엔드 연동은 App Router "
            "Route Handlers(HTTP+SSE)가 표준이며 AI SDK RSC는 공식 중단됨."
        ),
    },
    {
        "domain": "fullstack_web",
        "target_name": "NestJS",
        "source_url": "https://github.com/nestjs/nest/pull/16391",
        "source_type": "research_report",
        "published_at": "2026-10-23T00:00:00Z",
        "text": (
            "NestJS 12 핵심 동향: 공식 패키지 전면 ESM 전환(Node 20.19+/22.12+ require(esm) 호환), "
            "데코레이터에서 Standard Schema 지원으로 class-validator 대신 Zod, Valibot, ArkType 직접 사용 가능. "
            "RAG 아키텍처에서는 PostgreSQL pgvector와 멀티 프로바이더(OpenAI, Anthropic, Gemini) 어댑터 구조가 표준."
        ),
    },
    {
        "domain": "fullstack_web",
        "target_name": "React AI UI",
        "source_url": "https://vercel.com/changelog/ai-sdk-7",
        "source_type": "research_report",
        "published_at": "2026-10-23T00:00:00Z",
        "text": (
            "React AI UI 생태계 동향: assistant-ui가 LangGraph, LangChain, Vercel AI SDK 어댑터를 지원하는 "
            "Radix 스타일 헤드리스 채팅 UI 표준으로 부상. Vercel AI SDK v7은 ESM 전용(Node 22+)으로 전환하고 "
            "DefaultChatTransport 및 ToolLoopAgent/WorkflowAgent 프리미티브를 도입함."
        ),
    },
    {
        "domain": "ai_agent_llm",
        "target_name": "Open-Source RAG & Digest Benchmarks",
        "source_url": "https://github.com/khoj-ai/khoj",
        "source_type": "research_report",
        "published_at": "2026-10-23T00:00:00Z",
        "text": (
            "유사 도메인 오픈소스 벤치마크: TrendRadar(다중 플랫폼 트렌드·RSS 수집 + AI 브리핑 Telegram 푸시 + MCP 서버), "
            "khoj(Python + FastAPI + pgvector 세컨드 브레인 + 일일 브리핑 자동화 + Telegram 봇), "
            "follow-builders(고신호 핵심 빌더/공식 저장소 선별 추적), ai-news-brief(해시 및 pgvector 기반 중복 제거)."
        ),
    },
    {
        "domain": "infra_devops",
        "target_name": "Cloud-Native & DevSecOps Stack",
        "source_url": "https://github.com/initbtn/assist/blob/main/docs/plan.md",
        "source_type": "research_report",
        "published_at": "2026-10-23T00:00:00Z",
        "text": (
            "인프라 & DevOps 리서치 타겟: Kubernetes, Terraform/IaC, Docker 컨테이너 런타임, GitHub Actions CI/CD, "
            "Cloudflare(Workers, R2, Zero Trust), OpenTelemetry/Prometheus 관측성 및 pass 시크릿 스토어 기반 무평문 런타임 주입."
        ),
    },
)


def seed_initial_knowledge(
    *,
    vector_store: VectorStoreProtocol,
    dedup_store: DeduplicationStoreProtocol,
) -> int:
    total_chunks = 0
    for item in INITIAL_SEED_DOCUMENTS:
        chunks = ingest_document(
            text=item["text"],
            metadata={
                "domain": item["domain"],
                "target_name": item["target_name"],
                "source_url": item["source_url"],
                "source_type": item["source_type"],
                "published_at": item["published_at"],
            },
            vector_store=vector_store,
            dedup_store=dedup_store,
        )
        total_chunks += chunks
    return total_chunks
