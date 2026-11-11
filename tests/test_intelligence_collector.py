import pytest
from app.collectors import (
    CollectedItem,
    parse_arxiv_papers,
    parse_hf_daily_papers,
    parse_github_trending,
    format_daily_intelligence_report,
    export_item_to_notion_backlog,
)

SAMPLE_ARXIV_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>LangGraph: Building Stateful Multi-Agent Applications with Cyclic Graphs</title>
    <summary>We present LangGraph, a framework for building stateful, multi-agent systems with LLMs.</summary>
    <id>http://arxiv.org/abs/2611.12345v1</id>
    <published>2026-11-10T12:00:00Z</published>
  </entry>
</feed>
"""

SAMPLE_HF_PAPERS_JSON = [
    {
        "id": "2611.54321",
        "title": "Full-Duplex Conversational Speech Language Models",
        "summary": "Native speech language models enabling real-time audio interaction without cascaded STT/TTS.",
        "publishedAt": "2026-11-11T09:00:00.000Z",
    }
]

SAMPLE_GITHUB_TRENDING_ITEMS = [
    {
        "name": "pipecat-ai/pipecat",
        "description": "Open source framework for voice and multimodal conversational AI",
        "html_url": "https://github.com/pipecat-ai/pipecat",
        "stargazers_count": 12500,
    }
]


def test_parse_arxiv_papers():
    items = parse_arxiv_papers(SAMPLE_ARXIV_XML)
    assert len(items) == 1
    assert items[0].title == "LangGraph: Building Stateful Multi-Agent Applications with Cyclic Graphs"
    assert "http://arxiv.org/abs/2611.12345v1" in items[0].source_url
    assert "multi-agent systems" in items[0].content


def test_parse_hf_daily_papers():
    items = parse_hf_daily_papers(SAMPLE_HF_PAPERS_JSON)
    assert len(items) == 1
    assert items[0].title == "Full-Duplex Conversational Speech Language Models"
    assert "https://huggingface.co/papers/2611.54321" == items[0].source_url
    assert "Native speech" in items[0].content


def test_parse_github_trending():
    items = parse_github_trending(SAMPLE_GITHUB_TRENDING_ITEMS)
    assert len(items) == 1
    assert items[0].title == "pipecat-ai/pipecat (⭐ 12500)"
    assert items[0].source_url == "https://github.com/pipecat-ai/pipecat"
    assert "voice and multimodal" in items[0].content


def test_format_daily_intelligence_report():
    items = [
        CollectedItem(
            title="LangGraph: Building Stateful Multi-Agent Applications",
            content="Summary of LangGraph",
            source_url="http://arxiv.org/abs/2611.12345v1",
            published_at="2026-11-10",
        )
    ]
    report = format_daily_intelligence_report(items, title="📡 데일리 AI 논문/트렌드 브리핑")
    assert "📡 데일리 AI 논문/트렌드 브리핑" in report
    assert "LangGraph" in report
    assert "http://arxiv.org/abs/2611.12345v1" in report


def test_export_item_to_notion_backlog(monkeypatch):
    called = {}

    def fake_notion_post(payload, token):
        called["payload"] = payload
        called["token"] = token
        return "notion-card-12345"

    monkeypatch.setattr("app.collectors._post_to_notion_api", fake_notion_post)

    item = CollectedItem(
        title="Test Research Item",
        content="Interesting paper about Agents",
        source_url="https://example.com/paper",
        published_at="2026-11-11",
    )
    res_id = export_item_to_notion_backlog(item, token="test-token", db_id="test-db-id")
    assert res_id == "notion-card-12345"
    assert called["payload"]["properties"]["Name"]["title"][0]["text"]["content"] == "Test Research Item"
    assert called["payload"]["properties"]["Status"]["status"]["name"] == "1. Backlog"
