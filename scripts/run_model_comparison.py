import argparse
import json
import time
from typing import Any

import httpx

from app.rag import OLLAMA_MODEL_PRESETS, resolve_ollama_model_name


def measure_ollama_generation(
    base_url: str,
    model_name: str,
    prompt: str,
    *,
    timeout: float = 120.0,
) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}/api/generate"
    payload = {
        "model": model_name,
        "prompt": prompt,
        "stream": False,
    }
    start = time.perf_counter()
    resp = httpx.post(url, json=payload, timeout=timeout)
    resp.raise_for_status()
    elapsed = time.perf_counter() - start
    data = resp.json()

    response_text = str(data.get("response") or "").strip()
    eval_count = data.get("eval_count") or len(response_text.split())
    eval_duration_ns = data.get("eval_duration") or int(elapsed * 1e9)
    tok_per_sec = (
        (eval_count / (eval_duration_ns / 1e9)) if eval_duration_ns > 0 else 0.0
    )

    return {
        "model": model_name,
        "elapsed_seconds": round(elapsed, 2),
        "eval_count": eval_count,
        "tokens_per_second": round(tok_per_sec, 1),
        "response": response_text,
    }


def run_comparison(
    base_url: str,
    models: list[str] | None = None,
    prompt: str | None = None,
) -> dict[str, Any]:
    target_models = models or ["A", "C"]
    test_prompt = (
        prompt
        or "다음 기술 동향을 개발자를 위해 핵심만 한국어 3줄 요약해줘:\n"
        "- Next.js 16: 내장 DevTools MCP 서버 탑재 및 Cache Components 정식화\n"
        "- NestJS 12: ESM 전면 전환 및 Standard Schema(Zod, Valibot) 지원\n"
        "- Claude Code: 서브에이전트 오케스트레이션 및 review-army 규율 연동"
    )

    results: dict[str, Any] = {}
    for item in target_models:
        resolved = resolve_ollama_model_name(item)
        print(f"Testing model {item} ({resolved}) at {base_url} ...")
        metrics = measure_ollama_generation(base_url, resolved, test_prompt)
        results[resolved] = metrics
        print(
            f"  -> {metrics['elapsed_seconds']}s, {metrics['tokens_per_second']} t/s"
        )

    return {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "base_url": base_url,
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark Gemma 3 vs Hermes 3 on remote Ollama"
    )
    parser.add_argument(
        "--base-url", required=True, help="Ollama base URL (e.g. Cloudflare tunnel URL)"
    )
    parser.add_argument(
        "--models", nargs="+", default=["A", "C"], help="Models or presets (A, C)"
    )
    parser.add_argument("--output", help="Optional output JSON file path")
    args = parser.parse_args()

    report = run_comparison(args.base_url, models=args.models)
    formatted = json.dumps(report, indent=2, ensure_ascii=False)
    print("\n=== Benchmark Summary ===")
    print(formatted)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(formatted)
        print(f"\nSaved report to {args.output}")


if __name__ == "__main__":
    main()
