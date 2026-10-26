#!/usr/bin/env python3
import argparse
import logging
import signal
import sys
import time
from typing import Any

from app.articles import InMemoryArticleStore
from app.config import settings
from app.rag import FakeMemoryRetriever, LLMProtocol, PGVectorRetriever, RetrieverProtocol, get_llm
from app.targets import InMemoryTargetStore
from app.telegram import (
    fetch_telegram_updates,
    process_telegram_updates_batch,
    send_telegram_message,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("telegram_polling")


def run_polling_worker(
    *,
    bot_token: str | None = None,
    timeout: int = 30,
    poll_interval: float = 1.0,
    once: bool = False,
    target_store: InMemoryTargetStore | None = None,
    retriever: RetrieverProtocol | None = None,
    article_store: InMemoryArticleStore | None = None,
    llm: LLMProtocol | None = None,
    http_get: Any = None,
    http_post: Any = None,
) -> int:
    token = (bot_token or settings.resolved_telegram_bot_token()).strip()
    if not token:
        logger.error("Telegram bot token is missing or could not be resolved.")
        return 1

    t_store = target_store if target_store is not None else InMemoryTargetStore(seed=True)
    r_retriever = (
        retriever
        if retriever is not None
        else (PGVectorRetriever() if settings.use_pgvector else FakeMemoryRetriever())
    )
    a_store = article_store if article_store is not None else InMemoryArticleStore()
    active_llm = llm if llm is not None else get_llm(settings)

    def _sender(chat_id: str, text: str) -> None:
        kwargs: dict[str, Any] = {
            "text": text,
            "bot_token": token,
            "chat_id": chat_id,
        }
        if http_post is not None:
            kwargs["http_post"] = http_post
        send_telegram_message(**kwargs)

    offset: int | None = None
    logger.info("Starting Telegram outbound long polling worker...")

    running = True

    def _handle_exit(sig, frame):
        nonlocal running
        logger.info("Received termination signal, shutting down polling worker...")
        running = False

    signal.signal(signal.SIGINT, _handle_exit)
    signal.signal(signal.SIGTERM, _handle_exit)

    processed_count = 0
    while running:
        try:
            fetch_kwargs: dict[str, Any] = {
                "bot_token": token,
                "offset": offset,
                "timeout": timeout,
            }
            if http_get is not None:
                fetch_kwargs["http_get"] = http_get

            updates = fetch_telegram_updates(**fetch_kwargs)
            if updates:
                logger.info(f"Received {len(updates)} telegram update(s)")
                next_offset = process_telegram_updates_batch(
                    updates,
                    target_store=t_store,
                    retriever=r_retriever,
                    llm=active_llm,
                    sender=_sender,
                    article_store=a_store,
                )
                if next_offset is not None:
                    offset = next_offset
                processed_count += len(updates)
        except Exception as exc:
            logger.error(f"Error fetching/processing updates: {exc}")
            time.sleep(2.0)

        if once:
            break

        time.sleep(poll_interval)

    logger.info("Telegram polling worker stopped.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run outbound Telegram Bot long polling worker without inbound open ports."
    )
    parser.add_argument("--bot-token", help="Optional Telegram bot token override")
    parser.add_argument("--timeout", type=int, default=30, help="Long polling timeout in seconds")
    parser.add_argument("--interval", type=float, default=1.0, help="Loop interval in seconds")
    parser.add_argument("--once", action="store_true", help="Run a single polling cycle and exit")
    args = parser.parse_args()

    sys.exit(
        run_polling_worker(
            bot_token=args.bot_token,
            timeout=args.timeout,
            poll_interval=args.interval,
            once=args.once,
        )
    )


if __name__ == "__main__":
    main()
