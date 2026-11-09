# 난이도: Difficult
# 학습 키워드: Supervisor, Assertion, Fail Closed
"""고객 테스트를 시작하기 전에 사전조건을 평가한다. 프로세스는 만들지 않는다."""

from __future__ import annotations

from patchpilot.core.capability import (
    CONTAINER_ISOLATION_PROVEN,
    CUSTOMER_EXECUTION_APPROVED,
    RESOURCE_ENFORCEMENT_PROVEN,
)
from patchpilot.runner.worker_result import assert_expected, parse_worker_line
from patchpilot.schema.codes import (
    E_BASELINE_FAIL,
    E_INTERNAL,
    E_NO_REPRO,
    E_PATCH_TEST_FAIL,
    E_RUNTIME_NOT_READY,
    E_TEST_TAMPERED,
)


_READY_FLAGS = (
    ("container_isolation_proven", CONTAINER_ISOLATION_PROVEN, "container isolation is not proven"),
    ("resource_enforcement_proven", RESOURCE_ENFORCEMENT_PROVEN, "cgroup and rlimit enforcement is not proven"),
    ("customer_execution_approved", CUSTOMER_EXECUTION_APPROVED, "customer execution is not approved"),
)


def readiness_from_constants() -> dict:
    """이 빌드의 상수만 본다. 참인 플래그를 주입해도 여기에는 들어오지 않는다."""
    flags = {name: value for name, value, _cause in _READY_FLAGS}
    return decide_dispatch(flags)


def decide_dispatch(flags: dict) -> dict:
    """사전조건이 하나라도 아니면 평가 1회, blocked, not_run을 돌려준다.

    플래그가 모두 참이어도 worker_invoked는 False다. 이 함수는 프로세스를 시작하지 않는다.
    """
    causes = []
    for name, _value, cause in _READY_FLAGS:
        if flags.get(name) is not True:
            causes.append(cause)
    ready = not causes
    return {
        "ready": ready,
        "dispatch": False,
        "worker_invoked": False,
        "recorded_success": False,
        "stage_status": "blocked" if not ready else "skipped",
        "reason_code": E_RUNTIME_NOT_READY if not ready else None,
        "attempts": 1 if not ready else 0,
        "test_result": "not_run",
        "causes": causes,
    }


def classify_worker_fixture(stage: str, expected_values: list, line: str | None, *, lock_same: bool) -> dict:
    """주입된 한 줄과 lock 동일성만으로 기대를 판정한다. 실행 성공으로 기록하지 않는다."""
    base = {"worker_invoked": False, "recorded_success": False, "fixture_only": True}
    if lock_same is not True:
        return {**base, "result": "not_run", "reason_code": E_TEST_TAMPERED}
    if line is None:
        return {
            **base,
            "result": "not_run",
            "reason_code": E_RUNTIME_NOT_READY,
            "stage_status": "blocked",
            "attempts": 1,
        }
    parsed, err = parse_worker_line(line)
    if err:
        return {**base, "result": "not_run", "reason_code": err}
    matched = assert_expected(expected_values, parsed)
    if stage == "baseline_v1":
        if matched:
            return {**base, "result": "pass", "reason_code": None}
        return {**base, "result": "fail", "reason_code": E_BASELINE_FAIL}
    if stage == "unpatched_v2":
        if matched:
            return {**base, "result": "pass", "reason_code": E_NO_REPRO}
        return {**base, "result": "fail", "reason_code": None}
    if stage == "patched_v2":
        if matched:
            return {**base, "result": "pass", "reason_code": None}
        return {**base, "result": "fail", "reason_code": E_PATCH_TEST_FAIL}
    return {**base, "result": "not_run", "reason_code": E_INTERNAL}


def lock_snapshot(path: str, sha256: str, base_sha: str | None) -> dict:
    """읽기 전용 lock 증거 한 건. base SHA가 없으면 검증된 lock이 아니다."""
    return {
        "path": path,
        "sha256": sha256,
        "lock_base_sha": base_sha,
        "verified": isinstance(base_sha, str) and base_sha != "",
        "worker_may_write": False,
    }


def lock_still_same(before: dict, after: dict) -> bool:
    """경로와 hash가 같고 worker 쓰기가 거부된 두 snapshot이면 True다."""
    if not isinstance(before, dict) or not isinstance(after, dict):
        return False
    return (
        before.get("path") == after.get("path")
        and isinstance(before.get("sha256"), str)
        and before.get("sha256") != ""
        and         before.get("sha256") == after.get("sha256")
        and before.get("lock_base_sha") == after.get("lock_base_sha")
        and before.get("worker_may_write") is False
        and after.get("worker_may_write") is False
    )
