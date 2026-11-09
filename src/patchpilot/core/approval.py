# 난이도: Mid
# 학습 키워드: Approval, Binding, Fail Closed
"""실행 승인 기록의 모양만 검사한다. provider를 고르거나 네트워크를 열지 않는다."""

from __future__ import annotations

from patchpilot.schema.codes import E_RUNTIME_NOT_READY


_FIELDS = ("provider_identity", "api_identity", "customer_repo", "base_branch", "model_send_consent")


def execution_binding_decision(record: dict | None, *, customer_repo: str, base_branch: str) -> dict:
    """method/path가 없는 기록은 미정이다. 기록이 맞아도 이 빌드에서는 네트워크를 열지 않는다."""
    blocked = {
        "allowed": False,
        "shape_ok": False,
        "network": False,
        "reason_code": E_RUNTIME_NOT_READY,
    }
    if not isinstance(record, dict):
        return {
            **blocked,
            "cause": "execution approval record is unset; method/path is not provider identity or send consent",
        }
    for key in _FIELDS:
        if record.get(key) in (None, ""):
            return {**blocked, "cause": f"{key} is unset"}
    if record.get("customer_repo") != customer_repo or record.get("base_branch") != base_branch:
        return {**blocked, "cause": "customer repo or target branch does not match the approval record"}
    if record.get("model_send_consent") is not True:
        return {**blocked, "cause": "send consent is not true"}
    return {
        "allowed": False,
        "shape_ok": True,
        "network": False,
        "reason_code": E_RUNTIME_NOT_READY,
        "cause": "binding shape matches, but no approved provider endpoint is configured and network stays off",
    }
