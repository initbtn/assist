from typing import Any
import pytest
from langchain_core.documents import Document

from app.articles import InMemoryArticleStore
from app.telegram import (
    fetch_telegram_updates,
    process_telegram_updates_batch,
)
from app.targets import InMemoryTargetStore, ResearchTargetCreate
from app.rag import FakeMemoryRetriever
from scripts.run_telegram_polling import run_polling_worker


class MockLLM:
    def generate(self, prompt: str) -> str:
        return "- 1. AI 최신 동향 요약\n- 2. RAG 아키텍처 개선\n- 3. 엣지 배포 성공"


def test_fetch_telegram_updates_success():
    calls = []

    def fake_http_get(url: str, params: dict[str, Any]) -> dict[str, Any]:
        calls.append((url, params))
        return {
            "ok": True,
            "result": [
                {
                    "update_id": 101,
                    "message": {
                        "chat": {"id": 12345},
                        "text": "/targets",
                    },
                },
                {
                    "update_id": 102,
                    "message": {
                        "chat": {"id": 12345},
                        "text": "인공지능 최신 동향은?",
                    },
                },
            ],
        }

    updates = fetch_telegram_updates(
        bot_token="test-token",
        offset=100,
        timeout=10,
        http_get=fake_http_get,
    )
    assert len(updates) == 2
    assert updates[0]["update_id"] == 101
    assert updates[1]["update_id"] == 102
    assert calls[0][0] == "https://api.telegram.org/bottest-token/getUpdates"
    assert calls[0][1] == {"offset": 100, "timeout": 10}


def test_process_telegram_updates_batch():
    sent_messages = []

    def mock_sender(chat_id: str, text: str):
        sent_messages.append((chat_id, text))

    target_store = InMemoryTargetStore()
    target_store.add_target(
        ResearchTargetCreate(
            domain="ai",
            name="OpenAI Blog",
            source_type="rss",
            source_url="https://openai.com/blog/rss.xml",
        )
    )

    updates = [
        {
            "update_id": 200,
            "message": {
                "chat": {"id": 999},
                "text": "/targets",
            },
        },
        {
            "update_id": 201,
            "message": {
                "chat": {"id": 999},
                "text": "안녕하세요",
            },
        },
    ]

    next_offset = process_telegram_updates_batch(
        updates,
        target_store=target_store,
        retriever=FakeMemoryRetriever(),
        llm=MockLLM(),
        sender=mock_sender,
    )

    assert next_offset == 202
    assert len(sent_messages) == 2
    assert sent_messages[0][0] == "999"
    assert "OpenAI Blog" in sent_messages[0][1]


def test_process_telegram_updates_brief_command_and_article_store():
    sent_messages = []

    def mock_sender(chat_id: str, text: str):
        sent_messages.append((chat_id, text))

    retriever = FakeMemoryRetriever()
    retriever.add_documents([
        Document(
            page_content="신규 AI 엣지 배포 기술 분석 보고서",
            metadata={"domain": "ai", "source_url": "https://example.com/ai-1"}
        )
    ])
    article_store = InMemoryArticleStore()

    updates = [
        {
            "update_id": 250,
            "message": {
                "chat": {"id": 777},
                "text": "/brief",
            },
        }
    ]

    next_offset = process_telegram_updates_batch(
        updates,
        target_store=InMemoryTargetStore(),
        retriever=retriever,
        llm=MockLLM(),
        sender=mock_sender,
        article_store=article_store,
    )

    assert next_offset == 251
    assert len(sent_messages) == 1
    assert sent_messages[0][0] == "777"
    assert "브리핑" in sent_messages[0][1]
    # Verify article is saved to store
    articles = article_store.list_articles()
    assert len(articles) == 1
    assert "AI 최신 동향 요약" in articles[0].summary_lines[0]


def test_run_polling_worker_once():
    sent_messages = []

    def mock_http_get(url: str, params: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": True,
            "result": [
                {
                    "update_id": 300,
                    "message": {
                        "chat": {"id": 888},
                        "text": "/targets",
                    },
                }
            ],
        }

    def mock_http_post(url: str, payload: dict[str, Any]) -> dict[str, Any]:
        sent_messages.append(payload)
        return {"ok": True}

    article_store = InMemoryArticleStore()
    exit_code = run_polling_worker(
        bot_token="test-bot-token",
        timeout=1,
        once=True,
        article_store=article_store,
        llm=MockLLM(),
        http_get=mock_http_get,
        http_post=mock_http_post,
    )

    assert exit_code == 0
    assert len(sent_messages) == 1
    assert sent_messages[0]["chat_id"] == "888"


