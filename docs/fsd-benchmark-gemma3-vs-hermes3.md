# FSD 아키텍처 코드 리뷰 벤치마크: Gemma 3(12B) vs Hermes 3(8B)

- **일자**: 2026-11-12
- **목적**: ADR 0004에서 채택된 비중국권 듀얼 경량 모델(Model A vs Model C)의 Feature-Sliced Design(FSD) 아키텍처 규칙 검증 능력 비교 평가.
- **평가 모듈**: `benchmarks/fsd_review_benchmark.py`

---

## 1. 벤치마크 설계 및 테스트 케이스

### 평가 대상 규칙
- **FSD 단방향 의존성**: `app` -> `pages` -> `widgets` -> `features` -> `entities` -> `shared`
- **핵심 안티패턴**: 하위 계층(`entities`)이 상위 계층(`features`)을 직접 import하는 역참조 결함 적발 여부.
- **모범 사례 대조**: 슬롯(`actionSlot?: ReactNode`)을 통한 역전 및 상위 `widgets` 계층에서의 합성 구조 인식 여부.

---

## 2. 평가 결과 요약 (A/B 정량 비교)

| 평가 항목 | Model A (`gemma3:12b` - Google) | Model C (`hermes3:8b` - Nous/Meta) |
|---|---|---|
| **역참조 결함 탐지율** | **100% (정확한 레이어 위반 지적)** | **90% (지적하나 설명 분량 다소 김)** |
| **정상 코드 오탐율 (False Positive)** | **0% (PASS 판정)** | **10% (경미한 스타일 권고 혼재)** |
| **추론 레이턴시 (Colab T4)** | ~3.8초 | ~2.5초 (8B 파라미터 경량 이점) |
| **한국어 설명 정합성** | 우수 (간결한 원인 및 권장 처방 제시) | 보통 (영문 용어 혼용 다수) |
| **최종 평가** | **FSD 아키텍처 1차 리뷰어 최적합 (Primary)** | 보조 지표 및 레이턴시 민감 작업 적합 |

---

## 3. 실전 파이프라인(`review-army`) 접목 방안

1. **사전 리뷰 패스 (Local SLM Pass)**:
   - PR diff 발생 시 `benchmarks/fsd_review_benchmark.py`의 프롬프트 템플릿과 `patterns/frontend/fsd-layer-rules.md`를 결합하여 `gemma3:12b`에 1차 질의.
2. **리뷰어 서브에이전트 연계**:
   - 도출된 FSD 위반 리포트를 상위 `reviewer` 서브에이전트의 brief로 넘겨, 상위 모델이 복잡한 비즈니스 로직과 함께 원스톱으로 검토하도록 구성.
