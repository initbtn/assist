# Google Colab CLI 기반 T4 GPU Ollama 헤드리스 연동 가이드

`assist` 프로젝트는 초경량 GCP 인스턴스(`marine-edge-pc`, vCPU) 환경에서 가벼운 봇과 API를 운영하고, 한국어 3줄 요약용 무거운 오픈 LLM(`gemma3:12b`, `hermes3:8b`) 추론은 **Google Colab의 T4 GPU**를 헤드리스로 프로비저닝하여 연동합니다.

---

## 1. 사전 준비: `google-colab-cli` 설치 및 로그인

구글 공식 Colab CLI를 로컬 머신에 설치하고 구글 계정을 인증합니다.

```bash
# 1. 패키지 설치
pip install google-colab-cli
# 또는 uv 사용 시
# uv tool install google-colab-cli

# 2. 구글 계정 브라우저 인증 (1회 수행, 토큰은 ~/.config에 안전 저장)
colab auth login
```

---

## 2. 런처 스크립트 (`scripts/run_colab_llm.sh`)

저장소에 포함된 런처 스크립트를 통해 브라우저 접속 없이 터미널에서 T4 GPU 세션을 띄우고 Ollama 데몬을 기동할 수 있습니다.

### 사용법

```bash
# 기본 실행: T4 GPU 세션 생성 + Ollama(gemma3:12b, hermes3:8b) 기동 + Cloudflare 터널 생성
./scripts/run_colab_llm.sh

# dry-run 모드 (실제 실행하지 않고 명령어 템플릿 확인)
./scripts/run_colab_llm.sh --dry-run

# GPU 유형 변경 (예: L4, A100 등)
./scripts/run_colab_llm.sh --gpu L4

# SSH 포트포워딩 모드 (로컬 11434로 직통 바인딩)
./scripts/run_colab_llm.sh --port-forward
```

---

## 3. GCP `assist` 서비스와의 연동 워크플로우

### [방법 A] Cloudflare 터널 방식 (추천)
1. `./scripts/run_colab_llm.sh` 실행 시 터미널에 출력되는 HTTPS 터널 URL 확인:
   ```text
   https://xxxx.trycloudflare.com
   ```
2. 해당 주소를 `OLLAMA_BASE_URL` 환경변수로 넘겨 GCP 배포 갱신:
   ```bash
   OLLAMA_BASE_URL="https://xxxx.trycloudflare.com" ./scripts/deploy-gcp.sh
   ```

### [방법 B] SSH 포트 포워딩 방식 (`colab ssh`)
터널 없이 안전하게 로컬 또는 서버에서 직통 포트 포워딩을 유지하려면:
```bash
./scripts/run_colab_llm.sh --port-forward
# 로컬의 http://localhost:11434 로 Colab의 Ollama가 연결됨
```

---

## 4. 리소스 및 운영 팁
- **동적 모델 스와핑**: Colab T4 GPU(15GB VRAM) 상의 Ollama 데몬에 `gemma3:12b`와 `hermes3:8b`가 함께 적재되어, 요청된 모델에 따라 자동으로 VRAM 스와핑 처리되므로 OOM 없이 안정적으로 동작합니다.
- **세션 종료**: 사용이 끝나면 터미널에서 `colab stop` 또는 `colab list`로 세션을 조회하고 종료할 수 있습니다.


---

## 5. Makefile 단축 명령어

프로젝트 루트의 `Makefile`을 통해 간편하게 실행할 수 있습니다:

```bash
make help          # 전체 사용 가능한 명령어 목록 확인
make colab-login   # Google Colab CLI 계정 인증
make colab-llm     # Colab T4 GPU 세션 생성 및 Ollama 기동 (터널 생성)
make colab-dry     # 명령어 템플릿 dry-run 확인
make colab-ssh     # SSH 포트포워딩 (11434 바인딩)
make deploy        # GCP marine-edge-pc 실서버 배포
make bot-logs      # GCP 텔레그램 봇 실시간 로그 확인
make test          # 전체 단위/통합 테스트 실행
```
