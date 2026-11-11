# assist — Personal Dev Trend RAG Assistant & Local SLM Lifecycle Platform

`assist`는 최신 엔터프라이즈 개발 동향 및 논문/릴리스 정보를 자율 수집하여 벡터 검색(RAG)과 온디맨드 로컬 경량 언어 모델(sLM)을 통해 브리핑, 기사 합성, 아키텍처 리뷰를 제공하는 인텔리전스 백엔드 플랫폼입니다.

---

## 🏛 시스템 아키텍처

```mermaid
flowchart TD
    subgraph Clients["Clients / Consumers"]
        Telegram["Telegram Bot (@DomAssistBot)"]
        AdminConsole["B2B Admin Console (Web)"]
        Blog["domlog (Tech Blog)"]
    end

    subgraph WAS["WAS API Gateway (FastAPI)"]
        Router["API Router (/v1)"]
        Deps["Auth & RateLimiter (Stateless JWT / pass)"]
        Lifespan["FastAPI Lifespan (Idle Watcher Daemon)"]
        RAG["Contextual Retrieval & Chunking"]
    end

    subgraph Storage["Persistence & Compute"]
        Supabase[("Supabase PGVector + DB")]
        Firestore[("Cloud Firestore (Articles/Chat)")]
        ColabGPU["Google Colab T4 GPU (Ollama)"]
    end

    Telegram <-->|Long-polling / Webhook| WAS
    AdminConsole <-->|REST API (Bearer JWT)| WAS
    WAS -->|REST Post| Blog

    WAS <-->|Vector Search & Deduplication| Supabase
    WAS <-->|Briefing Persistence| Firestore
    WAS <-->|JIT Auto-Wakeup / Scale-to-Zero| ColabGPU
```

---

## 🔒 아키텍처 결정 기록 (Architecture Decision Records)

프로젝트의 핵심 설계 원칙과 결정 사항은 ADR 정본 문서를 통해 엄격히 통제됩니다:

| ADR | 제목 | 상태 | 핵심 요약 |
|---|---|---|---|
| [**0001**](docs/architecture-decision-record/0001-was-gateway-and-storage-security.md) | WAS 단일 API 게이트웨이 및 스토리지 보안 | `Accepted` | 브라우저/클라이언트의 DB(Supabase) 및 스토리지 직접 접근 원천 금지, 모든 I/O는 WAS 경유 |
| [**0002**](docs/architecture-decision-record/0002-b2b-api-console-and-token-rotation.md) | B2B API 콘솔 및 토큰 로테이션 | `Accepted` | 무상태 Firebase ID Token & B2B App별 API 키/리프레시 토큰 발급 및 수명주기 관리 |
| [**0003**](docs/architecture-decision-record/0003-gcp-secret-manager-node-credentials.md) | GCP Secret Manager 노드 자격증명 주입 | `Accepted` | 인프라 배포 시 pass 및 GCP Secret Manager를 통한 런타임 단기 메모리 시크릿 주입 |
| [**0004**](docs/architecture-decision-record/0004-non-chinese-slm-dual-model-evaluation.md) | 비중국권 경량 SLM 듀얼 모델 선정 및 A/B 평가 | `Accepted` | 비중국권 투명성 원칙(Gemma 3:12b vs Hermes 3:8b), Arctic Embed v2, 병행 비교 엔드포인트 운용 |

---

## 🧠 핵심 모델 및 RAG 스택

- **임베딩 모델**: `Snowflake/snowflake-arctic-embed-l-v2.0` (768 차원 벡터, Snowflake 엔터프라이즈)
- **로컬 생성 SLM (듀얼 체계)**:
  - **Model A (주력)**: `gemma3:12b` (Google DeepMind)
  - **Model C (비교/평가)**: `hermes3:8b` (Nous Research / Meta Llama 3 Fine-tuned)
  - *비중국권 모델 선정 원칙*: 중국계 모델(Qwen, DeepSeek 등)은 데이터 프라이버시 및 보안 공급망 규율에 따라 배제됩니다.
- **RAG 파이프라인**: Contextual Retrieval 1줄 맥락 헤더 주입(`[도메인: ... | 주제: ... | 제목: ...]`), 청크 메타데이터 보존(`category`, `priority`, `chunk_count`).

---

## 🚀 빠른 시작

### 1. 환경 설정 및 의존성 설치
```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. 로컬 테스트 실행
```bash
.venv/bin/pytest -q
```

### 3. 실서버 배포 (GCP VM)
```bash
ENABLE_INBOUND_8001=preserve ./scripts/deploy-gcp.sh
```
