#!/usr/bin/env bash
# run-ansible-cron.sh: marine-edge-pc VM에 assist 일일 수집·브리핑 cron 잡을 선언적으로 적용
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ANSIBLE_DIR="$REPO_ROOT/ansible"

echo "[INFO] Running Ansible playbook for assist daily cron configuration..."
ansible-playbook -i "$ANSIBLE_DIR/hosts.ini" "$ANSIBLE_DIR/playbook-cron.yml"

echo "[INFO] Verifying crontab on target host..."
gcloud compute ssh marine-edge-pc --zone=us-central1-a --command="crontab -l"
