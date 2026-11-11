import pytest
from unittest.mock import MagicMock
from app.articles import (
    ArticleItem,
    ArticleSection,
    BriefingArticle,
    build_daily_briefing_markdown,
    save_briefing_to_firestore,
    publish_briefing_to_domlog,
)


def test_build_daily_briefing_markdown():
    briefing = BriefingArticle(
        slug="2026-11-12-daily-tech-briefing",
        date="2026-11-12",
        title="2026-11-12 AI & 클라우드 기술 일간 종합 브리핑",
        summary_lines=[
            "LangGraph 기반 멀티에이전트 아키텍처 및 상태 루프 제어 논문 발표",
            "Next.js App Router와 Turbopack 최신 동향 정리",
        ],
        sections=[
            ArticleSection(
                domain="ai_agent_llm",
                domain_label="AI 에이전트 & LLM",
                items=[
                    ArticleItem(
                        target_name="LangGraph",
                        title="Building Stateful Multi-Agent Applications with Cyclic Graphs",
                        summary="순환 그래프 기반의 멀티에이전트 상태 제어 프레임워크 연구.",
                        source_url="http://arxiv.org/abs/2611.12345v1",
                    )
                ],
            )
        ],
        article_url="https://domlog.link/posts/2026-11-12-daily-tech-briefing",
    )

    md = build_daily_briefing_markdown(briefing)
    assert "# 2026-11-12 AI & 클라우드 기술 일간 종합 브리핑" in md
    assert "## AI 에이전트 & LLM" in md
    assert "Building Stateful Multi-Agent" in md
    assert "http://arxiv.org/abs/2611.12345v1" in md


def test_save_briefing_to_firestore(monkeypatch):
    mock_db = MagicMock()
    mock_doc = MagicMock()
    mock_db.collection.return_value.document.return_value = mock_doc

    briefing = BriefingArticle(
        slug="2026-11-12-briefing",
        date="2026-11-12",
        title="Test Briefing",
        summary_lines=["Line 1"],
        sections=[],
        article_url="http://example.com",
    )

    save_briefing_to_firestore(briefing, firestore_client=mock_db)
    mock_db.collection.assert_called_with("daily_briefings")
    mock_db.collection().document.assert_called_with("2026-11-12-briefing")
    mock_doc.set.assert_called_once()


def test_publish_briefing_to_domlog(monkeypatch):
    called = {}

    def fake_post(url, headers, json=None, timeout=None, **kwargs):
        called["url"] = url
        called["headers"] = headers
        called["json"] = json
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ok": True, "slug": json["slug"]}
        return mock_resp

    monkeypatch.setattr("httpx.post", fake_post)

    briefing = BriefingArticle(
        slug="2026-11-12-briefing",
        date="2026-11-12",
        title="Test Briefing",
        summary_lines=["Summary point"],
        sections=[],
        article_url="http://example.com",
    )

    res = publish_briefing_to_domlog(
        briefing=briefing,
        domlog_base_url="https://domlog.link",
        admin_api_key="ast_live_test_key_123",
    )

    assert res["ok"] is True
    assert called["url"] == "https://domlog.link/api/admin/posts"
    assert "Bearer ast_live_test_key_123" in called["headers"]["Authorization"]
    assert called["json"]["slug"] == "2026-11-12-briefing"
