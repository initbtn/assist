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

# 2. Configure inbound firewall (default: disabled, outbound-only mode)
ENABLE_INBOUND_8001="${ENABLE_INBOUND_8001:-false}"
if [[ "${ENABLE_INBOUND_8001}" == "true" ]]; then
  ADMIN_IP="${ADMIN_IP:-$(curl -s --max-time 5 https://api.ipify.org)}"
  SOURCE_RANGES="$(PYTHONPATH="${REPO_ROOT}" "${PYTHON_BIN}" -c "import sys; from app.config import build_gcp_allowed_source_ranges; print(build_gcp_allowed_source_ranges(sys.argv[1]))" "${ADMIN_IP}")"
  echo "[1/4] Inbound 8001 enabled: Configuring GCP firewall rule ${FIREWALL_RULE} (source-ranges: ${SOURCE_RANGES})..."
  if gcloud compute firewall-rules describe "${FIREWALL_RULE}" >/dev/null 2>&1; then
    gcloud compute firewall-rules update "${FIREWALL_RULE}" \
      --allow="tcp:8001" \
      --source-ranges="${SOURCE_RANGES}" \
      --no-disabled \
      --quiet
  else
    gcloud compute firewall-rules create "${FIREWALL_RULE}" \
      --allow="tcp:8001" \
      --source-ranges="${SOURCE_RANGES}" \
      --description="Allow restricted access to assist-api on port 8001" \
      --quiet
  fi
else
  echo "[1/4] Inbound port 8001 disabled (outbound-only mode). Ensuring firewall rule is disabled..."
  if gcloud compute firewall-rules describe "${FIREWALL_RULE}" >/dev/null 2>&1; then
    gcloud compute firewall-rules update "${FIREWALL_RULE}" --disabled --quiet >/dev/null 2>&1 || true
  fi
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
  web \
  scripts | gcloud compute ssh "${INSTANCE_NAME}" --zone="${ZONE}" --command="tar -C ~/assist -xzf -"

{
  printf 'TELEGRAM_BOT_TOKEN=%s\n' "$(pass show telegram/domAssistBot/bot-token | head -n1)"
  printf 'TELEGRAM_CHAT_ID=%s\n' "$(pass show telegram/domAssistBot/chat-id | head -n1)"
  printf 'OPS_TELEGRAM_BOT_TOKEN=%s\n' "$(pass show telegram/bot-token | head -n1)"
  printf 'OPS_TELEGRAM_CHAT_ID=%s\n' "$(pass show telegram/chat-id | head -n1)"
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
  sudo docker rm -f assist-api assist-bot 2>/dev/null || true
  if sudo docker compose version >/dev/null 2>&1; then
    sudo docker compose -f docker-compose.gcp.yml --env-file \"\${TMP_ENV}\" up -d --build --remove-orphans
  else
    sudo docker-compose -f docker-compose.gcp.yml --env-file \"\${TMP_ENV}\" up -d --build --remove-orphans
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
if [[ "${ENABLE_INBOUND_8001}" == "true" ]]; then
  EXTERNAL_IP="$(gcloud compute instances describe "${INSTANCE_NAME}" --zone="${ZONE}" --format='get(networkInterfaces[0].accessConfigs[0].natIP)')"
  echo "[4/4] Verifying http://${EXTERNAL_IP}:8001/health (inbound)..."
  for _ in {1..15}; do
    if curl -fsS --max-time 3 "http://${EXTERNAL_IP}:8001/health" | grep -q '"ok"'; then
      echo "Deployment verified: http://${EXTERNAL_IP}:8001/health -> ok"
      exit 0
    fi
    sleep 2
  done
  echo "ERROR: Health check failed for http://${EXTERNAL_IP}:8001/health" >&2
  exit 1
else
  echo "[4/4] Verifying internal health via SSH (http://127.0.0.1:8001/health)..."
  for _ in {1..15}; do
    if gcloud compute ssh "${INSTANCE_NAME}" --zone="${ZONE}" --command="curl -fsS --max-time 3 http://127.0.0.1:8001/health" 2>/dev/null | grep -q '"ok"'; then
      echo "Deployment verified internally: http://127.0.0.1:8001/health -> ok (inbound port 8001 safely closed)"
      exit 0
    fi
    sleep 2
  done
  echo "ERROR: Internal health check failed on ${INSTANCE_NAME}" >&2
  exit 1
fi
