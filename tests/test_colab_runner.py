import subprocess
import os

SCRIPT_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "scripts", "run_colab_llm.sh")
)


def test_run_colab_llm_dry_run_default():
    res = subprocess.run(
        [SCRIPT_PATH, "--dry-run"],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0
    assert "colab new --gpu T4" in res.stdout
    assert "ollama pull gemma3:12b" in res.stdout
    assert "ollama pull hermes3:8b" in res.stdout
    assert "ollama serve" in res.stdout
    assert "cloudflared tunnel" in res.stdout


def test_run_colab_llm_dry_run_custom_gpu_and_port_forward():
    res = subprocess.run(
        [SCRIPT_PATH, "--dry-run", "--gpu", "L4", "--port-forward"],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0
    assert "colab new --gpu L4" in res.stdout
    assert "colab ssh -- -N -L 11434:localhost:11434" in res.stdout


def test_run_colab_llm_gpu_missing_argument():
    res = subprocess.run(
        [SCRIPT_PATH, "--gpu"],
        capture_output=True,
        text=True,
    )
    assert res.returncode != 0
    assert "ERROR: --gpu requires a valid argument" in res.stderr


def test_run_colab_llm_help():
    res = subprocess.run(
        [SCRIPT_PATH, "--help"],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0
    assert "Usage:" in res.stdout
    assert "--dry-run" in res.stdout
    assert "--gpu" in res.stdout
    assert "--port-forward" in res.stdout