def test_run_polling_worker_seeds_initial_knowledge_by_default():
    sent_messages = []

    def mock_http_get(url: str, params: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": True,
            "result": [
                {
                    "update_id": 400,
                    "message": {
                        "chat": {"id": 888},
                        "text": "FastAPI 최신 업데이트는?",
                    },
                }
            ],
        }

    def mock_http_post(url: str, payload: dict[str, Any]) -> dict[str, Any]:
        sent_messages.append(payload)
        return {"ok": True}

    exit_code = run_polling_worker(
        bot_token="test-bot-token",
        ops_bot_token="test-ops-token",
        ops_telegram_chat_id="admin-chat-id",
        timeout=1,
        once=True,
        llm=MockLLM(),
        http_get=mock_http_get,
        http_post=mock_http_post,
    )

    assert exit_code == 0
    assert len(sent_messages) >= 2
    user_msgs = [m for m in sent_messages if m["chat_id"] == "888"]
    assert len(user_msgs) >= 1
    assert "저장된 지식 베이스에서 관련된 동향 문서를 찾지 못했습니다." not in user_msgs[-1]["text"]
    assert "출처:" in user_msgs[-1]["text"]
    admin_notices = [m for m in sent_messages if "부팅 시작" in m["text"] or "🟡" in m["text"]]
    assert len(admin_notices) >= 1


def test_handle_telegram_update_triggers_provisioner_when_offline():
    sent_messages = []

    def mock_sender(chat_id: str, text: str):
        sent_messages.append((chat_id, text))

    class MockOfflineProvisioner:
        def __init__(self):
            self.triggered = False

        def check_health(self) -> bool:
            return False

        def trigger_background_provision(self) -> None:
            self.triggered = True

    prov = MockOfflineProvisioner()
    update = {
        "update_id": 500,
        "message": {
            "chat": {"id": 1234},
            "text": "새로운 프레임워크 동향 알려줘",
        },
    }

    process_telegram_updates_batch(
        [update],
        target_store=InMemoryTargetStore(),
        retriever=FakeMemoryRetriever(),
        llm=MockLLM(),
        sender=mock_sender,
        provisioner=prov,
    )

    assert prov.triggered is True
    assert len(sent_messages) == 1
    assert not any("온디맨드로 부팅 중입니다" in msg[1] for msg in sent_messages)
    assert len(sent_messages[0][1]) > 0


def test_polling_worker_ops_channel_isolation():
    posted_requests = []

    def mock_http_get(url: str, params: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": True,
            "result": [
                {
                    "update_id": 601,
                    "message": {
                        "chat": {"id": 888},
                        "text": "FastAPI 최신 업데이트는?",
                    },
                }
            ],
        }

    def mock_http_post(url: str, payload: dict[str, Any]) -> dict[str, Any]:
        posted_requests.append({"url": url, "payload": payload})
        return {"ok": True}

    # 1. When ops_bot_token and ops_telegram_chat_id are provided:
    # User message sent via service bot token to chat 888
    # Ops alert sent via ops bot token to ops chat 9999
    exit_code = run_polling_worker(
        bot_token="test-service-token",
        ops_bot_token="test-ops-token",
        ops_telegram_chat_id="admin-9999",
        timeout=1,
        once=True,
        llm=MockLLM(),
        http_get=mock_http_get,
        http_post=mock_http_post,
    )

    assert exit_code == 0
    assert len(posted_requests) >= 2

    user_requests = [
        req for req in posted_requests
        if req["payload"]["chat_id"] == "888"
    ]
    ops_requests = [
        req for req in posted_requests
        if req["payload"]["chat_id"] == "admin-9999"
    ]

    assert len(user_requests) >= 1
    assert all(req["url"] == "https://api.telegram.org/bottest-service-token/sendMessage" for req in user_requests)
    assert any("출처:" in req["payload"]["text"] for req in user_requests)

    assert len(ops_requests) >= 1
    for req in ops_requests:
        assert "https://api.telegram.org/bottest-ops-token/sendMessage" == req["url"]
        assert any(icon in req["payload"]["text"] for icon in ["🟡", "🟢", "⚪", "🔴", "부팅"])

    # Verify service bot token NEVER sent to admin-9999
    assert all(
        req["url"] != "https://api.telegram.org/bottest-service-token/sendMessage"
        for req in ops_requests
    )


