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


def test_send_telegram_message_includes_reply_to_message_id():
    calls = []

    def fake_post(url: str, json_payload: dict) -> dict:
        calls.append((url, json_payload))
        return {"ok": True, "result": {"message_id": 42}}

    send_telegram_message(
        text="스레드 답변입니다.",
        bot_token="token123",
        chat_id="999",
        reply_to_message_id=555,
        http_post=fake_post,
    )

    assert len(calls) == 1
    assert calls[0][1]["reply_to_message_id"] == 555
    assert calls[0][1]["text"] == "스레드 답변입니다."


def test_handle_telegram_update_group_chat_selective_response():
    target_store = InMemoryTargetStore(seed=True)
    retriever = FakeMemoryRetriever(
        [
            Document(
                page_content="React 19 introduces React Server Components.",
                metadata={"domain": "frontend", "target_name": "React", "source_url": "https://react.dev"},
            )
        ]
    )
    sent_calls: list[dict] = []

    def mock_sender(chat_id: str, text: str, reply_to_message_id: int | None = None) -> None:
        sent_calls.append({
            "chat_id": chat_id,
            "text": text,
            "reply_to_message_id": reply_to_message_id,
        })

    class SimpleLLM:
        def generate(self, prompt: str) -> str:
            return f"응답: {prompt}"

    # 1. 일반 그룹 대화 (비호출) -> 침묵 (Silent Ignore)
    reply_chatter = handle_telegram_update(
        update={
            "message": {
                "message_id": 101,
                "chat": {"id": -1001234, "type": "supergroup"},
                "text": "오늘 점심 뭐 먹을까?",
            }
        },
        target_store=target_store,
        retriever=retriever,
        llm=SimpleLLM(),
        sender=mock_sender,
    )
    assert reply_chatter == ""
    assert len(sent_calls) == 0

    # 2. 그룹방 내 @DomAssistBot 멘션 호출 -> 인용 답장(reply_to_message_id=102)과 함께 답변
    reply_mention = handle_telegram_update(
        update={
            "message": {
                "message_id": 102,
                "chat": {"id": -1001234, "type": "supergroup"},
                "text": "@DomAssistBot React 19 주요 기능은?",
            }
        },
        target_store=target_store,
        retriever=retriever,
        llm=SimpleLLM(),
        sender=mock_sender,
    )
    assert reply_mention != ""
    assert len(sent_calls) == 1
    assert sent_calls[-1]["chat_id"] == "-1001234"
    assert sent_calls[-1]["reply_to_message_id"] == 102
    assert "React 19" in sent_calls[-1]["text"]

    # 3. 그룹방 내 봇 메시지에 대한 '답장(Reply)' -> 멘션 없어도 후속 질문으로 인식하여 답변
    reply_followup = handle_telegram_update(
        update={
            "message": {
                "message_id": 103,
                "chat": {"id": -1001234, "type": "supergroup"},
                "text": "더 자세히 설명해줘",
                "reply_to_message": {
                    "message_id": 99,
                    "from": {"is_bot": True, "username": "DomAssistBot"},
                },
            }
        },
        target_store=target_store,
        retriever=retriever,
        llm=SimpleLLM(),
        sender=mock_sender,
    )
    assert reply_followup != ""
    assert len(sent_calls) == 2
    assert sent_calls[-1]["reply_to_message_id"] == 103

    # 4. 다른 일반 사용자 메시지에 대한 답장 -> 봇 대상 아니므로 침묵
    reply_other_user = handle_telegram_update(
        update={
            "message": {
                "message_id": 104,
                "chat": {"id": -1001234, "type": "supergroup"},
                "text": "좋은 생각이야",
                "reply_to_message": {
                    "message_id": 98,
                    "from": {"is_bot": False, "username": "charlie"},
                },
            }
        },
        target_store=target_store,
        retriever=retriever,
        llm=SimpleLLM(),
        sender=mock_sender,
    )
    assert reply_other_user == ""
    assert len(sent_calls) == 2

    # 5. 1:1 개인 챗방 -> 멘션 없이도 모든 질문에 답변 (reply_to_message_id는 None)
    reply_private = handle_telegram_update(
        update={
            "message": {
                "message_id": 105,
                "chat": {"id": 12345, "type": "private"},
                "text": "React 19는?",
            }
        },
        target_store=target_store,
        retriever=retriever,
        llm=SimpleLLM(),
        sender=mock_sender,
    )
    assert reply_private != ""
    assert len(sent_calls) == 3
    assert sent_calls[-1]["chat_id"] == "12345"
    assert sent_calls[-1]["reply_to_message_id"] is None


def test_handle_telegram_update_silent_provision_warmup_without_guidance_notice():
    target_store = InMemoryTargetStore(seed=True)
    retriever = FakeMemoryRetriever(
        [Document(page_content="Data", metadata={"domain": "d", "target_name": "t", "source_url": "u"})]
    )
    sent_messages = []

    def mock_sender(chat_id: str, text: str, reply_to_message_id: int | None = None):
        sent_messages.append(text)

    class MockOfflineProvisioner:
        def __init__(self):
            self.triggered = False

        def check_health(self) -> bool:
            return False

        def trigger_background_provision(self) -> None:
            self.triggered = True

    class SimpleLLM:
        def generate(self, prompt: str) -> str:
            return "답변 내용입니다."

    prov = MockOfflineProvisioner()
    handle_telegram_update(
        update={"message": {"message_id": 201, "chat": {"id": 111, "type": "private"}, "text": "최신 기술은?"}},
        target_store=target_store,
        retriever=retriever,
        llm=SimpleLLM(),
        sender=mock_sender,
        provisioner=prov,
    )

    # Provisioner should be triggered in background
    assert prov.triggered is True
    # User should receive ONLY the answer, NO disruptive "🧠 [안내] ..." system bubble
    assert len(sent_messages) == 1
    assert "답변 내용입니다." in sent_messages[0]
    assert not any("온디맨드로 부팅 중입니다" in m or "🧠 [안내]" in m for m in sent_messages)
