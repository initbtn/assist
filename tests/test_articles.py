import json
from pathlib import Path

from langchain_core.documents import Document

from app.articles import (
    InMemoryArticleStore,
    build_briefing_article,
    export_articles_to_web,
    extract_three_line_summary,
    format_telegram_brief_message,
)


def _sample_docs() -> list[Document]:
    return [
        Document(
            page_content="Claude Code v2.1 adds subagent context isolation and MCP native hooks.",
            metadata={
                "domain": "ai_agent_llm",
                "target_name": "Claude Code",
                "title": "Claude Code v2.1 Release",
                "source_url": "https://github.com/anthropics/claude-code/releases/tag/v2.1.0",
            },
        ),
        Document(
            page_content="Next.js 16 ships Cache Components, proxy.ts, and built-in DevTools MCP.",
            metadata={
                "domain": "fullstack_web",
                "target_name": "Next.js",
                "title": "Next.js 16 Release",
                "source_url": "https://nextjs.org/blog/next-16",
            },
        ),
        Document(
            page_content="Kubernetes v1.33 stabilizes sidecar containers and Gateway API updates.",
            metadata={
                "domain": "infra_devops",
                "target_name": "Kubernetes",
                "title": "Kubernetes v1.33",
                "source_url": "https://github.com/kubernetes/kubernetes/releases/tag/v1.33.0",
            },
        ),
    ]


def test_extract_three_line_summary_four_boundary_cases():
    docs = _sample_docs()

    # 1) 정상값: 3줄 불릿 텍스트 -> 정확히 3줄 리스트 반환
    normal_raw = (
        "1. Claude Code v2.1 서브에이전트 격리 및 MCP 훅 추가\n"
        "2. Next.js 16 Cache Components 및 DevTools MCP 기본 탑재\n"
        "3. Kubernetes v1.33 사이드카 컨테이너 정식 안정화"
    )
    res_normal = extract_three_line_summary(normal_raw, fallback_docs=docs)
    assert res_normal == [
        "Claude Code v2.1 서브에이전트 격리 및 MCP 훅 추가",
        "Next.js 16 Cache Components 및 DevTools MCP 기본 탑재",
        "Kubernetes v1.33 사이드카 컨테이너 정식 안정화",
    ]

    # 2) 완전히 틀린 값(빈 문자열/공백) -> fallback_docs 기반으로 정확히 3줄 생성
    res_empty = extract_three_line_summary("   \n  ", fallback_docs=docs)
    assert len(res_empty) == 3
    assert "Claude Code" in res_empty[0]
    assert "Next.js" in res_empty[1]
    assert "Kubernetes" in res_empty[2]

    # 3) 일부만 맞는 값(1줄만 반환된 경우) -> 나머지 2줄을 fallback_docs에서 보충해 정확히 3줄 보장
    res_partial = extract_three_line_summary(
        "- AI 에이전트: Claude Code v2.1 출시",
        fallback_docs=docs,
    )
    assert len(res_partial) == 3
    assert res_partial[0] == "AI 에이전트: Claude Code v2.1 출시"
    assert "Next.js" in res_partial[1]
    assert "Kubernetes" in res_partial[2]

    # 4) 맞지만 헷갈리는 값(마크다운 헤더·빈 줄·5줄 초과 응답) -> 헤더 제외 후 상위 3줄만 정확히 추출
    confusing_raw = (
        "# 오늘의 3줄 요약\n\n"
        "• 첫 번째 핵심 동향 요약입니다.\n"
        "* 두 번째 핵심 동향 요약입니다.\n"
        "- 세 번째 핵심 동향 요약입니다.\n"
        "- 네 번째 초과 줄입니다.\n"
        "- 다섯 번째 초과 줄입니다."
    )
    res_confusing = extract_three_line_summary(confusing_raw, fallback_docs=docs)
    assert res_confusing == [
        "첫 번째 핵심 동향 요약입니다.",
        "두 번째 핵심 동향 요약입니다.",
        "세 번째 핵심 동향 요약입니다.",
    ]


def test_build_briefing_article_and_format_telegram_message():
    docs = _sample_docs()

    class StubLLM:
        def generate(self, prompt: str) -> str:
            return (
                "1. [AI/LLM] Claude Code v2.1 서브에이전트 컨텍스트 격리 및 MCP 훅 지원\n"
                "2. [Full-stack] Next.js 16 Cache Components 및 DevTools MCP 서버 도입\n"
                "3. [Infra] Kubernetes v1.33 사이드카 컨테이너 정식 안정화"
            )

    article = build_briefing_article(
        docs,
        llm=StubLLM(),
        date_str="2026-10-23",
        base_ui_url="https://assist-brief.vercel.app/",
    )

    assert article.slug == "2026-10-23"
    assert article.date == "2026-10-23"
    assert article.article_url == "https://assist-brief.vercel.app/articles/2026-10-23"
    assert len(article.summary_lines) == 3
    assert len(article.sections) == 3

    msg = format_telegram_brief_message(article)
    assert "1. [AI/LLM] Claude Code v2.1" in msg
    assert "2. [Full-stack] Next.js 16" in msg
    assert "3. [Infra] Kubernetes v1.33" in msg
    assert "https://assist-brief.vercel.app/articles/2026-10-23" in msg


def test_article_store_and_export_to_web(tmp_path: Path):
    docs = _sample_docs()
    article = build_briefing_article(
        docs,
        llm=None,
        date_str="2026-10-23",
        base_ui_url="https://assist-brief.vercel.app",
    )

    store = InMemoryArticleStore()
    store.save(article)

    fetched = store.get("2026-10-23")
    assert fetched is not None
    assert fetched.slug == "2026-10-23"
    assert len(store.list_articles()) == 1

    out_file = export_articles_to_web(store.list_articles(), web_dir=tmp_path)
    assert out_file == tmp_path / "data" / "articles.json"
    assert out_file.exists()

    loaded = json.loads(out_file.read_text(encoding="utf-8"))
    assert len(loaded["articles"]) == 1
    assert loaded["articles"][0]["slug"] == "2026-10-23"
    assert (
        loaded["articles"][0]["article_url"]
        == "https://assist-brief.vercel.app/articles/2026-10-23"
    )