def test_polling_worker_ops_alert_skipped_when_ops_token_missing(monkeypatch):
    posted_requests = []

    def mock_http_get(url: str, params: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": True,
            "result": [
                {
                    "update_id": 701,
                    "message": {
                        "chat": {"id": 888},
                        "text": "FastAPI 최신 업데이트는?",
                    },
                }
            ],
        }

    def mock_http_post(url: str, payload: dict[str, Any]) -> dict[str, Any]:
        posted_requests.append({"url": url, "payload": payload})
        return {"ok": True}

    monkeypatch.setattr("app.config.Settings.resolved_ops_telegram_bot_token", lambda self: "")
    monkeypatch.setattr("app.config.Settings.resolved_ops_telegram_chat_id", lambda self: "")

    exit_code = run_polling_worker(
        bot_token="test-service-token",
        ops_bot_token="",
        ops_telegram_chat_id="",
        timeout=1,
        once=True,
        llm=MockLLM(),
        http_get=mock_http_get,
        http_post=mock_http_post,
    )

    assert exit_code == 0
    # Only user response should be sent via service bot; no ops alerts should be sent
    assert len(posted_requests) >= 1
    assert all(req["payload"]["chat_id"] == "888" for req in posted_requests)
    assert all("bottest-service-token" in req["url"] for req in posted_requests)
    assert not any("🟡" in req["payload"]["text"] or "부팅 시작" in req["payload"]["text"] for req in posted_requests)


def test_polling_worker_group_mention_handling():
    posted_requests = []

    def mock_http_get(url: str, params: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": True,
            "result": [
                {
                    "update_id": 801,
                    "message": {
                        "message_id": 8010,
                        "chat": {"id": -100123456789, "type": "supergroup"},
                        "text": "@DomAssistBot FastAPI 최신 업데이트는?",
                    },
                }
            ],
        }

    def mock_http_post(url: str, payload: dict[str, Any]) -> dict[str, Any]:
        posted_requests.append({"url": url, "payload": payload})
        return {"ok": True}

    exit_code = run_polling_worker(
        bot_token="test-service-token",
        ops_bot_token="test-ops-token",
        ops_telegram_chat_id="admin-9999",
        timeout=1,
        once=True,
        llm=MockLLM(),
        http_get=mock_http_get,
        http_post=mock_http_post,
    )

    assert exit_code == 0
    group_responses = [
        req for req in posted_requests
        if req["payload"]["chat_id"] == "-100123456789"
    ]
    assert len(group_responses) == 1
    assert "출처:" in group_responses[0]["payload"]["text"]
    assert group_responses[0]["payload"]["reply_to_message_id"] == 8010


def test_polling_worker_ignores_unrelated_group_messages():
    posted_requests = []

    def mock_http_get(url: str, params: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": True,
            "result": [
                {
                    "update_id": 901,
                    "message": {
                        "message_id": 9010,
                        "chat": {"id": -100123456789, "type": "supergroup"},
                        "text": "오늘 점심 뭐 먹을까?",
                    },
                }
            ],
        }

    def mock_http_post(url: str, payload: dict[str, Any]) -> dict[str, Any]:
        posted_requests.append({"url": url, "payload": payload})
        return {"ok": True}

    exit_code = run_polling_worker(
        bot_token="test-service-token",
        ops_bot_token="test-ops-token",
        ops_telegram_chat_id="admin-9999",
        timeout=1,
        once=True,
        llm=MockLLM(),
        http_get=mock_http_get,
        http_post=mock_http_post,
    )

    assert exit_code == 0
    group_responses = [
        req for req in posted_requests
        if req["payload"]["chat_id"] == "-100123456789"
    ]
    assert len(group_responses) == 0


