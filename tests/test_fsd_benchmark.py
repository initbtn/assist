import pytest
from benchmarks.fsd_review_benchmark import (
    BAD_FSD_DIFF,
    GOOD_FSD_DIFF,
    build_fsd_review_prompt,
    run_fsd_benchmark,
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


def test_score_fsd_review_fallback_with_negative_words():
    # Test case where model doesn't output format, but says "위반 없음"
    review_output = "검토 결과 상위 레이어 역참조 위반 없음. 슬롯을 올바르게 사용하고 있어 문제 없음."
    result = score_fsd_review(review_output, is_bad_diff=False)
    assert result["pass"] is True
    assert result["violation_detected"] is False


def test_run_fsd_benchmark_boundary_contract():
    def mock_evaluator(prompt: str) -> str:
        # Prompt contains full diff at the bottom: check [검토할 Diff]: section
        diff_section = prompt.split("[검토할 Diff]:")[-1]
        if "features/edit-profile" in diff_section:
            return "- 판정: VIOLATION_DETECTED\n- 결함 원인: entities 계층에서 features 계층 역참조 발생."
        return "- 판정: PASS\n- 결함 원인: 없음. 정상적인 props 슬롯 패턴 준수."

    # Verify boundary contract function
    res = run_fsd_benchmark(mock_evaluator)
    assert res["success"] is True
    assert res["detection_rate"] == 1.0
    assert len(res["detected_violations"]) == 1
    assert "entities layer directly imports upper features layer" in res["detected_violations"][0]


def test_build_fsd_review_prompt_includes_rules():
    prompt = build_fsd_review_prompt("test diff")
    assert "app" in prompt and "features" in prompt and "entities" in prompt
    assert "test diff" in prompt
