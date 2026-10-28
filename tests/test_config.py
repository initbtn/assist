import pytest
from app.config import Settings, resolve_pass_secret


def test_resolved_ops_telegram_bot_token_explicit():
    s = Settings(ops_telegram_bot_token="ops-token-1234")
    assert s.resolved_ops_telegram_bot_token() == "ops-token-1234"


def test_resolved_ops_telegram_chat_id_explicit():
    s = Settings(ops_telegram_chat_id="ops-chat-999")
    assert s.resolved_ops_telegram_chat_id() == "ops-chat-999"


def test_resolved_ops_telegram_bot_token_from_pass(monkeypatch):
    def fake_pass_runner(key_path: str) -> str:
        if key_path == "telegram/bot-token":
            return "secret-ops-bot-token-from-pass\n"
        if key_path == "telegram/domAssistBot/bot-token":
            return "secret-service-bot-token-from-pass\n"
        return ""

    monkeypatch.setattr("app.config._default_pass_runner", fake_pass_runner)

    s = Settings(ops_telegram_bot_token="", telegram_bot_token="")
    assert s.resolved_ops_telegram_bot_token() == "secret-ops-bot-token-from-pass"
    assert s.resolved_telegram_bot_token() == "secret-service-bot-token-from-pass"


def test_resolved_ops_telegram_chat_id_from_pass(monkeypatch):
    def fake_pass_runner(key_path: str) -> str:
        if key_path == "telegram/chat-id":
            return "ops-admin-chat-id-from-pass\n"
        if key_path == "telegram/domAssistBot/chat-id":
            return "service-chat-id-from-pass\n"
        return ""

    monkeypatch.setattr("app.config._default_pass_runner", fake_pass_runner)

    s = Settings(ops_telegram_chat_id="", telegram_chat_id="")
    assert s.resolved_ops_telegram_chat_id() == "ops-admin-chat-id-from-pass"
    assert s.resolved_telegram_chat_id() == "service-chat-id-from-pass"
