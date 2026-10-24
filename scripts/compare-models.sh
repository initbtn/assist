#!/usr/bin/env bash
set -euo pipefail

OLLAMA_URL="${1:-${OLLAMA_BASE_URL:-}}"
if [[ -z "${OLLAMA_URL}" ]]; then
  echo "Usage: $0 <OLLAMA_BASE_URL>" >&2
  echo "Example: $0 https://xxxx.trycloudflare.com" >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${REPO_ROOT}/.venv/bin/python3"
if [[ ! -x "${PYTHON_BIN}" ]]; then
  PYTHON_BIN="python3"
fi

PYTHONPATH="${REPO_ROOT}" "${PYTHON_BIN}" "${REPO_ROOT}/scripts/run_model_comparison.py" \
  --base-url "${OLLAMA_URL}" \
  --models A C \
  --output "${REPO_ROOT}/docs/benchmark-gemma3-vs-hermes3.json"
