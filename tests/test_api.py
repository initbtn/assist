from fastapi.testclient import TestClient

from app.main import create_app


class StubLLM:
    def generate(self, prompt: str) -> str:
        if "브리핑" in prompt:
            return "🌅 도메인별 아침 브리핑 요약"
        return "요청하신 기술 동향 답변입니다."


def test_api_end_to_end_targets_ingest_query_brief_webhook_and_collect():
    sent_telegram: list[tuple[str, str]] = []

    def fake_sender(chat_id: str, text: str) -> None:
        sent_telegram.append((chat_id, text))

    def fake_github_get(url: str) -> list[dict]:
        return [
            {
                "tag_name": "v1.0.0",
                "name": "Release 1.0",
                "body": f"Release notes from {url}",
                "html_url": f"{url}/v1.0.0",
                "published_at": "2026-10-23T00:00:00Z",
                "draft": False,
            }
        ]

    app = create_app(
        llm=StubLLM(),
        telegram_sender=fake_sender,
        github_http_get=fake_github_get,
        webhook_secret="my-secret-token",
        default_chat_id="999888777",
    )
    client = TestClient(app)

    res_health = client.get("/health")
    assert res_health.status_code == 200
    assert res_health.json() == {"status": "ok"}

    res_targets = client.get("/targets")
    assert res_targets.status_code == 200
    initial_count = len(res_targets.json())
    assert initial_count >= 3

    new_target = {
        "domain": "infra_devops",
        "name": "Cilium",
        "source_type": "github_repo",
        "source_config": {"repo": "cilium/cilium"},
    }
    res_create = client.post("/targets", json=new_target)
    assert res_create.status_code == 201
    target_id = res_create.json()["id"]

    res_dup_target = client.post("/targets", json=new_target)
    assert res_dup_target.status_code == 409

    res_patch = client.patch(f"/targets/{target_id}", json={"is_active": False})
    assert res_patch.status_code == 200
    assert res_patch.json()["is_active"] is False

    res_not_found = client.patch("/targets/non-existent", json={"is_active": True})
    assert res_not_found.status_code == 404

    ingest_payload = {
        "text": "Next.js 16 ships native DevTools MCP server and Cache Components.",
        "metadata": {
            "domain": "fullstack_web",
            "target_name": "Next.js",
            "source_url": "https://nextjs.org/blog/next-16",
        },
    }
    res_ingest1 = client.post("/ingest", json=ingest_payload)
    assert res_ingest1.status_code == 200
    assert res_ingest1.json() == {"ingested_chunks": 1, "skipped_duplicate": False}

    res_ingest2 = client.post("/ingest", json=ingest_payload)
    assert res_ingest2.status_code == 200
    assert res_ingest2.json() == {"ingested_chunks": 0, "skipped_duplicate": True}

    res_query = client.post(
        "/query",
        json={"question": "Next.js 16 기능은?", "domain": "fullstack_web"},
    )
    assert res_query.status_code == 200
    assert res_query.json() == {
        "answer": "요청하신 기술 동향 답변입니다.",
        "sources": ["https://nextjs.org/blog/next-16"],
    }

    res_collect = client.post(
        "/collect",
        json={"domain": "ai_agent_llm", "include_seed": True},
    )
    assert res_collect.status_code == 200
    collect_data = res_collect.json()
    assert collect_data["checked_targets"] == 2
    assert collect_data["ingested_documents"] == 2
    assert collect_data["seeded_chunks"] >= 4

    res_collect_dup = client.post(
        "/collect",
        json={"domain": "ai_agent_llm", "include_seed": True},
    )
    assert res_collect_dup.status_code == 200
    assert res_collect_dup.json()["ingested_documents"] == 0
    assert res_collect_dup.json()["skipped_duplicates"] == 2
    assert res_collect_dup.json()["seeded_chunks"] == 0

    res_brief = client.post("/brief/send", json={})
    assert res_brief.status_code == 200
    assert res_brief.json() == {
        "sent": True,
        "chat_id": "999888777",
        "brief": "🌅 도메인별 아침 브리핑 요약",
    }
    assert sent_telegram[-1] == ("999888777", "🌅 도메인별 아침 브리핑 요약")

    res_forbidden = client.post(
        "/webhook/telegram",
        headers={"X-Telegram-Bot-Api-Secret-Token": "wrong-token"},
        json={"message": {"chat": {"id": 555}, "text": "/brief"}},
    )
    assert res_forbidden.status_code == 403

    res_webhook = client.post(
        "/webhook/telegram",
        headers={"X-Telegram-Bot-Api-Secret-Token": "my-secret-token"},
        json={"message": {"chat": {"id": 555}, "text": "Next.js 16 알려줘"}},
    )
    assert res_webhook.status_code == 200
    assert "https://nextjs.org/blog/next-16" in res_webhook.json()["reply"]
    assert sent_telegram[-1][0] == "555"
