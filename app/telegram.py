import logging
import re
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

logger = logging.getLogger(__name__)
DEFAULT_BOT_USERNAME = "DomAssistBot"


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
    reply_to_message_id: int | None = None,
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
    payload: dict[str, Any] = {
        "chat_id": cleaned_chat,
        "text": cleaned_text,
        "disable_web_page_preview": True,
    }
    if reply_to_message_id is not None:
        payload["reply_to_message_id"] = reply_to_message_id
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
    provisioner: Any | None = None,
    allowed_chat_ids: list[str] | None = None,
    enable_colab_gpu: bool = True,
) -> str:
    message = update.get("message") or {}
    chat = message.get("chat") or {}
    chat_id = str(chat.get("id") or "").strip()
    chat_type = str(chat.get("type") or "private").lower()
    raw_text = str(message.get("text") or "").strip()
    message_id = message.get("message_id")

    if not chat_id or not raw_text:
        return ""

    is_group = chat_type in ("group", "supergroup")
    reply_to_id = message_id if is_group else None

    # Check if message targets the bot in group chats:
    # 1. Command (/brief, /targets)
    # 2. Mention (@DomAssistBot)
    # 3. Direct reply to bot's message
    is_command = raw_text.startswith("/")
    has_mention = bool(
        re.search(rf"@{DEFAULT_BOT_USERNAME}\b", raw_text, flags=re.IGNORECASE)
        or any(
            entity.get("type") == "mention"
            and f"@{DEFAULT_BOT_USERNAME}".lower() in raw_text[entity.get("offset", 0):entity.get("offset", 0) + entity.get("length", 0)].lower()
            for entity in message.get("entities", [])
        )
    )
    is_reply_to_bot = False
    reply_to = message.get("reply_to_message") or {}
    reply_from = reply_to.get("from") or {}
    if reply_from.get("is_bot") and (reply_from.get("username") or "").lower() == DEFAULT_BOT_USERNAME.lower():
        is_reply_to_bot = True

    if is_group and not (is_command or has_mention or is_reply_to_bot):
        logger.debug("Group message ignored: not targeted to bot")
        return ""

    # Check authorization whitelist if specified
    if allowed_chat_ids and chat_id not in allowed_chat_ids:
        logger.warning("Unauthorized telegram chat_id blocked: %s", chat_id)
        reply = "⚠️ 접근 권한이 없습니다. 관리자에게 문의하세요."
        try:
            sender(chat_id, reply, reply_to_message_id=reply_to_id)
        except TypeError:
            sender(chat_id, reply)
        return reply

    # Strip bot mention in group chats (e.g. /command@DomAssistBot -> /command, @DomAssistBot query -> query)
    text = re.sub(r"^(/[a-zA-Z0-9_]+)@\w+", r"\1", raw_text)
    text = re.sub(r"^@\w+[\s,:]*", "", text).strip()
    text = re.sub(rf"@{DEFAULT_BOT_USERNAME}\b", "", text, flags=re.IGNORECASE).strip()

    if not text:
        return ""

    ui_url = (base_ui_url or settings.public_ui_base_url).strip()

    if text.startswith("/targets"):
        reply = _format_targets_summary(target_store)
    elif text.startswith("/brief"):
        if enable_colab_gpu and provisioner is not None and hasattr(provisioner, "check_health") and not provisioner.check_health():
            if hasattr(provisioner, "trigger_background_provision"):
                provisioner.trigger_background_provision()
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
        if enable_colab_gpu and provisioner is not None and hasattr(provisioner, "check_health") and not provisioner.check_health():
            if hasattr(provisioner, "trigger_background_provision"):
                provisioner.trigger_background_provision()
        result = answer_question(text, retriever=retriever, llm=llm)
        if result.sources:
            sources_text = "\n".join(f"- {s}" for s in result.sources)
            reply = f"{result.answer}\n\n🔗 출처:\n{sources_text}"
        else:
            reply = result.answer

    try:
        sender(chat_id, reply, reply_to_message_id=reply_to_id)
    except TypeError:
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
    provisioner: Any | None = None,
    allowed_chat_ids: list[str] | None = None,
    enable_colab_gpu: bool = True,
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
            provisioner=provisioner,
            allowed_chat_ids=allowed_chat_ids,
            enable_colab_gpu=enable_colab_gpu,
        )

    return last_offset
