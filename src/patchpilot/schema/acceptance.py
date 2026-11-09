# 난이도: Easy
# 학습 키워드: Acceptance Criteria, NOT_RUN
"""PRD PP-AC-001~024 추적표. 제품 관찰 결과는 전부 NOT_RUN이다."""

from __future__ import annotations

AC_IDS = tuple(f"PP-AC-{index:03d}" for index in range(1, 25))
AC_STATUS = {ac_id: "NOT_RUN" for ac_id in AC_IDS}


def all_not_run() -> bool:
    """24개 AC가 모두 NOT_RUN인지 확인한다."""
    return len(AC_STATUS) == 24 and set(AC_STATUS.values()) == {"NOT_RUN"}
