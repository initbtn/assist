# Change-flow 어댑터 — assist

대상 repo(`initbtn/assist`)의 `change-flow` 스킬이 돌 때 읽는 프로젝트 파라미터. 흐름·규율은 `~/projects/domstack/skills/change-flow/SKILL.md`, 여기엔 `assist` 특화 mechanic 만 기술한다.

## 파라미터

| 키 | assist 값 |
|---|---|
| **issue(◦)** | issue-first: **버그·규율 결함 = 필수**(수정 前 선등록), 그 외 선택(1인 repo). PR `closes #N` |
| **마일스톤(◦)** | **없음** |
| **프로젝트(◦)** | **없음** (`gh` 토큰에 `project` 스코프 미부여로 비활성화) |
| **착수 표시(◦)** | **켠다** (assignee 를 「지금 이 이슈를 하고 있다」 표시로 사용) |
| **worktree(①)** | 수동 `git worktree add .claude/worktrees/<name>/ -b <name> origin/main` |
| **토큰(⓪⑤⑥⑧)** | `GH_TOKEN="$(pass show github/gh-token)"` 또는 `gh` 래퍼 |
| **verify(③)** | **앱 코드 변경 → `.venv/bin/pytest -q`** (TDD: 실패하는 테스트 선행 후 구현). **docs·어댑터 변경 → 마크다운 링크·경로 실재 확인** |
| **ADR(②)** | 자리 = `docs/architecture-decision-record/`. 상태 필드 = `- **상태**: <값>` |
| **리뷰 차원(⑦)** | 사실검증(파일·라인·스키마 실재) · 테스트 커버리지 및 격리성 · 시크릿 노출 여부(`secret-hygiene`) · 표준 대조(commit prefix·한국어·squash) · plan-match |
| **커밋(④)** | 한국어, prefix `feat:`/`docs:`/`fix:`/`chore:`, forward-only |
| **PR(⑥)** | 템플릿 [.github/PULL_REQUEST_TEMPLATE.md](./.github/PULL_REQUEST_TEMPLATE.md), `closes #N` |
| **merge 모델(⑧)** | **squash-only** (`--squash --delete-branch`, 단독 owner, 사용자 명시 위임 시만) |
| **cleanup(⑨)** | `git worktree remove` + 로컬 브랜치 `-D` (`~/projects/domstack/docs/worktree-cleanup.md` 정본 준수) |
| **배포(⑩)** | GCP `marine-edge-pc`(`us-central1-a`, `8001` 포트) 경량 컨테이너 배포 (`./scripts/deploy-gcp.sh`, `deploy-run` 게이트 준수) |
| **warming** | pass·gpg (`DOMSTACK_WARMING` on) |
| **Python 구조(②)** | 모듈 하나는 하나의 책임만 진다 — 수집·변환·저장·전송을 한 함수에 섞지 않는다(SRP). 설정·주소·키는 `Settings` 같은 한 곳에서 읽고, 호출부는 인자로 받는다(DIP). I/O(HTTP·DB·LLM) 호출은 얇은 함수로 분리해 테스트에서 대체하고 실호출을 하지 않는다. 공개 함수는 쓰는 인자만 받는다(ISP) |
| **하드코딩·상수(②)** | 매직 넘버·색·URL·키·문구를 코드에 흩뿌려 박지 않는다. 같은 값이 둘 이상의 자리에 쓰이면 한 곳(상수·토큰·설정)에서 정의해 참조한다. 환경마다 다른 값은 설정·env 로 받고 시크릿은 코드에 두지 않는다 |
