from typing import Any, Callable

import httpx
from pydantic import BaseModel, Field

from app.config import settings
from app.ingest import VectorStoreProtocol, ingest_document
from app.targets import DeduplicationStoreProtocol, InMemoryTargetStore


def build_github_headers(token: str | None = None) -> dict[str, str]:
    headers: dict[str, str] = {"Accept": "application/vnd.github+json"}
    cleaned = (token or "").strip()
    if cleaned:
        headers["Authorization"] = f"Bearer {cleaned}"
    return headers



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
        headers=build_github_headers(settings.resolved_github_token()),
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

# ==============================================================================
# Daily Intelligence (arXiv, Hugging Face, GitHub Trending) & Notion Bridge
# ==============================================================================
import xml.etree.ElementTree as ET


def parse_arxiv_papers(xml_text: str) -> list[CollectedItem]:
    items: list[CollectedItem] = []
    root = ET.fromstring(xml_text)
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    for entry in root.findall("atom:entry", ns):
        title = entry.findtext("atom:title", default="", namespaces=ns).strip().replace("\n", " ")
        summary = entry.findtext("atom:summary", default="", namespaces=ns).strip().replace("\n", " ")
        source_url = entry.findtext("atom:id", default="", namespaces=ns).strip()
        published = entry.findtext("atom:published", default="", namespaces=ns).strip()
        if title:
            items.append(
                CollectedItem(
                    title=title,
                    content=summary,
                    source_url=source_url,
                    published_at=published,
                )
            )
    return items


def parse_hf_daily_papers(data: list[dict[str, Any]]) -> list[CollectedItem]:
    items: list[CollectedItem] = []
    for entry in data:
        paper_id = entry.get("id") or entry.get("paper", {}).get("id", "")
        title = entry.get("title") or entry.get("paper", {}).get("title", "")
        summary = entry.get("summary") or entry.get("paper", {}).get("summary", "")
        published = entry.get("publishedAt") or entry.get("published", "")
        source_url = f"https://huggingface.co/papers/{paper_id}" if paper_id else ""
        if title:
            items.append(
                CollectedItem(
                    title=title.strip(),
                    content=summary.strip(),
                    source_url=source_url,
                    published_at=published,
                )
            )
    return items


def parse_github_trending(data: list[dict[str, Any]]) -> list[CollectedItem]:
    items: list[CollectedItem] = []
    for repo in data:
        name = repo.get("name") or repo.get("full_name", "")
        stars = repo.get("stargazers_count", 0)
        desc = repo.get("description", "") or ""
        url = repo.get("html_url", "")
        if name:
            title = f"{name} (⭐ {stars})" if stars else name
            items.append(
                CollectedItem(
                    title=title,
                    content=desc,
                    source_url=url,
                    published_at="",
                )
            )
    return items


def format_daily_intelligence_report(items: list[CollectedItem], title: str = "📡 데일리 AI 논문/트렌드 브리핑") -> str:
    lines = [f"<b>{title}</b>\n"]
    for i, it in enumerate(items, start=1):
        lines.append(f"{i}. <b>{it.title}</b>")
        if it.content:
            short_desc = it.content[:150] + "..." if len(it.content) > 150 else it.content
            lines.append(f"   <i>{short_desc}</i>")
        lines.append(f"   🔗 <a href=\"{it.source_url}\">원문 링크</a>\n")
    return "\n".join(lines)


def _post_to_notion_api(payload: dict[str, Any], token: str) -> str:
    import json, urllib.request
    req = urllib.request.Request(
        "https://api.notion.com/v1/pages",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=10.0) as resp:
        res = json.loads(resp.read().decode("utf-8"))
        return res.get("id", "")


def export_item_to_notion_backlog(item: CollectedItem, token: str, db_id: str) -> str:
    payload = {
        "parent": {"database_id": db_id},
        "icon": {"type": "emoji", "emoji": "📡"},
        "properties": {
            "Name": {
                "title": [{"type": "text", "text": {"content": item.title}}]
            },
            "Status": {"status": {"name": "1. Backlog"}},
            "Type": {"select": {"name": "리서치"}},
            "Topic": {"select": {"name": "🦜 LangChain & Agent"}},
            "GitHub PR": {"url": item.source_url if item.source_url.startswith("http") else None},
        },
        "children": [
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [
                        {"type": "text", "text": {"content": item.content or "내용 없음"}}
                    ]
                },
            }
        ],
    }
    return _post_to_notion_api(payload, token)

# ==============================================================================
# Security Knowledge Base Items (CWE, CAPEC, CVE)
# ==============================================================================

class CweRecordItem(BaseModel):
    cwe_id: str
    name: str
    abstraction: str = ""
    structure: str = ""
    status: str = "Stable"
    description: str
    extended_description: str = ""
    likelihood_of_exploit: str = "Medium"
    mitigations: list[dict[str, Any]] = Field(default_factory=list)


