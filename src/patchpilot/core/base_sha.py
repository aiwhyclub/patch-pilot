# 난이도: Mid
# 학습 키워드: SHA-256, Fail Closed, Git
"""base_sha 계약 판정. git을 실행하지 않고 주입된 관찰값만 본다.

시작 시점의 1차 SHA와 PR 전 base_sha_check의 2차 SHA는 trusted supervisor의
읽기 전용 adapter 몫이다. 그 adapter는 이 빌드에 연결되어 있지 않다.
고객 hook과 git -c 설정 주입을 피하려고 명령 문자열을 만들지도 실행하지도 않는다.
"""

from __future__ import annotations

import re

from patchpilot.schema.codes import E_RUNTIME_NOT_READY, H_BASE_MOVED


_SHA = re.compile(r"^[0-9a-fA-F]{40}$|^[0-9a-fA-F]{64}$")
_STATUSES = ("acquired", "not_attempted", "rejected", "failed")
_NEEDS_ACQUIRED = ("draft_pr_opened", "patch_only", "pr_gate_blocked")
_NEEDS_SECOND_CHECK = ("draft_pr_opened", "patch_only")


def readonly_adapter_connected() -> bool:
    """고객 repo SHA adapter가 연결되어 있으면 True다. 이 빌드에서는 False다."""
    return False


def adapter_block_cause() -> dict:
    """SHA adapter가 왜 연결되어 있지 않은지 돌려준다. git은 실행하지 않는다."""
    return {
        "connected": False,
        "network": False,
        "invokes_git": False,
        "reason_code": E_RUNTIME_NOT_READY,
        "cause": "readonly base SHA adapter is not connected; customer repo, credentials, and hook policy are unset",
    }


def observe_injected(payload: dict | None) -> dict:
    """호출자가 넣은 관찰값만 계약 상태로 바꾼다. payload를 명령으로 해석하지 않는다."""
    if payload is None:
        return {"status": "not_attempted", "reason_code": None, "base_sha": None}
    status = payload.get("status")
    if status == "acquired" and _sha_text(payload.get("base_sha")):
        return {"status": "acquired", "reason_code": None, "base_sha": payload["base_sha"]}
    if status in ("rejected", "failed", "not_attempted"):
        reason = payload.get("reason_code")
        return {"status": status, "reason_code": reason if isinstance(reason, str) else None, "base_sha": None}
    return {"status": "failed", "reason_code": None, "base_sha": None}


def mismatch_reason(first: dict, second: dict) -> str | None:
    """두 관찰이 모두 acquired인데 값이 다르면 H_BASE_MOVED를 돌려준다.

    None은 성공이 아니다. 한쪽이라도 없으면 이동을 주장하지 않을 뿐이며,
    최종 성공 여부는 success_sha_ok가 따로 본다.
    """
    if first.get("status") == "acquired" and second.get("status") == "acquired":
        if first.get("base_sha") != second.get("base_sha"):
            return H_BASE_MOVED
    return None


def success_sha_ok(first: dict, second: dict) -> bool:
    """1차와 2차가 같은 비어 있지 않은 SHA로 acquired일 때만 True다."""
    if first.get("status") != "acquired" or second.get("status") != "acquired":
        return False
    sha = first.get("base_sha")
    return _sha_text(sha) and sha == second.get("base_sha")


def acquisition_problems(manifest: dict) -> list[str]:
    """manifest의 base_sha 획득 상태가 계약과 어긋나면 이유 문자열을 모은다."""
    acquisition = manifest.get("acquisition")
    inputs = manifest.get("inputs")
    if not isinstance(acquisition, dict) or not isinstance(inputs, dict):
        return ["base_sha"]
    item = acquisition.get("base_sha")
    if not isinstance(item, dict) or item.get("status") not in _STATUSES:
        return ["base_sha status"]
    status = item.get("status")
    sha = inputs.get("base_sha")
    outcome = manifest.get("outcome")
    if status != "acquired":
        if sha is not None:
            return ["base_sha null"]
        if outcome in _NEEDS_ACQUIRED:
            return ["base_sha success"]
        return []
    if not _sha_text(sha):
        return ["base_sha value"]
    if outcome in _NEEDS_SECOND_CHECK:
        stage = _stage(manifest, "base_sha_check")
        attempts = None if stage is None else stage.get("attempts")
        if (
            stage is None
            or stage.get("status") != "passed"
            or not isinstance(attempts, int)
            or not 1 <= attempts <= 2
            or not stage.get("started_at")
            or not stage.get("ended_at")
        ):
            return ["base_sha check"]
        lock_sha = (manifest.get("tests") or {}).get("lock_base_sha")
        if lock_sha != sha:
            return ["lock_base_sha"]
    return []


def _sha_text(value) -> bool:
    """git 객체 id 모양의 한 줄만 SHA로 받는다. 명령 조각은 거부한다."""
    return isinstance(value, str) and _SHA.fullmatch(value) is not None


def _stage(manifest: dict, name: str) -> dict | None:
    """고정 stage 목록에서 이름이 같은 항목을 찾는다."""
    for stage in manifest.get("stages") or []:
        if isinstance(stage, dict) and stage.get("name") == name:
            return stage
    return None
