# 난이도: Mid
# 학습 키워드: Fail Closed, Adapter, Consent
"""모델 전송 결정과 명백한 가짜 adapter. 네트워크 호출은 없다."""

from __future__ import annotations

from patchpilot.core.capability import MODEL_ENDPOINT_APPROVED
from patchpilot.schema.codes import H_MODEL_SEND_BLOCKED
from patchpilot.schema.redact import contains_secret


def model_send_decision(*, consent: bool, excerpt: str | None, endpoint_approved: bool | None = None) -> str | None:
    """전송할 수 있으면 None, 동의·불확실·비밀이 있으면 H_MODEL_SEND_BLOCKED를 돌려준다."""
    approved = MODEL_ENDPOINT_APPROVED if endpoint_approved is None else endpoint_approved
    if approved is not True or consent is not True or not isinstance(excerpt, str) or excerpt == "":
        return H_MODEL_SEND_BLOCKED
    if contains_secret(excerpt):
        return H_MODEL_SEND_BLOCKED
    return None


def accept_model_result(result: dict | None, *, endpoint_approved: bool) -> bool:
    """실제 provider 표시와 승인된 endpoint가 아니면 diff를 받지 않는다."""
    if endpoint_approved is not True or not isinstance(result, dict):
        return False
    if result.get("fake") is True or result.get("is_real_provider") is not True:
        return False
    diff = result.get("diff")
    return isinstance(diff, str) and diff != "" and not contains_secret(diff)


class ObviousFakeModel:
    """테스트용 가짜. 규칙으로 키를 바꾸지 않고 diff도 만들지 않는다."""

    is_real_provider = False
    name = "obvious-fake-not-a-provider"

    def propose_diff(self, excerpt: str) -> dict:
        """네트워크 없이 가짜 차단 결과만 돌려준다."""
        return {
            "fake": True,
            "is_real_provider": False,
            "diff": None,
            "blocked": True,
            "reason_code": H_MODEL_SEND_BLOCKED,
            "excerpt_ignored": True,
        }


def send_to_provider(excerpt: str, consent: bool) -> dict:
    """승인된 endpoint가 없으면 소켓을 열지 않고 차단 결과를 돌려준다."""
    reason = model_send_decision(consent=consent, excerpt=excerpt)
    return {
        "network": False,
        "sent": False,
        "diff": None,
        "reason_code": reason or H_MODEL_SEND_BLOCKED,
    }