class CapecRecordItem(BaseModel):
    capec_id: str
    name: str
    abstraction: str = ""
    status: str = "Stable"
    summary: str
    prerequisites: str = ""
    severity: str = "Medium"
    likelihood_of_attack: str = "Medium"
    related_cwe_ids: list[str] = Field(default_factory=list)
    attack_steps: list[dict[str, Any]] = Field(default_factory=list)
    mitigations: list[Any] = Field(default_factory=list)


class CveRecordItem(BaseModel):
    cve_id: str
    published_at: str
    last_modified_at: str
    severity: str
    cvss_score: float | None = None
    cwe_ids: list[str] = Field(default_factory=list)
    affected_packages: list[dict[str, Any]] = Field(default_factory=list)
    summary_en: str
    summary_ko: str = ""
    action_guide_ko: str = ""
    source_url: str = ""


def parse_cwe_sample(d: dict[str, Any]) -> CweRecordItem:
    raw_id = str(d.get("ID") or d.get("cwe_id") or "").strip()
    cwe_id = raw_id if raw_id.upper().startswith("CWE-") else f"CWE-{raw_id}"
    return CweRecordItem(
        cwe_id=cwe_id,
        name=str(d.get("Name") or d.get("name") or "").strip(),
        abstraction=str(d.get("Abstraction") or "").strip(),
        structure=str(d.get("Structure") or "").strip(),
        status=str(d.get("Status") or "Stable").strip(),
        description=str(d.get("Description") or "").strip(),
        extended_description=str(d.get("Extended_Description") or "").strip(),
        likelihood_of_exploit=str(d.get("Likelihood_Of_Exploit") or "Medium").strip(),
        mitigations=list(d.get("Mitigations") or []),
    )


def parse_capec_sample(d: dict[str, Any]) -> CapecRecordItem:
    raw_id = str(d.get("ID") or d.get("capec_id") or "").strip()
    capec_id = raw_id if raw_id.upper().startswith("CAPEC-") else f"CAPEC-{raw_id}"
    
    # Normalize related CWEs
    raw_cwes = d.get("Related_Weaknesses") or d.get("related_cwe_ids") or []
    related_cwes = []
    for c in raw_cwes:
        s = str(c).strip()
        if s:
            related_cwes.append(s if s.upper().startswith("CWE-") else f"CWE-{s}")

    return CapecRecordItem(
        capec_id=capec_id,
        name=str(d.get("Name") or d.get("name") or "").strip(),
        abstraction=str(d.get("Abstraction") or "").strip(),
        status=str(d.get("Status") or "Stable").strip(),
        summary=str(d.get("Summary") or "").strip(),
        prerequisites=str(d.get("Prerequisites") or "").strip(),
        severity=str(d.get("Severity") or "Medium").strip(),
        likelihood_of_attack=str(d.get("Likelihood") or "Medium").strip(),
        related_cwe_ids=related_cwes,
        attack_steps=list(d.get("Attack_Steps") or []),
        mitigations=list(d.get("Mitigations") or []),
    )


def parse_nvd_cve_item(d: dict[str, Any]) -> CveRecordItem:
    cve_data = d.get("cve", d)
    cve_id = str(cve_data.get("id") or "").strip()
    published = str(cve_data.get("published") or "").strip()
    last_mod = str(cve_data.get("lastModified") or "").strip()

    # Descriptions
    desc_list = cve_data.get("descriptions") or []
    summary_en = ""
    for item in desc_list:
        if item.get("lang") == "en":
            summary_en = str(item.get("value") or "").strip()
            break
    if not summary_en and desc_list:
        summary_en = str(desc_list[0].get("value") or "").strip()

    # Metrics CVSS V3.1
    metrics = cve_data.get("metrics") or {}
    cvss_v31 = metrics.get("cvssMetricV31") or []
    score = None
    severity = "MEDIUM"
    if cvss_v31:
        cvss_data = cvss_v31[0].get("cvssData") or {}
        score = cvss_data.get("baseScore")
        severity = str(cvss_data.get("baseSeverity") or "MEDIUM").upper()

    # CWE Weaknesses
    cwe_ids = []
    for w in cve_data.get("weaknesses") or []:
        for desc in w.get("description") or []:
            val = str(desc.get("value") or "").strip()
            if val and val.upper().startswith("CWE-"):
                cwe_ids.append(val)

    # Affected packages (CPE parse)
    affected_packages = []
    for conf in cve_data.get("configurations") or []:
        for node in conf.get("nodes") or []:
            for cpe in node.get("cpeMatch") or []:
                criteria = str(cpe.get("criteria") or "")
                parts = criteria.split(":")
                pkg = parts[4] if len(parts) > 4 else criteria
                version_end = cpe.get("versionEndExcluding") or cpe.get("versionEndIncluding") or ""
                affected_packages.append({"package": pkg, "version_end": version_end, "criteria": criteria})

    return CveRecordItem(
        cve_id=cve_id,
        published_at=published,
        last_modified_at=last_mod,
        severity=severity,
        cvss_score=score,
        cwe_ids=cwe_ids,
        affected_packages=affected_packages,
        summary_en=summary_en,
        source_url=f"https://nvd.nist.gov/vuln/detail/{cve_id}" if cve_id else "",
    )
