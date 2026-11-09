# 난이도: Easy
# 학습 키워드: Fail Closed, Capability Gate, Feature Flag
"""아직 증명되지 않은 실행 능력. 환경변수로 우회할 수 없게 상수로 고정한다."""

from __future__ import annotations

# 별도 승인과 강제 입증 전에는 모두 False다.
CUSTOMER_EXECUTION_APPROVED = False
MODEL_ENDPOINT_APPROVED = False
CUSTOMER_PR_APPROVED = False
RESOURCE_ENFORCEMENT_PROVEN = False
LEDGER_DURABILITY_PROVEN = False
CONTAINER_ISOLATION_PROVEN = False


def capabilities_proven() -> bool:
    """고객 실행, 모델, PR, 자원 강제, ledger 내구성이 모두 증명됐는지 확인한다."""
    return all(
        (
            CUSTOMER_EXECUTION_APPROVED,
            MODEL_ENDPOINT_APPROVED,
            CUSTOMER_PR_APPROVED,
            RESOURCE_ENFORCEMENT_PROVEN,
            LEDGER_DURABILITY_PROVEN,
            CONTAINER_ISOLATION_PROVEN,
        )
    )


def full_success_allowed(flags: dict) -> bool:
    """계약 성공 조건과 미증명 능력이 모두 참일 때만 True를 돌려준다."""
    required = (
        "acquisition_complete",
        "evidence_gate_passed",
        "supported_change",
        "patch_validated",
        "locks_match",
        "sequence_pass_fail_pass",
        "approval_verified",
        "sha_checked_twice",
        "pr_lookup_matches",
        "secrets_clear",
        "customer_equals_target",
        "customer_execution_approved",
        "model_endpoint_approved",
        "customer_pr_approved",
        "resource_enforcement_proven",
        "ledger_durability_proven",
        "container_isolation_proven",
    )
    return all(flags.get(name) is True for name in required)


def enforce_unproven_block(outcome: str) -> str:
    """능력이 미증명이면 draft_pr_opened와 patch_only를 error로 내린다."""
    if outcome in ("draft_pr_opened", "patch_only") and not capabilities_proven():
        return "error"
    return outcome
