import pytest

from app.collectors import (
    build_github_headers,
    collect_and_ingest_targets,
    fetch_github_releases,
    seed_initial_knowledge,
)
from app.config import Settings, resolve_pass_secret
from app.rag import FakeMemoryRetriever
from app.targets import (
    InMemoryDeduplicationStore,
    InMemoryTargetStore,
    ResearchTargetCreate,
)


def test_fetch_github_releases_filters_draft_and_empty_and_validates_repo():
    sample_releases = [
        {
            "tag_name": "v16.3.0",
            "name": "Next.js 16.3",
            "body": "Adds experimental native Rust React Compiler.",
            "html_url": "https://github.com/vercel/next.js/releases/tag/v16.3.0",
            "published_at": "2026-06-15T00:00:00Z",
            "draft": False,
        },
        {
            "tag_name": "v16.4.0-draft",
            "name": "Draft Release",
            "body": "Work in progress",
            "html_url": "https://github.com/vercel/next.js/releases/tag/v16.4.0",
            "published_at": "2026-06-20T00:00:00Z",
            "draft": True,
        },
        {
            "tag_name": "",
            "name": "   ",
            "body": "   ",
            "html_url": "https://github.com/vercel/next.js/releases/tag/empty",
            "published_at": "2026-06-10T00:00:00Z",
            "draft": False,
        },
    ]

    called_urls: list[str] = []

    def fake_get(url: str) -> list[dict]:
        called_urls.append(url)
        return sample_releases

    items = fetch_github_releases("vercel/next.js", http_get=fake_get, per_page=3)

    assert called_urls == [
        "https://api.github.com/repos/vercel/next.js/releases?per_page=3"
    ]
    assert len(items) == 1
    assert items[0].title == "Next.js 16.3 (v16.3.0)"
    assert items[0].source_url == "https://github.com/vercel/next.js/releases/tag/v16.3.0"
    assert "Rust React Compiler" in items[0].content

    for invalid_repo in ["", "vercel", "vercel/", "/next.js", "a/b/c"]:
        with pytest.raises(ValueError, match="repo"):
            fetch_github_releases(invalid_repo, http_get=fake_get)


def test_collect_and_ingest_targets_aggregates_new_and_duplicate_counts():
    target_store = InMemoryTargetStore(seed=False)
    target_store.add_target(
        ResearchTargetCreate(
            domain="fullstack_web",
            name="Next.js",
            source_type="github_repo",
            source_config={"repo": "vercel/next.js"},
        )
    )
    target_store.add_target(
        ResearchTargetCreate(
            domain="infra_devops",
            name="Terraform",
            source_type="github_repo",
            source_config={"repo": "hashicorp/terraform"},
        )
    )

    def fake_get(url: str) -> list[dict]:
        if "vercel/next.js" in url:
            return [
                {
                    "tag_name": "v16.0.0",
                    "name": "Next.js 16",
                    "body": "Cache Components and native MCP server.",
                    "html_url": "https://github.com/vercel/next.js/releases/tag/v16.0.0",
                    "published_at": "2025-10-21T00:00:00Z",
                    "draft": False,
                }
            ]
        return [
            {
                "tag_name": "v1.10.0",
                "name": "Terraform 1.10",
                "body": "State locking improvements.",
                "html_url": "https://github.com/hashicorp/terraform/releases/tag/v1.10.0",
                "published_at": "2026-01-10T00:00:00Z",
                "draft": False,
            }
        ]

    retriever = FakeMemoryRetriever()
    dedup = InMemoryDeduplicationStore()

    first_run = collect_and_ingest_targets(
        target_store=target_store,
        vector_store=retriever,
        dedup_store=dedup,
        http_get=fake_get,
    )
    assert first_run.checked_targets == 2
    assert first_run.fetched_items == 2
    assert first_run.ingested_documents == 2
    assert first_run.ingested_chunks == 2
    assert first_run.skipped_duplicates == 0

    second_run = collect_and_ingest_targets(
        target_store=target_store,
        vector_store=retriever,
        dedup_store=dedup,
        http_get=fake_get,
    )
    assert second_run.checked_targets == 2
    assert second_run.fetched_items == 2
    assert second_run.ingested_documents == 0
    assert second_run.ingested_chunks == 0
    assert second_run.skipped_duplicates == 2


def test_seed_initial_knowledge_is_idempotent():
    retriever = FakeMemoryRetriever()
    dedup = InMemoryDeduplicationStore()

    first_chunks = seed_initial_knowledge(
        vector_store=retriever,
        dedup_store=dedup,
    )
    second_chunks = seed_initial_knowledge(
        vector_store=retriever,
        dedup_store=dedup,
    )

    assert first_chunks >= 4
    assert second_chunks == 0
    domains = {d.metadata.get("domain") for d in retriever.docs}
    assert domains == {"ai_agent_llm", "fullstack_web", "infra_devops"}


def test_resolve_pass_secret_uses_first_line_and_handles_errors():
    assert (
        resolve_pass_secret(
            "telegram/domAssistBot/bot-token",
            runner=lambda key: "123456:ABCDEF\nextra-metadata\n",
        )
        == "123456:ABCDEF"
    )
    assert (
        resolve_pass_secret(
            "telegram/missing",
            runner=lambda key: (_ for _ in ()).throw(RuntimeError("not found")),
        )
        == ""
    )
    with pytest.raises(ValueError, match="key_path"):
        resolve_pass_secret("   ", runner=lambda key: "val")


def test_settings_resolved_telegram_secrets_use_dom_assist_bot_pass_paths(monkeypatch):
    requested_keys: list[str] = []

    def fake_resolve(key_path: str) -> str:
        requested_keys.append(key_path)
        if key_path == "telegram/domAssistBot/bot-token":
            return "bot-token-from-pass"
        if key_path == "telegram/domAssistBot/chat-id":
            return "-100987654321"
        return ""

    monkeypatch.setattr("app.config.resolve_pass_secret", fake_resolve)

    cfg = Settings(telegram_bot_token="", telegram_chat_id="")
    assert cfg.resolved_telegram_bot_token() == "bot-token-from-pass"
    assert cfg.resolved_telegram_chat_id() == "-100987654321"
    assert requested_keys == [
        "telegram/domAssistBot/bot-token",
        "telegram/domAssistBot/chat-id",
    ]

    explicit_cfg = Settings(
        telegram_bot_token="  explicit-token  ",
        telegram_chat_id="  -100111222  ",
    )
    assert explicit_cfg.resolved_telegram_bot_token() == "explicit-token"
    assert explicit_cfg.resolved_telegram_chat_id() == "-100111222"
    assert len(requested_keys) == 2


def test_build_github_headers_includes_bearer_token_when_present():
    assert build_github_headers("  ghp_test123  ") == {
        "Accept": "application/vnd.github+json",
        "Authorization": "Bearer ghp_test123",
    }
    assert build_github_headers("   ") == {
        "Accept": "application/vnd.github+json",
    }
    assert build_github_headers(None) == {
        "Accept": "application/vnd.github+json",
    }
