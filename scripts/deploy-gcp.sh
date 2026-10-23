#!/usr/bin/env bash
set -euo pipefail

INSTANCE_NAME="${GCP_INSTANCE_NAME:-marine-edge-pc}"
ZONE="${GCP_ZONE:-us-central1-a}"
FIREWALL_RULE="${GCP_FIREWALL_RULE:-allow-assist-api-8001}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MAIN_REPO_ROOT="$(cd "$(git -C "${REPO_ROOT}" rev-parse --git-common-dir)/.." && pwd)"
if [[ -x "${REPO_ROOT}/.venv/bin/python3" ]]; then
  PYTHON_BIN="${REPO_ROOT}/.venv/bin/python3"
elif [[ -x "${MAIN_REPO_ROOT}/.venv/bin/python3" ]]; then
  PYTHON_BIN="${MAIN_REPO_ROOT}/.venv/bin/python3"
else
  PYTHON_BIN="python3"
fi

# 1. Warming gate check (pass/gpg)
if ! gpg-connect-agent 'keyinfo --list' /bye 2>/dev/null | awk '$7 == 1 {found=1} END {exit !found}'; then
  echo "ERROR: GPG cache is COLD. Run agy-reset to warm up credentials." >&2
  exit 1
fi

# 2. Resolve and validate allowed source IP ranges via sys.argv[1]
ADMIN_IP="${ADMIN_IP:-$(curl -s --max-time 5 https://api.ipify.org)}"
SOURCE_RANGES="$(PYTHONPATH="${REPO_ROOT}" "${PYTHON_BIN}" -c "import sys; from app.config import build_gcp_allowed_source_ranges; print(build_gcp_allowed_source_ranges(sys.argv[1]))" "${ADMIN_IP}")"

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

# 3. Ensure 2GB Swap + vm.swappiness=10 on marine-edge-pc (idempotent)
echo "[2/4] Ensuring 2GB swapfile and vm.swappiness=10 on ${INSTANCE_NAME} (${ZONE})..."
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
  echo 'vm.swappiness=10' | sudo tee /etc/sysctl.d/99-swap.conf >/dev/null
  sudo sysctl -w vm.swappiness=10 >/dev/null
  mkdir -p ~/assist
"

# 4. Sync source archive, start container via RAM tmpfs (/dev/shm), and purge swap after build
echo "[3/4] Syncing source, starting assist-api container, and purging residual swap on ${INSTANCE_NAME}..."
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
  TMP_ENV=\"/dev/shm/assist-env.\$\$\"
  umask 077
  trap 'shred -u \"\${TMP_ENV}\" 2>/dev/null || rm -f \"\${TMP_ENV}\"' EXIT
  cat > \"\${TMP_ENV}\"
  cd ~/assist
  if sudo docker compose version >/dev/null 2>&1; then
    sudo docker compose -f docker-compose.gcp.yml --env-file \"\${TMP_ENV}\" up -d --build
  else
    sudo docker-compose -f docker-compose.gcp.yml --env-file \"\${TMP_ENV}\" up -d --build
  fi

  # Drop build pagecache and purge swap if SwapUsed > 0 and MemAvailable >= SwapUsed + 64MB
  sync
  echo 1 | sudo tee /proc/sys/vm/drop_caches >/dev/null || true
  MEM_AVAIL_KB=\$(awk '/^MemAvailable:/ {print \$2}' /proc/meminfo)
  SWAP_TOTAL_KB=\$(awk '/^SwapTotal:/ {print \$2}' /proc/meminfo)
  SWAP_FREE_KB=\$(awk '/^SwapFree:/ {print \$2}' /proc/meminfo)
  SWAP_USED_KB=\$((SWAP_TOTAL_KB - SWAP_FREE_KB))
  if (( SWAP_USED_KB > 0 && MEM_AVAIL_KB >= SWAP_USED_KB + 65536 )); then
    sudo swapoff /swapfile && sudo swapon /swapfile
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
