# 난이도: Mid
# 학습 키워드: Idempotency, SHA-256, Approval Binding
"""PR 조회 결과와 승인 binding을 순수 함수로 비교한다. 원격 조회는 하지 않는다."""

from __future__ import annotations

import hashlib

from patchpilot.schema.codes import (
    B_BINDING_MISMATCH,
    B_EVIDENCE_GATE,
    B_NO_APPROVAL,
    E_PR_CREATE_FAILED,
    E_PR_RESULT_UNKNOWN,
    H_REUSED_PR_MISMATCH,
)


def idem_key(customer_repo: str, pr_repo: str, base_branch: str, base_sha: str, spec_new_sha256: str, diff_sha256: str) -> str:
    """여섯 값을 NUL로 구분해 sha256한 idem_key를 만든다."""
    parts = [customer_repo, pr_repo, base_branch, base_sha, spec_new_sha256, diff_sha256]
    blob = b"\0".join(part.encode("utf-8") for part in parts)
    return hashlib.sha256(blob).hexdigest()


def approval_decision(*, open_pr: bool, binding: dict | None, target: dict) -> str | None:
    """PR을 열 필요가 없으면 None, 승인 문제가 있으면 B_ 코드를 돌려준다."""
    if not open_pr:
        return None
    if not isinstance(binding, dict):
        return B_NO_APPROVAL
    expected = {
        "repo": target.get("repo"),
        "base_branch": target.get("base_branch"),
        "base_sha": target.get("base_sha"),
        "diff_sha256": target.get("diff_sha256"),
        "operation": "open_draft_pr",
    }
    for key, value in expected.items():
        if value is None or binding.get(key) != value:
            return B_BINDING_MISMATCH
    return None


def evidence_gate_decision(*, hashes_match: bool, sequence_ok: bool) -> str | None:
    """재해시와 검증 순서가 모두 맞을 때만 None, 아니면 B_EVIDENCE_GATE를 돌려준다."""
    if hashes_match is True and sequence_ok is True:
        return None
    return B_EVIDENCE_GATE


def pr_match(remote: dict, expected: dict) -> str | None:
    """원격 조회로 받은 dict가 기대와 같으면 None, 아니면 계약 reason을 돌려준다."""
    existence = remote.get("existence")
    if existence == "unknown":
        return E_PR_RESULT_UNKNOWN
    if existence == "absent":
        return E_PR_CREATE_FAILED
    if existence != "exists":
        return E_PR_RESULT_UNKNOWN
    checks = (
        remote.get("repo") == expected.get("repo"),
        remote.get("base_branch") == expected.get("base_branch"),
        remote.get("base_sha") == expected.get("base_sha"),
        remote.get("head_diff_sha256") == expected.get("diff_sha256"),
        remote.get("draft") is True,
        remote.get("merged") is False,
        remote.get("approval_ref") == expected.get("approval_ref"),
    )
    if not all(checks):
        return H_REUSED_PR_MISMATCH
    return None


def may_auto_reissue(_existence: str) -> bool:
    """어떤 조회 결과에서도 자동 재발행을 허용하지 않는다."""
    return False
