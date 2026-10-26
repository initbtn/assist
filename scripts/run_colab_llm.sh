#!/usr/bin/env bash
set -euo pipefail

GPU_TYPE="${COLAB_GPU_TYPE:-T4}"
DRY_RUN=false
PORT_FORWARD=false

show_help() {
  cat << 'EOF'
Usage: ./scripts/run_colab_llm.sh [options]

Provisions a Google Colab GPU runtime via google-colab-cli and starts Ollama (gemma3:12b, hermes3:8b).

Options:
  --gpu <type>        GPU accelerator type (default: T4, options: T4, L4, A100)
  --port-forward      Establish SSH port forwarding to localhost:11434 via colab ssh
  --dry-run           Print commands without executing
  -h, --help          Show this help message
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --gpu)
      if [[ $# -lt 2 || -z "${2:-}" || "${2:-}" == --* ]]; then
        echo "ERROR: --gpu requires a valid argument (e.g. T4, L4, A100)" >&2
        exit 1
      fi
      GPU_TYPE="$2"
      shift 2
      ;;
    --port-forward)
      PORT_FORWARD=true
      shift
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    -h|--help)
      show_help
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      show_help
      exit 1
      ;;
  esac
done

OLLAMA_SETUP_COMMANDS=$(cat << 'EOF'
curl -fsSL https://ollama.com/install.sh | sh
nohup ollama serve > /tmp/ollama.log 2>&1 &
sleep 4
echo "Pulling Model A (gemma3:12b)..."
ollama pull gemma3:12b
echo "Pulling Model C (hermes3:8b)..."
ollama pull hermes3:8b
echo "Ollama ready with models!"
EOF
)

if [[ "${DRY_RUN}" == "true" ]]; then
  echo "=== [DRY RUN] Google Colab GPU LLM Runner ==="
  echo "1. Provision GPU runtime:"
  echo "   colab new --gpu ${GPU_TYPE}"
  echo ""
  echo "2. Remote setup commands (via python subprocess in colab exec):"
  echo "${OLLAMA_SETUP_COMMANDS}"
  echo ""
  if [[ "${PORT_FORWARD}" == "true" ]]; then
    echo "3. Port forwarding command:"
    echo "   colab ssh -- -N -L 11434:localhost:11434"
  else
    echo "3. Cloudflare Quick Tunnel command:"
    echo "   curl -fsSL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /tmp/cloudflared && chmod +x /tmp/cloudflared"
    echo "   /tmp/cloudflared tunnel --url http://localhost:11434"
  fi
  exit 0
fi

if ! command -v colab >/dev/null 2>&1; then
  echo "ERROR: 'colab' command not found." >&2
  echo "Install it with: pip install google-colab-cli (or uv tool install google-colab-cli)" >&2
  echo "Then authenticate with: colab auth login" >&2
  exit 1
fi

echo "[1/3] Provisioning Colab runtime with GPU: ${GPU_TYPE}..."
colab new --gpu "${GPU_TYPE}"

echo "[2/3] Installing Ollama and pulling gemma3:12b & hermes3:8b..."
cat << 'PYEOF' | colab exec
import subprocess, sys

script = """
curl -fsSL https://ollama.com/install.sh | sh
nohup ollama serve > /tmp/ollama.log 2>&1 &
sleep 4
ollama pull gemma3:12b
ollama pull hermes3:8b
"""
res = subprocess.run(script, shell=True, capture_output=True, text=True)
sys.stdout.write(res.stdout)
sys.stderr.write(res.stderr)
if res.returncode != 0:
    sys.exit(res.returncode)
print("Ollama ready with models!")
PYEOF

if [[ "${PORT_FORWARD}" == "true" ]]; then
  echo "[3/3] Establishing port forwarding (11434 -> localhost:11434)..."
  echo "Run assist with OLLAMA_BASE_URL=http://localhost:11434"
  colab ssh -- -N -L 11434:localhost:11434
else
  echo "[3/3] Starting Cloudflare Quick Tunnel on Colab..."
  cat << 'PYEOF' | colab exec
import subprocess, time, re

tunnel_script = """
curl -fsSL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /tmp/cloudflared && chmod +x /tmp/cloudflared
nohup /tmp/cloudflared tunnel --url http://localhost:11434 > /tmp/cloudflared.log 2>&1 &
"""
subprocess.run(tunnel_script, shell=True, check=True)

url = None
for _ in range(15):
    time.sleep(1)
    try:
        with open("/tmp/cloudflared.log", "r", encoding="utf-8", errors="ignore") as f:
            matches = re.findall(r'https://[-a-zA-Z0-9]+\.trycloudflare\.com', f.read())
            if matches:
                url = matches[-1]
                break
    except Exception:
        pass

if url:
    print(f"\n==========================================")
    print(f"Colab Cloudflare Tunnel URL: {url}")
    print(f"==========================================")
else:
    print("Warning: Could not detect Cloudflare tunnel URL automatically. Check /tmp/cloudflared.log on Colab.")
PYEOF
  echo "Use the above URL for OLLAMA_BASE_URL in scripts/deploy-gcp.sh"
fi
