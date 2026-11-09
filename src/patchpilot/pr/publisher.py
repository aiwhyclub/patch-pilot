# 난이도: Easy
# 학습 키워드: Fail Closed, Pull Request, Draft
"""고객 draft PR publisher. 네트워크를 열지 않고 즉시 차단한다."""

from __future__ import annotations

from patchpilot.core.capability import CUSTOMER_PR_APPROVED
from patchpilot.schema.codes import E_RUNTIME_NOT_READY


_GATES = (
    "ledger_durable",
    "approval_verified",
    "evidence_gate_passed",
    "sha_checked_twice",
    "customer_pr_approved",
    "provider_binding_ok",
)


def publisher_decision(gates: dict | None = None) -> dict:
    """게이트가 모두 참처럼 보여도 이 빌드에서는 원격 호출과 성공 기록을 하지 않는다."""
    supplied = gates or {}
    missing = [name for name in _GATES if supplied.get(name) is not True]
    if CUSTOMER_PR_APPROVED is not True:
        missing.append("customer_pr_approved_constant")
    return {
        "call": False,
        "network": False,
        "existence": "not_attempted",
        "recorded_success": False,
        "url": None,
        "reason_code": E_RUNTIME_NOT_READY,
        "missing": missing,
    }


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
