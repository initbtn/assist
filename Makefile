PYTEST ?= $(shell if [ -x .venv/bin/pytest ]; then echo .venv/bin/pytest; elif [ -x "$$(git rev-parse --git-common-dir 2>/dev/null)/../.venv/bin/pytest" ]; then echo "$$(git rev-parse --git-common-dir 2>/dev/null)/../.venv/bin/pytest"; else which pytest 2>/dev/null || echo pytest; fi)
COLAB ?= $(shell if [ -x .venv/bin/colab ]; then echo .venv/bin/colab; elif [ -x "$$(git rev-parse --git-common-dir 2>/dev/null)/../.venv/bin/colab" ]; then echo "$$(git rev-parse --git-common-dir 2>/dev/null)/../.venv/bin/colab"; else which colab 2>/dev/null || echo colab; fi)

.PHONY: help test colab-login colab-llm colab-dry colab-ssh compare deploy bot-logs

help:
	@echo "assist 프로젝트 주요 명령어:"
	@echo "  make test          - 전체 단위/통합 테스트 실행"
	@echo "  make colab-login   - Google Colab CLI 계정 인증"
	@echo "  make colab-llm     - Colab T4 GPU 세션 생성 및 Ollama 기동 (터널 생성)"
	@echo "  make colab-dry     - Colab GPU 런처 dry-run (명령어 템플릿 확인)"
	@echo "  make colab-ssh     - Colab GPU SSH 포트포워딩 (로컬 11434 바인딩)"
	@echo "  make compare       - Gemma 3 vs Hermes 3 벤치마크 비교 실행"
	@echo "  make deploy        - GCP marine-edge-pc 실서버 배포"
	@echo "  make bot-logs      - GCP 텔레그램 봇 실시간 로그 확인"

test:
	$(PYTEST) -q

colab-login:
	$(COLAB) status || $(COLAB) new --help

colab-llm:
	./scripts/run_colab_llm.sh

colab-dry:
	./scripts/run_colab_llm.sh --dry-run

colab-ssh:
	./scripts/run_colab_llm.sh --port-forward

compare:
	./scripts/compare-models.sh

deploy:
	./scripts/deploy-gcp.sh

bot-logs:
	gcloud compute ssh marine-edge-pc --zone=us-central1-a --command="sudo docker logs -f assist-bot"
