# 난이도: Easy
# 학습 키워드: Fail Closed, Sandbox, cgroup
"""고객 코드 실행 가능 여부. 이 빌드에서는 항상 차단이다."""

from __future__ import annotations

from patchpilot.core.capability import (
    CONTAINER_ISOLATION_PROVEN,
    CUSTOMER_EXECUTION_APPROVED,
    RESOURCE_ENFORCEMENT_PROVEN,
)


def execution_block_reason() -> str:
    """컨테이너·cgroup·승인이 하나라도 없으면 BLOCKED를 돌려준다."""
    if CONTAINER_ISOLATION_PROVEN and RESOURCE_ENFORCEMENT_PROVEN and CUSTOMER_EXECUTION_APPROVED:
        return ""
    return "BLOCKED"


def run_customer_worker(*_args, **_kwargs):
    """고객 프로세스를 만들지 않고 즉시 예외를 낸다. 테스트에서 호출하지 않는다."""
    raise RuntimeError("BLOCKED: customer worker is not approved and was not started")
