#!/usr/bin/env bash
set -euo pipefail

INSTANCE_NAME="${GCP_INSTANCE_NAME:-marine-edge-pc}"
ZONE="${GCP_ZONE:-us-central1-a}"
FIREWALL_RULE="${GCP_FIREWALL_RULE:-allow-assist-api-8001}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${REPO_ROOT}/.venv/bin/python3"
if [[ ! -x "${PYTHON_BIN}" ]]; then
  PYTHON_BIN="python3"
fi

# 1. Warming gate check (pass/gpg)
if ! gpg-connect-agent 'keyinfo --list' /bye 2>/dev/null | awk '$7 == 1 {found=1} END {exit !found}'; then
  echo "ERROR: GPG cache is COLD. Run agy-reset to warm up credentials." >&2
  exit 1
fi

# 2. Resolve and validate allowed source IP ranges (Admin IP + Telegram Webhooks)
ADMIN_IP="${ADMIN_IP:-$(curl -s --max-time 5 https://api.ipify.org)}"
SOURCE_RANGES="$(PYTHONPATH="${REPO_ROOT}" "${PYTHON_BIN}" -c "from app.config import build_gcp_allowed_source_ranges; print(build_gcp_allowed_source_ranges('${ADMIN_IP}'))")"

echo "[1/4] Configuring GCP firewall rule ${FIREWALL_RULE} (source-ranges: ${SOURCE_RANGES})..."
if gcloud compute firewall-rules describe "${FIREWALL_RULE}" >/dev/null 2>&1; then
  gcloud compute firewall-rules update "${FIREWALL_RULE}" \
    --allow="tcp:8001" \
    --source-ranges="${SOURCE_RANGES}" \
    --quiet
else
  gcloud compute firewall-rules create "${FIREWALL_RULE}" \
    --allow="tcp:8001" \
    --source-ranges="${SOURCE_RANGES}" \
    --description="Allow restricted access to assist-api on port 8001 (Admin IP + Telegram Webhook CIDRs)" \
    --quiet
fi

# 3. Ensure 2GB Swap on marine-edge-pc (idempotent)
echo "[2/4] Ensuring 2GB swapfile on ${INSTANCE_NAME} (${ZONE})..."
gcloud compute ssh "${INSTANCE_NAME}" --zone="${ZONE}" --command="
  set -euo pipefail
  if ! sudo swapon --show | grep -q '/swapfile'; then
    if [[ ! -f /swapfile ]]; then
      sudo fallocate -l 2G /swapfile || sudo dd if=/dev/zero of=/swapfile bs=1M count=2048
      sudo chmod 600 /swapfile
      sudo mkswap /swapfile
    fi
    sudo swapon /swapfile
    if ! grep -q '^/swapfile ' /etc/fstab; then
      echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
    fi
  fi
  mkdir -p ~/assist
"

# 4. Sync source archive and start container with runtime-injected secrets
echo "[3/4] Syncing source and starting assist-api container on ${INSTANCE_NAME}..."
tar -C "${REPO_ROOT}" -czf - \
  Dockerfile \
  docker-compose.gcp.yml \
  requirements.txt \
  requirements-embeddings.txt \
  pyproject.toml \
  app \
  web | gcloud compute ssh "${INSTANCE_NAME}" --zone="${ZONE}" --command="tar -C ~/assist -xzf -"

{
  printf 'TELEGRAM_BOT_TOKEN=%s\n' "$(pass show telegram/domAssistBot/bot-token | head -n1)"
  printf 'TELEGRAM_CHAT_ID=%s\n' "$(pass show telegram/domAssistBot/chat-id | head -n1)"
  printf 'GITHUB_TOKEN=%s\n' "$(pass show github/gh-token | head -n1)"
  printf 'OLLAMA_BASE_URL=%s\n' "${OLLAMA_BASE_URL:-http://127.0.0.1:11434}"
  printf 'OLLAMA_MODEL_NAME=%s\n' "${OLLAMA_MODEL_NAME:-gemma3:12b}"
  printf 'USE_PGVECTOR=%s\n' "${USE_PGVECTOR:-false}"
} | gcloud compute ssh "${INSTANCE_NAME}" --zone="${ZONE}" --command="
  set -euo pipefail
  cd ~/assist
  if sudo docker compose version >/dev/null 2>&1; then
    sudo docker compose -f docker-compose.gcp.yml --env-file /dev/stdin up -d --build
  else
    sudo docker-compose -f docker-compose.gcp.yml --env-file /dev/stdin up -d --build
  fi
"

# 5. Verify health endpoint
EXTERNAL_IP="$(gcloud compute instances describe "${INSTANCE_NAME}" --zone="${ZONE}" --format='get(networkInterfaces[0].accessConfigs[0].natIP)')"
echo "[4/4] Verifying http://${EXTERNAL_IP}:8001/health ..."
for _ in {1..15}; do
  if curl -fsS --max-time 3 "http://${EXTERNAL_IP}:8001/health" | grep -q '"ok"'; then
    echo "Deployment verified: http://${EXTERNAL_IP}:8001/health -> ok"
    exit 0
  fi
  sleep 2
done

echo "ERROR: Health check failed for http://${EXTERNAL_IP}:8001/health" >&2
exit 1
