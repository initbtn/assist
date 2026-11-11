import logging
import os
import re
from typing import Any, Callable

logger = logging.getLogger(__name__)

# 1. FSD Mock Diffs for Benchmarking
BAD_FSD_DIFF = """
diff --git a/entities/user/ui/UserProfileCard.tsx b/entities/user/ui/UserProfileCard.tsx
new file mode 100644
--- /dev/null
+++ b/entities/user/ui/UserProfileCard.tsx
@@ -0,0 +1,18 @@
+// entities layer importing upper features layer directly
+import React from 'react';
+import { EditProfileModal } from '@/features/edit-profile/ui/EditProfileModal';
+import { User } from '../model/types';

interface Props {
  user: User;
}

export function UserProfileCard({ user }: Props) {
  return (
    <div className="card">
      <h3>{user.name}</h3>
      <p>{user.email}</p>
      <EditProfileModal userId={user.id} />
    </div>
  );
}
"""

GOOD_FSD_DIFF = """
diff --git a/entities/user/ui/UserProfileCard.tsx b/entities/user/ui/UserProfileCard.tsx
new file mode 100644
--- /dev/null
+++ b/entities/user/ui/UserProfileCard.tsx
@@ -0,0 +1,18 @@
+// entities layer using slot props to maintain downward dependency
+import React, { ReactNode } from 'react';
+import { User } from '../model/types';

interface Props {
  user: User;
  actionSlot?: ReactNode;
}

export function UserProfileCard({ user, actionSlot }: Props) {
  return (
    <div className="card">
      <h3>{user.name}</h3>
      <p>{user.email}</p>
      {actionSlot && <div className="card-actions">{actionSlot}</div>}
    </div>
  );
}
"""


def load_fsd_rules() -> str:
    current_dir = os.path.dirname(__file__)
    candidate_paths = [
        os.path.join(current_dir, "..", "patterns", "frontend", "fsd-layer-rules.md"),
        os.path.join(current_dir, "patterns", "frontend", "fsd-layer-rules.md"),
    ]
    for p in candidate_paths:
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                return f.read()

    return """[FSD 아키텍처 단방향 의존성 규칙]
1. 계층 구조: app -> pages -> widgets -> features -> entities -> shared
2. 하위 레이어(entities, shared)는 상위 레이어(features, widgets, pages)를 직접 import할 수 없습니다.
3. 동일 계층 내 Cross-Slice 직접 참조를 금지하며 슬롯(actionSlot) 또는 상위 위젯에서 합성해야 합니다."""


def build_fsd_review_prompt(diff: str) -> str:
    rules = load_fsd_rules()
    return f"""당신은 엔터프라이즈 프론트엔드 아키텍처(Feature-Sliced Design, FSD) 코드 리뷰어입니다.
아래의 FSD 아키텍처 규칙과 주어진 git diff를 엄격히 검토하여 아키텍처 결함(Code Smells)을 판정하세요.

{rules}

[검토할 Diff]:
{diff}

[응답 형식]:
- 판정: [VIOLATION_DETECTED | PASS]
- 결함 원인: (규칙 위반 세부 설명)
- 권장 처방: (해결 방안)
"""


def score_fsd_review(review_text: str, is_bad_diff: bool) -> dict[str, Any]:
    cleaned = review_text.strip()

    # 1. Check explicit judgment tokens
    explicit_violation = bool(
        re.search(r"판정:\s*VIOLATION_DETECTED", cleaned, re.IGNORECASE)
    )
    explicit_pass = bool(re.search(r"판정:\s*PASS", cleaned, re.IGNORECASE))

    if explicit_violation and not explicit_pass:
        is_violation = True
    elif explicit_pass and not explicit_violation:
        is_violation = False
    else:
        # Fallback keyword matching with negative guard (e.g. "위반 없음", "결함 없음")
        has_negative = bool(
            re.search(
                r"(위반\s*없음|결함\s*없음|문제\s*없음|역참조\s*없음|정상|준수)",
                cleaned,
                re.IGNORECASE,
            )
        )
        has_violation_keyword = bool(
            re.search(r"(위반|상위 레이어|역참조)", cleaned, re.IGNORECASE)
        )
        if has_negative:
            is_violation = False
        else:
            is_violation = has_violation_keyword

    passed = is_violation if is_bad_diff else not is_violation

    keywords_found = []
    for kw in ["entities", "features", "import", "슬롯", "단방향", "의존성", "slot"]:
        if kw.lower() in cleaned.lower():
            keywords_found.append(kw)

    return {
        "pass": passed,
        "violation_detected": is_violation,
        "keywords_found": keywords_found,
        "review_summary": cleaned[:200],
    }


def run_single_fsd_benchmark(
    diff: str,
    is_bad_diff: bool,
    evaluator: Callable[[str], str],
) -> dict[str, Any]:
    prompt = build_fsd_review_prompt(diff)
    review_output = evaluator(prompt)
    score = score_fsd_review(review_output, is_bad_diff=is_bad_diff)
    return {
        **score,
        "full_review": review_output,
    }


def run_fsd_benchmark(
    evaluator: Callable[[str], str],
) -> dict[str, Any]:
    """Boundary contract function matching DoD:

    run_fsd_benchmark(llm_evaluator) -> dict[str, Any]
    """
    bad_result = run_single_fsd_benchmark(BAD_FSD_DIFF, is_bad_diff=True, evaluator=evaluator)
    good_result = run_single_fsd_benchmark(GOOD_FSD_DIFF, is_bad_diff=False, evaluator=evaluator)

    detected_violations: list[str] = []
    if bad_result["violation_detected"]:
        detected_violations.append("entities layer directly imports upper features layer")
    if good_result["violation_detected"]:
        detected_violations.append("false positive violation detected in good diff")

    passed_count = (1 if bad_result["pass"] else 0) + (1 if good_result["pass"] else 0)
    detection_rate = passed_count / 2.0
    passed_all = bad_result["pass"] and good_result["pass"]

    # 남길 관측 (ops) logging format
    logger.info(
        "FSD benchmark completed: Model detected %d architectural violations",
        len(detected_violations),
    )

    return {
        "success": passed_all,
        "detection_rate": detection_rate,
        "detected_violations": detected_violations,
        "bad_diff_result": bad_result,
        "good_diff_result": good_result,
    }


# Backwards compatibility alias
run_fsd_benchmark_suite = run_fsd_benchmark
