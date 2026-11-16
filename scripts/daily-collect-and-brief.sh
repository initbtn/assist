#!/usr/bin/env bash
# daily-collect-and-brief.sh: assist 일일 동향 수집 및 일일 브리핑 자동 생성 배치 스크립트
# 사용법: ./scripts/daily-collect-and-brief.sh [API_BASE_URL]
set -euo pipefail

API_BASE="${1:-http://127.0.0.1:8001}"
PER_TARGET_LIMIT="${PER_TARGET_LIMIT:-5}"

echo "[INFO] Starting daily collection against $API_BASE (per_target_limit=$PER_TARGET_LIMIT)..."

# 1. 대상 오픈소스 동향 수집 및 RAG 지식 베이스 임베딩 (씨드 지식 포함)
COLLECT_RESP="$(curl -s -f -X POST "$API_BASE/collect" \
  -H "Content-Type: application/json" \
  -d "{\"include_seed\": true, \"per_target_limit\": $PER_TARGET_LIMIT}")"

echo "[INFO] Collection result: $COLLECT_RESP"

# 2. 오늘 날짜 기준 듀얼 모델 브리핑 자동 합성 및 비교 생성
echo "[INFO] Generating daily brief comparison..."
BRIEF_RESP="$(curl -s -f -X POST "$API_BASE/brief/compare" \
  -H "Content-Type: application/json" \
  -d '{"models": ["A", "C"]}')"

echo "[INFO] Daily brief generation result:"
echo "$BRIEF_RESP" | jq -r '.date // "OK"' 2>/dev/null || echo "Brief completed."

echo "[INFO] Daily collect and brief pipeline completed successfully."
