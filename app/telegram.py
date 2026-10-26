from collections import defaultdict
from typing import Any, Callable

import httpx

from app.articles import (
    InMemoryArticleStore,
    build_briefing_article,
    format_telegram_brief_message,
)
from app.config import settings
from app.rag import LLMProtocol, RetrieverProtocol, answer_question
from app.targets import InMemoryTargetStore


def _default_http_post(url: str, json_payload: dict[str, Any]) -> dict[str, Any]:
    resp = httpx.post(url, json=json_payload, timeout=15.0)
    resp.raise_for_status()
    return resp.json()


def _default_http_get(url: str, params: dict[str, Any]) -> dict[str, Any]:
    timeout = float(params.get("timeout", 30)) + 5.0
    resp = httpx.get(url, params=params, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def send_telegram_message(
    text: str,
    *,
    bot_token: str,
    chat_id: str,
    http_post: Callable[[str, dict[str, Any]], dict[str, Any]] = _default_http_post,
) -> dict[str, Any]:
    cleaned_token = bot_token.strip()
    cleaned_chat = str(chat_id).strip()
    cleaned_text = text.strip()

    if not cleaned_token:
        raise ValueError("bot_token must not be empty")
    if not cleaned_chat:
        raise ValueError("chat_id must not be empty")
    if not cleaned_text:
        raise ValueError("text must not be empty")

    url = f"https://api.telegram.org/bot{cleaned_token}/sendMessage"
    payload = {
        "chat_id": cleaned_chat,
        "text": cleaned_text,
        "disable_web_page_preview": True,
    }
    return http_post(url, payload)


def fetch_telegram_updates(
    *,
    bot_token: str,
    offset: int | None = None,
    timeout: int = 30,
    http_get: Callable[[str, dict[str, Any]], dict[str, Any]] = _default_http_get,
) -> list[dict[str, Any]]:
    cleaned_token = bot_token.strip()
    if not cleaned_token:
        raise ValueError("bot_token must not be empty")

    url = f"https://api.telegram.org/bot{cleaned_token}/getUpdates"
    params: dict[str, Any] = {"timeout": timeout}
    if offset is not None:
        params["offset"] = offset

    data = http_get(url, params)
    if isinstance(data, dict) and data.get("ok"):
        return data.get("result", [])
    return []


def _format_targets_summary(target_store: InMemoryTargetStore) -> str:
    active = target_store.list_targets(active_only=True)
    if not active:
        return "현재 활성화된 리서치 타겟이 없습니다."

    grouped: dict[str, list[str]] = defaultdict(list)
    for t in active:
        grouped[t.domain].append(f"{t.name} ({t.source_type})")

    lines = ["📌 활성 리서치 타겟 목록:"]
    for domain, items in grouped.items():
        lines.append(f"\n[{domain}]\n- " + "\n- ".join(items))
    return "\n".join(lines)


def handle_telegram_update(
    update: dict[str, Any],
    *,
    target_store: InMemoryTargetStore,
    retriever: RetrieverProtocol,
    llm: LLMProtocol,
    sender: Callable[[str, str], None],
    article_store: InMemoryArticleStore | None = None,
    base_ui_url: str | None = None,
) -> str:
    message = update.get("message") or {}
    chat = message.get("chat") or {}
    chat_id = str(chat.get("id") or "").strip()
    text = str(message.get("text") or "").strip()

    if not chat_id or not text:
        return ""

    ui_url = (base_ui_url or settings.public_ui_base_url).strip()

    if text.startswith("/targets"):
        reply = _format_targets_summary(target_store)
    elif text.startswith("/brief"):
        recent_docs = retriever.search("recent", k=20)
        article = build_briefing_article(
            recent_docs,
            llm=llm,
            base_ui_url=ui_url,
        )
        if article_store is not None:
            article_store.save(article)
        reply = format_telegram_brief_message(article)
    else:
        result = answer_question(text, retriever=retriever, llm=llm)
        if result.sources:
            sources_text = "\n".join(f"- {s}" for s in result.sources)
            reply = f"{result.answer}\n\n🔗 출처:\n{sources_text}"
        else:
            reply = result.answer

    sender(chat_id, reply)
    return reply


def process_telegram_updates_batch(
    updates: list[dict[str, Any]],
    *,
    target_store: InMemoryTargetStore,
    retriever: RetrieverProtocol,
    llm: LLMProtocol,
    sender: Callable[[str, str], None],
    article_store: InMemoryArticleStore | None = None,
    base_ui_url: str | None = None,
) -> int | None:
    if not updates:
        return None

    last_offset = None
    for item in updates:
        update_id = item.get("update_id")
        if isinstance(update_id, int):
            last_offset = update_id + 1
        handle_telegram_update(
            item,
            target_store=target_store,
            retriever=retriever,
            llm=llm,
            sender=sender,
            article_store=article_store,
            base_ui_url=base_ui_url,
        )

    return last_offset
