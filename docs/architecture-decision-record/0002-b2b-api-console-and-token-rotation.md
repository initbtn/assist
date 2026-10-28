# 0002. B2B Cloud Console 및 앱별 API 토큰·리프레시·화이트리스트 인가 아키텍처

- **상태**: 승인됨 (Accepted)
- **날짜**: 2026-10-29

## 맥락 (Context)

`assist` 시스템을 B2B 외부 고객 및 서드파티 클라이언트에 API 서비스로 판매 및 제공할 수 있는 기반이 필요합니다.
이를 위해 Cloud Service Console(예: OpenAI, Supabase, Anthropic)과 같은 대시보드를 구축하여 앱별 API 토큰을 발급하고, 토큰의 유효 기간(TTL) 및 리프레시(Rotation) 메커니즘을 지원해야 합니다.
동시에 [ADR 0001](0001-was-gateway-and-storage-security.md)에 명시된 원칙(WAS가 유일한 공개 API 게이트웨이이며 브라우저가 DB/스토리지에 직접 접근하지 않음)을 엄격히 준수하고, 텔레그램 봇을 통한 무단 온디맨드 Colab T4 GPU 기동을 차단하는 인가 체계가 필요합니다.

## 결정 (Decision)

### 1. WAS 게이트웨이 기반 데이터 모델 (Supabase PostgreSQL)
브라우저는 Supabase에 직접 접근하지 않고 WAS 백엔드(`assist-api`)를 통해서만 데이터를 조작합니다.
- `apps`: B2B 테넌트의 등록 애플리케이션 (`id`, `name`, `description`, `is_active`, `created_at`)
- `api_tokens`:
  - `id`: UUID (PK)
  - `app_id`: UUID (FK -> `apps.id`)
  - `name`: 토큰 식별 이름
  - `key_prefix`: 식별용 접두사 (`ast_live_` + 앞 8자리, 대시보드 표시용)
  - `key_hash`: SHA-256 해시값 (평문 키는 생성 시 1회만 클라이언트에 반환되며 DB에는 해시만 저장)
  - `refresh_token_hash`: SHA-256 해시값 (토큰 로테이션용 리프레시 토큰)
  - `expires_at`: 만료 일시 (TTL 기반 타임스탬프)
  - `last_used_at`: 최근 API 호출 일시
  - `revoked_at`: 토큰 폐기 일시
  - `is_active`: 활성화 여부
- `bot_configs`:
  - `app_id`: UUID (FK -> `apps.id`)
  - `allowed_chat_ids`: `TEXT[]` (허용된 텔레그램 Chat ID 목록)
  - `enable_colab_gpu`: 온디맨드 Colab T4 부팅 허용 여부 (`true`/`false`)
  - `rate_limit_rpm`: 분당 요청 한도

### 2. B2B API 토큰 발급, 검증 및 Refresh Rotation
- **토큰 포맷**:
  - Access Token: `ast_live_<32바이트_urlsafe_랜덤>`
  - Refresh Token: `ast_ref_<32바이트_urlsafe_랜덤>`
- **API 인증 미들웨어**:
  - `assist-api` 호출 시 `Authorization: Bearer ast_live_...` 또는 `X-API-Key: ast_live_...` 헤더를 수신.
  - SHA-256 해시를 계산하여 활성 상태(`is_active=True`, `revoked_at is NULL`) 및 만료 여부(`expires_at >= now()`)를 검증.
- **Refresh & Key Rotation (`POST /v1/auth/tokens/refresh`)**:
  - 리프레시 토큰을 제출하면, 기존 토큰을 폐기(`revoked_at = now()`)하고 동일한 설정(앱 및 이름)으로 새로운 Access Token과 Refresh Token 쌍을 발급.

### 3. 텔레그램 인가 화이트리스트 및 GPU 가드
- `app/telegram.py` 및 `scripts/run_telegram_polling.py`는 수신된 메시지의 `chat_id`를 화이트리스트(`bot_configs.allowed_chat_ids` 및 환경변수 `TELEGRAM_ALLOWED_CHAT_IDS`)와 대조.
- 미인가 사용자의 요청인 경우 Colab 온디맨드 부팅(`provisioner.trigger_background_provision()`)을 절대 트리거하지 않으며, 미인가 안내 메시지를 반환하거나 무시.

### 4. Vercel Web Console (`web/admin/`)
- Cloud Service Console 인터페이스 제공:
  - App 등록 및 관리
  - API Key 발급 모달 (TTL 선택: 30일/90일/1년/무제한, 생성 직후 1회 복사)
  - Key 상태(Active / Expired / Revoked) 시각화 및 Rotate/Revoke 액션
  - 텔레그램 Chat ID 화이트리스트 및 Colab GPU 기동 토글 설정

## 근거 및 트레이드오프

### 이점
- **B2B 확장성**: 앱별 독립적인 API 키와 쿼터, 만료 주기를 제공하여 B2B 유료화 및 파트너십 연동 지원.
- **보안성(Zero Plaintext in DB)**: DB 유출 시에도 SHA-256 해시만 노출되므로 원본 키 탈취 불가. Refresh 토큰 로테이션으로 장기 토큰의 탈취 리스크 완화.
- **ADR 0001 준수**: 브라우저에 DB 자격증명을 노출하지 않고 WAS 게이트웨이를 통해서만 안전하게 동작.
- **Colab GPU 비용 통제**: 인가되지 않은 외부 사용자의 무단 Colab T4 기동을 완벽히 차단.
