import pytest

from app.targets import (
    DEFAULT_SEED_TARGETS,
    InMemoryDeduplicationStore,
    InMemoryTargetStore,
    ResearchTargetCreate,
    compute_content_hash,
)


def test_seed_targets_cover_all_three_domains():
    store = InMemoryTargetStore(seed=True)
    all_targets = store.list_targets()
    domains = {t.domain for t in all_targets}

    assert domains == {"ai_agent_llm", "fullstack_web", "infra_devops"}
    assert len(all_targets) == len(DEFAULT_SEED_TARGETS)


def test_target_store_crud_and_filtering():
    store = InMemoryTargetStore(seed=False)
    created = store.add_target(
        ResearchTargetCreate(
            domain="ai_agent_llm",
            name="Claude Code",
            source_type="github_repo",
            source_config={"repo": "anthropics/claude-code"},
        )
    )
    second = store.add_target(
        ResearchTargetCreate(
            domain="infra_devops",
            name="Terraform",
            source_type="github_repo",
            source_config={"repo": "hashicorp/terraform"},
        )
    )

    assert [t.name for t in store.list_targets(domain="ai_agent_llm")] == ["Claude Code"]

    updated = store.set_active(second.id, is_active=False)
    assert updated.is_active is False
    assert [t.name for t in store.list_targets(active_only=True)] == ["Claude Code"]
    assert [t.name for t in store.list_targets(active_only=False)] == [
        "Claude Code",
        "Terraform",
    ]


def test_target_store_rejects_duplicate_and_invalid_inputs():
    store = InMemoryTargetStore(seed=False)
    payload = ResearchTargetCreate(
        domain="fullstack_web",
        name="Next.js",
        source_type="github_repo",
        source_config={"repo": "vercel/next.js"},
    )
    store.add_target(payload)

    with pytest.raises(ValueError, match="already exists"):
        store.add_target(payload)

    with pytest.raises(KeyError, match="not found"):
        store.set_active("non-existent-id", is_active=False)


def test_compute_content_hash_normalizes_whitespace_and_rejects_empty():
    h1 = compute_content_hash("  Next.js 16   ships   MCP  \n\t server ")
    h2 = compute_content_hash("Next.js 16 ships MCP server")

    assert h1 == h2
    assert len(h1) == 64

    with pytest.raises(ValueError, match="empty"):
        compute_content_hash("   \n\t  ")


def test_deduplication_store_detects_exact_and_updated_content():
    dedup = InMemoryDeduplicationStore()
    url = "https://nextjs.org/blog/next-16"
    hash_v1 = compute_content_hash("Release v16.0 notes")
    hash_v2 = compute_content_hash("Release v16.1 updated notes")

    assert dedup.is_duplicate(url, hash_v1) is False

    dedup.record(
        source_url=url,
        content_hash=hash_v1,
        domain="fullstack_web",
        target_name="Next.js",
    )

    assert dedup.is_duplicate(url, hash_v1) is True
    assert dedup.is_duplicate(url, hash_v2) is False
