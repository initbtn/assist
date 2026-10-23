import json
from pathlib import Path

import pytest
from langchain_core.documents import Document

from app.articles import (
    InMemoryArticleStore,
    ModelBriefComparison,
    build_briefing_article,
    build_vercel_deployment_payload,
    compare_briefing_models,
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


def test_article_store_and_export_to_web_and_vercel_payload(tmp_path: Path):
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

    # article.html 템플릿이 있을 때 정적 상세 경로 파일(articles/<slug>/index.html)까지 생성하는지 검증
    (tmp_path / "index.html").write_text("<html>home</html>", encoding="utf-8")
    (tmp_path / "article.html").write_text("<html>detail</html>", encoding="utf-8")
    (tmp_path / "vercel.json").write_text("{}", encoding="utf-8")

    out_file = export_articles_to_web(store.list_articles(), web_dir=tmp_path)
    assert out_file == tmp_path / "data" / "articles.json"
    assert out_file.exists()

    static_detail = tmp_path / "articles" / "2026-10-23" / "index.html"
    assert static_detail.exists()
    assert static_detail.read_text(encoding="utf-8") == "<html>detail</html>"

    loaded = json.loads(out_file.read_text(encoding="utf-8"))
    assert len(loaded["articles"]) == 1
    assert loaded["articles"][0]["slug"] == "2026-10-23"

    payload = build_vercel_deployment_payload(tmp_path, project_name="assist-brief")
    assert payload["name"] == "assist-brief"
    assert payload["target"] == "production"
    file_paths = {f["file"] for f in payload["files"]}
    assert "index.html" in file_paths
    assert "article.html" in file_paths
    assert "data/articles.json" in file_paths
    assert "articles/2026-10-23/index.html" in file_paths

    with pytest.raises(ValueError, match="web_dir"):
        build_vercel_deployment_payload(tmp_path / "non-existent")


def test_compare_briefing_models_four_boundary_cases():
    docs = _sample_docs()

    class StubModelLLM:
        def __init__(self, tag: str, lines: list[str]) -> None:
            self.tag = tag
            self.lines = lines

        def generate(self, prompt: str) -> str:
            return "\n".join(self.lines)

    llm_a = StubModelLLM(
        "gemma3:12b",
        [
            "1. [Gemma3] Claude Code v2.1 서브에이전트 컨텍스트 격리 강화",
            "2. [Gemma3] Next.js 16 Cache Components 및 MCP 서버 내장",
            "3. [Gemma3] Kubernetes v1.33 사이드카 컨테이너 안정화",
        ],
    )
    llm_c = StubModelLLM(
        "hermes3:8b",
        [
            "1. [Hermes3] Claude Code v2.1 에이전트 훅 및 격리 도입",
            "2. [Hermes3] Next.js 16 명시적 캐싱 및 DevTools MCP 탑재",
            "3. [Hermes3] Kubernetes v1.33 네이티브 사이드카 정식 지원",
        ],
    )

    # 1) 정상값: A(gemma3:12b)와 C(hermes3:8b) 두 모델 비교
    results = compare_briefing_models(
        docs,
        model_llms={"A (gemma3:12b)": llm_a, "C (hermes3:8b)": llm_c},
        date_str="2026-10-23",
        base_ui_url="https://assist-brief.vercel.app",
    )
    assert list(results.keys()) == ["A (gemma3:12b)", "C (hermes3:8b)"]
    comp_a = results["A (gemma3:12b)"]
    comp_c = results["C (hermes3:8b)"]
    assert isinstance(comp_a, ModelBriefComparison)
    assert comp_a.summary_lines[0] == "[Gemma3] Claude Code v2.1 서브에이전트 컨텍스트 격리 강화"
    assert comp_c.summary_lines[0] == "[Hermes3] Claude Code v2.1 에이전트 훅 및 격리 도입"
    assert "https://assist-brief.vercel.app/articles/2026-10-23" in comp_a.telegram_message
    assert "https://assist-brief.vercel.app/articles/2026-10-23" in comp_c.telegram_message

    # 2) 맞지만 헷갈리는 값: 모델 키 앞뒤에 공백이 포함된 경우 정제된 키로 반환
    res_trimmed = compare_briefing_models(
        docs,
        model_llms={"  A  ": llm_a},
        date_str="2026-10-23",
    )
    assert list(res_trimmed.keys()) == ["A"]
    assert len(res_trimmed["A"].summary_lines) == 3

    # 3) 일부만 맞는 값: 빈 문서 리스트일 때도 각 모델별 기본 3줄 폴백으로 비교 결과 생성
    res_empty_docs = compare_briefing_models(
        [],
        model_llms={"A": llm_a, "C": llm_c},
        date_str="2026-10-23",
    )
    assert len(res_empty_docs["A"].summary_lines) == 3
    assert len(res_empty_docs["C"].summary_lines) == 3

    # 4) 완전히 틀린 값: model_llms가 비어 있거나 공백 키만 있을 때 ValueError 발생
    with pytest.raises(ValueError, match="model_llms"):
        compare_briefing_models(docs, model_llms={})
    with pytest.raises(ValueError, match="model_llms"):
        compare_briefing_models(docs, model_llms={"   ": llm_a})

