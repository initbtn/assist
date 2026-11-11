import pytest
from benchmarks.fsd_review_benchmark import (
    BAD_FSD_DIFF,
    GOOD_FSD_DIFF,
    run_fsd_benchmark_suite,
    run_single_fsd_benchmark,
    score_fsd_review,
)


def test_score_fsd_review_bad_diff_detected():
    review_output = """
- 판정: VIOLATION_DETECTED
- 결함 원인: 하위 레이어 entities가 상위 레이어 features를 직접 import하여 단방향 의존성 규칙을 위반함.
- 권장 처방: actionSlot을 통해 상위 컴포넌트를 주입하세요.
"""
    result = score_fsd_review(review_output, is_bad_diff=True)
    assert result["pass"] is True
    assert result["violation_detected"] is True
    assert "entities" in result["keywords_found"]
    assert "features" in result["keywords_found"]


def test_score_fsd_review_good_diff_pass():
    review_output = """
- 판정: PASS
- 결함 원인: 결함 없음. 슬롯(actionSlot)을 통해 단방향 의존성을 올바르게 유지함.
- 권장 처방: 유지 권장.
"""
    result = score_fsd_review(review_output, is_bad_diff=False)
    assert result["pass"] is True
    assert result["violation_detected"] is False
    assert "슬롯" in result["keywords_found"]


def test_run_fsd_benchmark_suite_with_mock_llm():
    def mock_evaluator(prompt: str) -> str:
        if "features/edit-profile" in prompt:
            return "- 판정: VIOLATION_DETECTED\n- 결함 원인: entities 계층에서 features 계층 역참조 발생."
        return "- 판정: PASS\n- 결함 원인: 없음. 정상적인 props 슬롯 패턴 준수."

    suite_result = run_fsd_benchmark_suite(mock_evaluator)
    assert suite_result["success"] is True
    assert suite_result["bad_diff_result"]["pass"] is True
    assert suite_result["good_diff_result"]["pass"] is True
