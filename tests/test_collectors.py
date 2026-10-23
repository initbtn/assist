import pytest

from app.collectors import (
    build_github_headers,
    collect_and_ingest_targets,
    fetch_github_releases,
    seed_initial_knowledge,
)
from app.config import (
    Settings,
    build_gcp_allowed_source_ranges,
    resolve_pass_secret,
    should_purge_swap,
)
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


def test_build_gcp_allowed_source_ranges_four_boundary_cases():
    # 1) 정상값: 단일 공인 IPv4 -> /32 정규화 + Telegram 웹훅 CIDR 결합
    assert (
        build_gcp_allowed_source_ranges("39.113.59.152")
        == "39.113.59.152/32,149.154.160.0/20,91.108.4.0/22"
    )
    assert (
        build_gcp_allowed_source_ranges(
            "39.113.59.152", include_telegram_webhooks=False
        )
        == "39.113.59.152/32"
    )

    # 2) 맞지만 헷갈리는 값: 앞뒤 공백 및 이미 /32 또는 서브넷이 붙은 CIDR 입력
    assert (
        build_gcp_allowed_source_ranges("  39.113.59.152/32  ")
        == "39.113.59.152/32,149.154.160.0/20,91.108.4.0/22"
    )
    assert (
        build_gcp_allowed_source_ranges(
            " 203.0.113.0/24 ", include_telegram_webhooks=False
        )
        == "203.0.113.0/24"
    )

    # 3) 일부만 맞는 값: 절단된 IP("39.113.59."), 슬래시 뒤 프리픽스 누락("39.113.59.152/"), 공백 문자열
    with pytest.raises(ValueError, match="admin_ip"):
        build_gcp_allowed_source_ranges("39.113.59.")
    with pytest.raises(ValueError, match="admin_ip"):
        build_gcp_allowed_source_ranges("39.113.59.152/")
    with pytest.raises(ValueError, match="admin_ip"):
        build_gcp_allowed_source_ranges("   ")

    # 4) 완전히 틀린 값: 0.0.0.0/0 전체 개방(보안 정책 위반) 또는 숫자가 아닌 임의 문자열
    with pytest.raises(ValueError, match="0.0.0.0/0"):
        build_gcp_allowed_source_ranges("0.0.0.0/0")
    with pytest.raises(ValueError, match="admin_ip"):
        build_gcp_allowed_source_ranges("not-an-ip-address")


def test_should_purge_swap_four_boundary_cases():
    # 1) 정상값: 사용 중인 Swap이 있고(>0), 가용 RAM이 (Swap 사용량 + 안전 마진 64MB) 이상일 때 True
    assert should_purge_swap(mem_available_kb=400_000, swap_used_kb=100_000) is True

    # 2) 맞지만 헷갈리는 값: 정확히 경계치(swap_used + safety_margin == mem_available)일 때 True, Swap이 0이면 False
    assert (
        should_purge_swap(
            mem_available_kb=165_536, swap_used_kb=100_000, safety_margin_kb=65_536
        )
        is True
    )
    assert should_purge_swap(mem_available_kb=500_000, swap_used_kb=0) is False

    # 3) 일부만 맞는 값: 가용 RAM이 Swap 사용량보다는 크지만 안전 마진(64MB)을 합치면 부족한 경우 False (OOM 방지)
    assert (
        should_purge_swap(
            mem_available_kb=120_000, swap_used_kb=100_000, safety_margin_kb=65_536
        )
        is False
    )

    # 4) 완전히 틀린 값: 음수 메모리/스왑/마진 입력 시 ValueError
    with pytest.raises(ValueError, match="non-negative"):
        should_purge_swap(mem_available_kb=-1, swap_used_kb=100)
    with pytest.raises(ValueError, match="non-negative"):
        should_purge_swap(mem_available_kb=100_000, swap_used_kb=-5)
    with pytest.raises(ValueError, match="non-negative"):
        should_purge_swap(
            mem_available_kb=100_000, swap_used_kb=10, safety_margin_kb=-1
        )
