#!/usr/bin/env bash
set -euo pipefail

API_URL="${1:-${ASSIST_API_URL:-http://127.0.0.1:8000}}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${REPO_ROOT}/.venv/bin/python3"
if [[ ! -x "${PYTHON_BIN}" ]]; then
  PYTHON_BIN="python3"
fi

PYTHONPATH="${REPO_ROOT}" "${PYTHON_BIN}" "${REPO_ROOT}/scripts/run_model_comparison.py" \
  --api-url "${API_URL}" \
  --models A C \
  --output "${REPO_ROOT}/docs/benchmark-gemma3-vs-hermes3.json"
