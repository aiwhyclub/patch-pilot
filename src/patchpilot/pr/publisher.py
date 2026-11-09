# 난이도: Easy
# 학습 키워드: Fail Closed, Pull Request, Draft
"""고객 draft PR publisher. 네트워크를 열지 않고 즉시 차단한다."""

from __future__ import annotations


def publish_draft_pr(**_kwargs) -> dict:
    """원격 PR을 만들지 않고 not_attempted 차단 결과만 돌려준다. 테스트에서 호출하지 않는다."""
    return {
        "blocked": True,
        "network": False,
        "existence": "not_attempted",
        "url": None,
        "reason_code": None,
        "detail": "customer PR publisher is fail-closed; no remote call",
    }
