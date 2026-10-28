from typing import Any
import pytest

from langchain_core.documents import Document
from app.articles import InMemoryArticleStore
from app.rag import FakeMemoryRetriever, LLMProtocol
from app.targets import InMemoryTargetStore
from app.telegram import handle_telegram_update


class DummyLLM:
    def complete(self, prompt: str) -> str:
        return "테스트 답변입니다."


class DummyProvisioner:
    def __init__(self, healthy: bool = False):
        self.healthy = healthy
        self.triggered = False

    def check_health(self) -> bool:
        return self.healthy

    def trigger_background_provision(self) -> None:
        self.triggered = True


def test_telegram_update_blocks_unauthorized_user_and_prevents_gpu_startup():
    sent_messages: list[tuple[str, str]] = []

    def mock_sender(chat_id: str, text: str, **kwargs: Any) -> None:
        sent_messages.append((chat_id, text))

    retriever = FakeMemoryRetriever(
        docs=[Document(page_content="doc1", metadata={"source_url": "https://example.com"})]
    )
    target_store = InMemoryTargetStore(seed=False)
    article_store = InMemoryArticleStore()
    llm = DummyLLM()
    provisioner = DummyProvisioner(healthy=False)

    # 1. Unauthorized chat_id: "999999" (not in allowed list ["12345"])
    update_unauth = {
        "update_id": 1,
        "message": {
            "message_id": 101,
            "chat": {"id": "999999", "type": "private"},
            "text": "안녕? GPU 켜줘",
        },
    }

    reply = handle_telegram_update(
        update_unauth,
        target_store=target_store,
        retriever=retriever,
        llm=llm,
        sender=mock_sender,
        article_store=article_store,
        provisioner=provisioner,
        allowed_chat_ids=["12345"],
    )

    # Must NOT trigger GPU provisioning
    assert provisioner.triggered is False
    assert "인가되지 않은" in reply or "접근 권한이 없습니다" in reply
    assert len(sent_messages) == 1
    assert sent_messages[0][0] == "999999"

    # 2. Authorized chat_id: "12345"
    update_auth = {
        "update_id": 2,
        "message": {
            "message_id": 102,
            "chat": {"id": "12345", "type": "private"},
            "text": "오늘 기술 동향 알려줘",
        },
    }

    reply_auth = handle_telegram_update(
        update_auth,
        target_store=target_store,
        retriever=retriever,
        llm=llm,
        sender=mock_sender,
        article_store=article_store,
        provisioner=provisioner,
        allowed_chat_ids=["12345"],
    )

    # Authorized user SHOULD trigger GPU provisioning if offline
    assert provisioner.triggered is True
    assert "doc1" in reply_auth
