import pytest
from langchain_core.documents import Document

from app.rag import FakeMemoryRetriever
from app.targets import InMemoryTargetStore
from app.telegram import handle_telegram_update, send_telegram_message


def test_send_telegram_message_validates_credentials_and_posts():
    calls: list[tuple[str, dict]] = []

    def fake_post(url: str, json_payload: dict) -> dict:
        calls.append((url, json_payload))
        return {"ok": True, "result": {"message_id": 42}}

    res = send_telegram_message(
        text="모닝 브리핑입니다.",
        bot_token="123456:ABC-DEF",
        chat_id="987654321",
        http_post=fake_post,
    )

    assert res["ok"] is True
    assert calls == [
        (
            "https://api.telegram.org/bot123456:ABC-DEF/sendMessage",
            {
                "chat_id": "987654321",
                "text": "모닝 브리핑입니다.",
                "disable_web_page_preview": True,
            },
        )
    ]

    with pytest.raises(ValueError, match="bot_token"):
        send_telegram_message(
            text="hello", bot_token="", chat_id="123", http_post=fake_post
        )

    with pytest.raises(ValueError, match="text"):
        send_telegram_message(
            text="   ", bot_token="token", chat_id="123", http_post=fake_post
        )


def test_handle_telegram_update_routes_commands_and_questions():
    target_store = InMemoryTargetStore(seed=True)
    retriever = FakeMemoryRetriever(
        [
            Document(
                page_content="Next.js 16 adds native MCP server.",
                metadata={
                    "domain": "fullstack_web",
                    "target_name": "Next.js",
                    "source_url": "https://nextjs.org/blog/next-16",
                },
            )
        ]
    )
    sent_messages: list[tuple[str, str]] = []

    def fake_sender(chat_id: str, text: str) -> None:
        sent_messages.append((chat_id, text))

    class StubLLM:
        def generate(self, prompt: str) -> str:
            if "3줄" in prompt or "브리핑" in prompt or "아침" in prompt:
                return (
                    "1. Next.js 16 내장 MCP 서버 출시\n"
                    "2. Cache Components 정식 도입\n"
                    "3. 풀스택 AI 통합 워크플로 강화"
                )
            return "Next.js 16은 MCP 서버를 지원합니다."

    # 1) /targets 명령
    reply_targets = handle_telegram_update(
        update={"message": {"chat": {"id": 111}, "text": "/targets"}},
        target_store=target_store,
        retriever=retriever,
        llm=StubLLM(),
        sender=fake_sender,
    )
    assert "ai_agent_llm" in reply_targets
    assert sent_messages[-1][0] == "111"

    # 2) /brief 명령 -> 3줄 요약 + 아티클 링크 포함
    reply_brief = handle_telegram_update(
        update={"message": {"chat": {"id": 111}, "text": "/brief"}},
        target_store=target_store,
        retriever=retriever,
        llm=StubLLM(),
        sender=fake_sender,
        base_ui_url="https://assist-brief.vercel.app",
    )
    assert "1. Next.js 16 내장 MCP 서버 출시" in reply_brief
    assert "2. Cache Components 정식 도입" in reply_brief
    assert "3. 풀스택 AI 통합 워크플로 강화" in reply_brief
    assert "https://assist-brief.vercel.app/articles/" in reply_brief

    # 3) 일반 질문 메시지
    reply_q = handle_telegram_update(
        update={"message": {"chat": {"id": 111}, "text": "Next.js 16 변경점은?"}},
        target_store=target_store,
        retriever=retriever,
        llm=StubLLM(),
        sender=fake_sender,
    )
    assert "Next.js 16은 MCP 서버를 지원합니다." in reply_q
    assert "https://nextjs.org/blog/next-16" in reply_q


def test_handle_telegram_update_strips_bot_mentions_in_group_chats():
    target_store = InMemoryTargetStore(seed=True)
    retriever = FakeMemoryRetriever(
        [
            Document(
                page_content="Next.js 16 adds native MCP server.",
                metadata={
                    "domain": "fullstack_web",
                    "target_name": "Next.js",
                    "source_url": "https://nextjs.org/blog/next-16",
                },
            )
        ]
    )
    sent_messages: list[tuple[str, str]] = []

    def fake_sender(chat_id: str, text: str) -> None:
        sent_messages.append((chat_id, text))

    class EchoLLM:
        def generate(self, prompt: str) -> str:
            return "답변 완료"

    # 1) @DomAssistBot mention in group question
    reply_mention = handle_telegram_update(
        update={"message": {"chat": {"id": 777}, "text": "@DomAssistBot Next.js 16 변경점은?"}},
        target_store=target_store,
        retriever=retriever,
        llm=EchoLLM(),
        sender=fake_sender,
    )
    assert "답변 완료" in reply_mention
    assert sent_messages[-1][0] == "777"

    # 2) /brief@DomAssistBot command mention in group
    reply_brief_mention = handle_telegram_update(
        update={"message": {"chat": {"id": 777}, "text": "/brief@DomAssistBot"}},
        target_store=target_store,
        retriever=retriever,
        llm=EchoLLM(),
        sender=fake_sender,
    )
    assert "모닝 브리핑" in reply_brief_mention or "아티클" in reply_brief_mention

    # 3) /targets@DomAssistBot command mention in group
    reply_targets_mention = handle_telegram_update(
        update={"message": {"chat": {"id": 777}, "text": "/targets@DomAssistBot"}},
        target_store=target_store,
        retriever=retriever,
        llm=EchoLLM(),
        sender=fake_sender,
    )
    assert "ai_agent_llm" in reply_targets_mention

    # 4) Mention only (empty query) -> should return empty string without sending
    sent_len_before = len(sent_messages)
    reply_empty = handle_telegram_update(
        update={"message": {"chat": {"id": 777}, "text": "@DomAssistBot   "}},
        target_store=target_store,
        retriever=retriever,
        llm=EchoLLM(),
        sender=fake_sender,
    )
    assert reply_empty == ""
    assert len(sent_messages) == sent_len_before
