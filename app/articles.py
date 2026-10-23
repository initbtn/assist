import json
import re
from collections import defaultdict
from datetime import date
from pathlib import Path

from langchain_core.documents import Document
from pydantic import BaseModel, Field

from app.rag import LLMProtocol

DOMAIN_LABELS: dict[str, str] = {
    "ai_agent_llm": "AI 에이전트 & LLM",
    "fullstack_web": "풀스택 웹 (React · Next.js · NestJS)",
    "infra_devops": "인프라 & DevOps",
}

_BULLET_PREFIX_RE = re.compile(r"^(?:[0-9]+[.)]\s*|[-*•]\s*)+")


class ArticleItem(BaseModel):
    target_name: str
    title: str
    summary: str
    source_url: str


class ArticleSection(BaseModel):
    domain: str
    domain_label: str
    items: list[ArticleItem] = Field(default_factory=list)


class BriefingArticle(BaseModel):
    slug: str
    date: str
    title: str
    summary_lines: list[str]
    sections: list[ArticleSection]
    article_url: str


def _clean_summary_line(line: str) -> str:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return ""
    cleaned = _BULLET_PREFIX_RE.sub("", stripped).strip()
    return cleaned


def _build_fallback_lines(docs: list[Document] | None) -> list[str]:
    fallback: list[str] = []
    if docs:
        seen_targets: set[str] = set()
        for doc in docs:
            target = str(doc.metadata.get("target_name") or "기술 동향").strip()
            if target in seen_targets:
                continue
            seen_targets.add(target)
            first_line = doc.page_content.strip().splitlines()[0].strip() if doc.page_content.strip() else ""
            snippet = first_line[:90] + ("…" if len(first_line) > 90 else "")
            candidate = f"{target}: {snippet}" if snippet else f"{target} 최신 동향 업데이트"
            fallback.append(candidate)
            if len(fallback) >= 3:
                break

    defaults = [
        "AI 에이전트 및 LLM 도구 생태계 최신 릴리스 동향 점검",
        "풀스택 웹(React · Next.js · NestJS) 핵심 기능 업데이트 요약",
        "인프라 및 클라우드 네이티브(Kubernetes · DevOps) 안정화 동향",
    ]
    for item in defaults:
        if len(fallback) >= 3:
            break
        if item not in fallback:
            fallback.append(item)

    return fallback[:3]


def extract_three_line_summary(
    raw_text: str,
    *,
    fallback_docs: list[Document] | None = None,
) -> list[str]:
    lines: list[str] = []
    for raw_line in (raw_text or "").splitlines():
        cleaned = _clean_summary_line(raw_line)
        if cleaned and cleaned not in lines:
            lines.append(cleaned)
        if len(lines) >= 3:
            return lines[:3]

    fallback_candidates = _build_fallback_lines(fallback_docs)
    for fb in fallback_candidates:
        if len(lines) >= 3:
            break
        target_prefix = fb.split(":", 1)[0].strip()
        if fb not in lines and not any(target_prefix in existing for existing in lines):
            lines.append(fb)

    for fb in fallback_candidates:
        if len(lines) >= 3:
            break
        if fb not in lines:
            lines.append(fb)

    return lines[:3]


def build_briefing_article(
    documents: list[Document],
    *,
    llm: LLMProtocol | None = None,
    date_str: str | None = None,
    title: str | None = None,
    base_ui_url: str = "https://assist-brief.vercel.app",
) -> BriefingArticle:
    resolved_date = (date_str or date.today().isoformat()).strip()
    slug = resolved_date
    resolved_title = (title or f"{resolved_date} 개발 기술 동향 브리핑").strip()
    normalized_base = base_ui_url.strip().rstrip("/")
    article_url = f"{normalized_base}/articles/{slug}"

    grouped_items: dict[str, list[ArticleItem]] = defaultdict(list)
    seen_keys: set[tuple[str, str, str]] = set()

    for doc in documents:
        domain = str(doc.metadata.get("domain") or "general").strip()
        target_name = str(doc.metadata.get("target_name") or "Tech").strip()
        item_title = str(doc.metadata.get("title") or f"{target_name} 업데이트").strip()
        source_url = str(doc.metadata.get("source_url") or "").strip()
        content = doc.page_content.strip()
        dedup_key = (domain, target_name, source_url or item_title)
        if dedup_key in seen_keys:
            continue
        seen_keys.add(dedup_key)
        grouped_items[domain].append(
            ArticleItem(
                target_name=target_name,
                title=item_title,
                summary=content,
                source_url=source_url,
            )
        )

    sections: list[ArticleSection] = []
    for domain, items in grouped_items.items():
        sections.append(
            ArticleSection(
                domain=domain,
                domain_label=DOMAIN_LABELS.get(domain, domain),
                items=items,
            )
        )

    raw_llm_summary = ""
    if llm is not None and documents:
        context_lines = [
            f"- [{d.metadata.get('domain', 'general')}/{d.metadata.get('target_name', 'unknown')}] {d.page_content}"
            for d in documents[:15]
        ]
        prompt = (
            "당신은 개발자 모닝 브리핑 에디터입니다.\n"
            "아래 수집된 기술 동향을 바탕으로 오늘의 핵심 동향을 정확히 3줄(1. / 2. / 3.)로만 요약하세요.\n\n"
            + "\n".join(context_lines)
        )
        raw_llm_summary = llm.generate(prompt)

    summary_lines = extract_three_line_summary(
        raw_llm_summary,
        fallback_docs=documents,
    )

    return BriefingArticle(
        slug=slug,
        date=resolved_date,
        title=resolved_title,
        summary_lines=summary_lines,
        sections=sections,
        article_url=article_url,
    )


def format_telegram_brief_message(article: BriefingArticle) -> str:
    three_lines = extract_three_line_summary(
        "\n".join(article.summary_lines),
        fallback_docs=None,
    )
    numbered = "\n".join(
        f"{idx}. {line}" for idx, line in enumerate(three_lines, start=1)
    )
    return (
        f"🌅 {article.title}\n\n"
        f"{numbered}\n\n"
        f"🔗 상세 아티클 보기: {article.article_url}"
    )


class InMemoryArticleStore:
    def __init__(self, initial: list[BriefingArticle] | None = None) -> None:
        self._by_slug: dict[str, BriefingArticle] = {}
        for art in initial or []:
            self._by_slug[art.slug] = art

    def save(self, article: BriefingArticle) -> BriefingArticle:
        self._by_slug[article.slug] = article
        return article

    def get(self, slug: str) -> BriefingArticle | None:
        return self._by_slug.get(slug.strip())

    def list_articles(self) -> list[BriefingArticle]:
        return sorted(
            self._by_slug.values(),
            key=lambda a: a.date,
            reverse=True,
        )


def export_articles_to_web(
    articles: list[BriefingArticle],
    *,
    web_dir: Path,
) -> Path:
    data_dir = Path(web_dir) / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    out_file = data_dir / "articles.json"
    payload = {
        "articles": [art.model_dump() for art in articles],
    }
    out_file.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return out_file
