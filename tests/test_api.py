from typing import Any

from fastapi.testclient import TestClient

from app.main import create_app


class StubLLM:
    def generate(self, prompt: str) -> str:
        if "3줄" in prompt or "브리핑" in prompt:
            return (
                "1. AI 에이전트: Claude Code 및 LangChain 최신 릴리스 반영\n"
                "2. 풀스택 웹: Next.js 16 DevTools MCP 및 Cache Components 도입\n"
                "3. 인프라: Kubernetes 및 오픈소스 동향 파이프라인 통합"
            )
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
        base_ui_url="https://assist-brief.vercel.app",
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

    res_brief = client.post("/brief/send", json={"date_str": "2026-10-23"})
    assert res_brief.status_code == 200
    brief_json = res_brief.json()
    assert brief_json["sent"] is True
    assert brief_json["chat_id"] == "999888777"
    assert brief_json["article_slug"] == "2026-10-23"
    assert (
        brief_json["article_url"]
        == "https://assist-brief.vercel.app/articles/2026-10-23"
    )
    assert len(brief_json["summary_lines"]) == 3
    assert "https://assist-brief.vercel.app/articles/2026-10-23" in brief_json["brief"]
    assert sent_telegram[-1] == ("999888777", brief_json["brief"])

    # 아티클 목록 및 상세 조회 검증
    res_articles = client.get("/articles")
    assert res_articles.status_code == 200
    assert len(res_articles.json()) == 1
    assert res_articles.json()[0]["slug"] == "2026-10-23"

    res_article_detail = client.get("/articles/2026-10-23")
    assert res_article_detail.status_code == 200
    assert res_article_detail.json()["slug"] == "2026-10-23"
    assert len(res_article_detail.json()["sections"]) >= 1

    res_article_404 = client.get("/articles/non-existent-date")
    assert res_article_404.status_code == 404

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

    # 모델 A(gemma3:12b) vs C(hermes3:8b) 비교 엔드포인트 검증
    res_compare = client.post(
        "/brief/compare",
        json={"models": ["A", "C"], "date_str": "2026-10-23"},
    )
    assert res_compare.status_code == 200
    compare_json = res_compare.json()
    assert compare_json["date"] == "2026-10-23"
    assert set(compare_json["comparisons"].keys()) == {"gemma3:12b", "hermes3:8b"}
    assert len(compare_json["comparisons"]["gemma3:12b"]["summary_lines"]) == 3
    assert len(compare_json["comparisons"]["hermes3:8b"]["summary_lines"]) == 3

    # 중국계 모델(B) 요청 시 422 거부 검증
    res_compare_excluded = client.post(
        "/brief/compare",
        json={"models": ["B"], "date_str": "2026-10-23"},
    )
    assert res_compare_excluded.status_code == 422


def test_measure_ollama_generation_and_run_comparison_mocked(monkeypatch):
    import scripts.run_model_comparison as runner

    def fake_post(url: str, json: dict[str, Any], timeout: float):
        class FakeResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return {
                    "response": f"Summary from {json['model']}",
                    "eval_count": 42,
                    "eval_duration": 1_000_000_000,
                }

        return FakeResponse()

    monkeypatch.setattr("httpx.post", fake_post)

    out = runner.measure_ollama_generation(
        base_url="http://fake-ollama:11434",
        model_name="gemma3:12b",
        prompt="요약해줘",
    )
    assert out["model"] == "gemma3:12b"
    assert out["eval_count"] == 42
    assert out["tokens_per_second"] == 42.0
    assert "Summary from gemma3:12b" in out["response"]

    full = runner.run_comparison(
        base_url="http://fake-ollama:11434",
        models=["A", "C"],
        prompt="테스트",
    )
    assert set(full["results"].keys()) == {"gemma3:12b", "hermes3:8b"}

