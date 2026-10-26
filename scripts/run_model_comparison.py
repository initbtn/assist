import argparse
import json
import time
from typing import Any

import httpx


def compare_brief_api(
    api_url: str,
    *,
    models: list[str] | None = None,
    domain: str | None = None,
    date_str: str | None = None,
    timeout: float = 180.0,
    http_client: Any | None = None,
) -> dict[str, Any]:
    target_url = f"{api_url.rstrip('/')}/brief/compare"
    payload: dict[str, Any] = {
        "models": models or ["A", "C"],
    }
    if domain:
        payload["domain"] = domain
    if date_str:
        payload["date_str"] = date_str

    start = time.perf_counter()
    if http_client is not None:
        resp = http_client.post(target_url, json=payload)
    else:
        resp = httpx.post(target_url, json=payload, timeout=timeout)
    resp.raise_for_status()
    elapsed = time.perf_counter() - start

    data = resp.json()
    return {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "api_url": target_url,
        "elapsed_seconds": round(elapsed, 2),
        "requested_models": payload["models"],
        "date": data.get("date"),
        "comparisons": data.get("comparisons", {}),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark POST /brief/compare on assist API (Gemma 3 vs Hermes 3)"
    )
    parser.add_argument(
        "--api-url",
        default="http://127.0.0.1:8000",
        help="assist API base URL (e.g. http://127.0.0.1:8000 or http://34.133.74.29:8001)",
    )
    parser.add_argument(
        "--models",
        nargs="+",
        default=["A", "C"],
        help="Model presets or names to compare (default: A C)",
    )
    parser.add_argument("--domain", help="Optional domain filter")
    parser.add_argument("--date-str", help="Optional date string (YYYY-MM-DD)")
    parser.add_argument("--output", help="Optional output JSON file path")
    args = parser.parse_args()

    print(f"Calling POST {args.api_url}/brief/compare with models {args.models} ...")
    report = compare_brief_api(
        args.api_url,
        models=args.models,
        domain=args.domain,
        date_str=args.date_str,
    )
    formatted = json.dumps(report, indent=2, ensure_ascii=False)
    print("\n=== POST /brief/compare Benchmark Result ===")
    print(formatted)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(formatted)
        print(f"\nSaved report to {args.output}")


if __name__ == "__main__":
    main()
