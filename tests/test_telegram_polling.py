from typing import Any
import pytest

from app.telegram import (
    fetch_telegram_updates,
    process_telegram_updates_batch,
)
from app.targets import InMemoryTargetStore, ResearchTargetCreate
from app.rag import FakeMemoryRetriever
from scripts.run_telegram_polling import run_polling_worker


class MockLLM:
    def generate(self, prompt: str) -> str:
        return "테스트 답변"


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

    exit_code = run_polling_worker(
        bot_token="test-bot-token",
        timeout=1,
        once=True,
        http_get=mock_http_get,
        http_post=mock_http_post,
    )

    assert exit_code == 0
    assert len(sent_messages) == 1
    assert sent_messages[0]["chat_id"] == "888"
