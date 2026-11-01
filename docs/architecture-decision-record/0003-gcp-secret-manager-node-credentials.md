# 0003. GCP Secret Manager 및 노드 IAM 기반 백엔드 자격증명 일원화

- **상태**: 승인됨 (Accepted)
- **날짜**: 2026-11-01

## 맥락 (Context)

[ADR 0001]에 따라 assist WAS는 외부 서비스(blog 등)의 유일한 백엔드 게이트웨이 역할을 수행하며, B2B 테넌트 API 인증([ADR 0002]) 및 외부 클라우드(Waffle Firestore) 영속화를 중계합니다.

기존 배포 방식(`scripts/deploy-gcp.sh`)에서는 로컬 `pass`에 저장된 다중 라인 서비스 계정(SA) JSON과 B2B 게이트웨이 토큰을 원격 SSH 파이프를 통해 `/dev/shm`의 `.env` 파일로 직접 전달·주입했습니다. 그러나 이 방식은 다음과 같은 구조적 한계를 가집니다:
1. 배포 머신의 로컬 환경(`pass`, GPG 캐시)에 운영 런타임 자격증명이 강하게 결합됨.
2. 셸 환경변수(`.env`) 파싱 시 멀티라인 JSON 처리 오류 및 줄바꿈 유실 위험 상존.
3. 동일 GCP 인프라 노드 내에서 구동됨에도 불구하고 중앙화된 클라우드 보안 거버넌스(IAM/Secret Manager)를 충분히 활용하지 못함.

이미 PR #45(`assist-colab-credentials`)에서 GCP Secret Manager와 VM 노드 IAM 서비스 계정(`178683488024-compute@developer.gserviceaccount.com`)을 활용하여 노드가 런타임에 직접 메모리로 시크릿을 취득하는 패턴이 검증되어 있습니다.

## 결정 (Decision)

### 1. 단일 통합 시크릿 일원화 (`assist-gateway-credentials`)
GCP Secret Manager(`initbtn-510706`)에 게이트웨이 연동에 필요한 모든 자격증명을 단일 JSON 시크릿(`assist-gateway-credentials`)으로 통합 보관합니다:
```json
{
  "gateway_token": "ast_live_<32바이트_urlsafe>",
  "firestore_sa_key": {
    "type": "service_account",
    "project_id": "waffle-dominic",
    ...
  }
}
```
- **네트워크 최적화**: 애플리케이션 기동 시 Secret Manager API 호출 1회로 토큰과 SA 키를 원자적으로 취득.
- **버전 관리 일원화**: 시크릿 회전(Rotation) 시 단일 시크릿 버전 갱신으로 일관성 보장.

### 2. 노드 IAM 기반 런타임 인메모리 취득
- `marine-edge-pc` VM 인스턴스의 기본 IAM 서비스 계정 권한으로 `SecretManagerServiceClient`를 호출하여 런타임 메모리에만 자격증명을 언패킹.
- 컨테이너 파일시스템 및 `.env` 파일에 민감 자격증명을 영구 저장하거나 노출하지 않음.

### 3. 무상태(Stateless) 배포 파이프라인
- `scripts/deploy-gcp.sh`는 거대한 SA 키나 게이트웨이 토큰을 SSH로 전송하지 않으며, 컨테이너 빌드, 배포 및 헬스체크만 수행.
- 배포 스크립트와 시크릿 라이프사이클의 책임을 엄격히 분리.

### 4. 로컬 개발 및 테스트 격리 (DIP)
- 로컬 개발 환경: Secret Manager 부재 시 기존 환경변수(`GATEWAY_TOKEN`, `FIRESTORE_SA_KEY_JSON`) 및 로컬 `pass`(`assist/gateway-token`, `gcp/waffle-dominic/service-account.json`)로 점진적 폴백.
- 테스트 환경: `InMemoryChatStore` 및 Mock 주입을 통해 GCP API 호출 없이 100% 격리된 단위/통합 테스트 유지.
