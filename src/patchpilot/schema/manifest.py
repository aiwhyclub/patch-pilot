# 난이도: Mid
# 학습 키워드: JSON Schema, Manifest, ISO 8601
"""실행 전 manifest 뼈대와 최종 manifest의 계약 필드 검사."""

from __future__ import annotations

from patchpilot.schema.codes import (
    BLOCK_CODES,
    DATA_NOTICE,
    ERROR_CODES,
    HOLD_CODES,
    PR_ABSENT,
    PR_EXISTS,
    PR_NOT_ATTEMPTED,
    PR_UNKNOWN,
    SCHEMA_VERSION,
    STAGE_ORDER,
    STAGE_STATUS_VALUES,
    TEST_RESULT_VALUES,
)


def empty_stage(name: str) -> dict:
    """아직 들어가지 않은 stage를 skipped, 시도 0, 시각 null로 만든다."""
    return {
        "name": name,
        "status": "skipped",
        "attempts": 0,
        "started_at": None,
        "ended_at": None,
        "reason_code": None,
    }


def new_manifest(inputs: dict, run_id: str, started_at: str) -> dict:
    """계약 키를 채운 초기 manifest를 만든다. outcome은 끝나기 전 null이다."""
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "idem_key": None,
        "mode": inputs["mode"],
        "started_at": started_at,
        "finished_at": None,
        "inputs": inputs,
        "acquisition": {
            "spec_old": {"status": "not_attempted", "reason_code": None},
            "spec_new": {"status": "not_attempted", "reason_code": None},
            "change_mapping": {"status": "not_attempted", "reason_code": None},
            "customer_checkout": {"status": "not_attempted", "reason_code": None},
            "test_lock": {"status": "not_attempted", "reason_code": None},
            "base_sha": {"status": "not_attempted", "reason_code": None},
            "allowlist": {"status": "not_attempted", "reason_code": None},
        },
        "changes": [],
        "stage_order": list(STAGE_ORDER),
        "stages": [empty_stage(name) for name in STAGE_ORDER],
        "tests": {
            "lock": None,
            "lock_base_sha": None,
            "lock_verified_before": False,
            "lock_verified_after": None,
            "baseline_v1": {"result": "not_run", "expected": "pass"},
            "unpatched_v2": {"result": "not_run", "expected": "fail"},
            "patched_v2": {"result": "not_run", "expected": "pass"},
        },
        "patch": None,
        "approval": {
            "required": bool(inputs.get("open_pr")),
            "approval_ref": inputs.get("approval_ref"),
            "bound_repo": None,
            "bound_base_branch": None,
            "bound_base_sha": None,
            "bound_diff_sha256": None,
            "bound_operation": None,
            "verified": False,
        },
        "pr": {
            "existence": PR_NOT_ATTEMPTED,
            "url": None,
            "number": None,
            "draft": None,
            "branch": None,
            "reused": None,
            "lookup_evidence_path": None,
        },
        "cancelled": None,
        "outcome": None,
        "reason_code": None,
        "evidence": {
            "log_path": None,
            "scan_report_path": None,
            "report_path": None,
            "pre_pr_snapshot_sha256": None,
            "collector_index_path": None,
        },
        "data_notice": DATA_NOTICE,
    }


def set_stage(manifest: dict, name: str, status: str, started_at: str | None, ended_at: str | None, reason_code: str | None) -> None:
    """고정 stage 목록 안의 한 stage 상태와 시도 횟수를 갱신한다."""
    attempts = 0 if status in ("skipped", "pending") else 1
    for stage in manifest["stages"]:
        if stage["name"] == name:
            stage["status"] = status
            stage["attempts"] = attempts
            stage["started_at"] = started_at
            stage["ended_at"] = ended_at
            stage["reason_code"] = reason_code
            return
    raise KeyError(name)


def validate_manifest(manifest: dict) -> list[str]:
    """계약 필드가 빠지거나 outcome과 reason이 어긋나면 이유 문자열을 모은다."""
    errors = []
    required = {
        "schema_version",
        "run_id",
        "idem_key",
        "mode",
        "started_at",
        "finished_at",
        "inputs",
        "acquisition",
        "changes",
        "stage_order",
        "stages",
        "tests",
        "patch",
        "approval",
        "pr",
        "cancelled",
        "outcome",
        "reason_code",
        "evidence",
        "data_notice",
    }
    if not isinstance(manifest, dict) or set(manifest) != required:
        return ["manifest keys"]
    if manifest["schema_version"] != SCHEMA_VERSION:
        errors.append("schema_version")
    if manifest["mode"] not in ("A", "B", "C"):
        errors.append("mode")
    if manifest["stage_order"] != list(STAGE_ORDER):
        errors.append("stage_order")
    if manifest["data_notice"] != DATA_NOTICE:
        errors.append("data_notice")
    names = [stage.get("name") for stage in manifest["stages"]]
    if names != list(STAGE_ORDER):
        errors.append("stages")
    for stage in manifest["stages"]:
        status = stage.get("status")
        if status not in STAGE_STATUS_VALUES:
            errors.append(f"stage status {stage.get('name')}")
        if status in ("skipped", "pending"):
            if stage.get("attempts") != 0 or stage.get("started_at") is not None or stage.get("ended_at") is not None:
                errors.append(f"stage skip {stage.get('name')}")
        elif status == "running":
            if stage.get("attempts", 0) < 1 or stage.get("ended_at") is not None:
                errors.append(f"stage running {stage.get('name')}")
        else:
            if stage.get("attempts", 0) < 1 or not stage.get("started_at") or not stage.get("ended_at"):
                errors.append(f"stage terminal {stage.get('name')}")
    outcome = manifest["outcome"]
    reason = manifest["reason_code"]
    if outcome == "draft_pr_opened" and reason is not None:
        errors.append("success reason")
    if outcome == "patch_only" and reason is not None:
        errors.append("patch_only reason")
    if outcome == "hold" and reason not in HOLD_CODES:
        errors.append("hold reason")
    if outcome == "pr_gate_blocked" and reason not in BLOCK_CODES:
        errors.append("block reason")
    if outcome == "error" and reason not in ERROR_CODES:
        errors.append("error reason")
    if outcome not in (None, "draft_pr_opened", "patch_only", "pr_gate_blocked", "hold", "error"):
        errors.append("outcome")
    pr = manifest["pr"]
    if pr.get("existence") not in (PR_EXISTS, PR_ABSENT, PR_UNKNOWN, PR_NOT_ATTEMPTED):
        errors.append("pr.existence")
    tests = manifest["tests"]
    for name, expected in (
        ("baseline_v1", "pass"),
        ("unpatched_v2", "fail"),
        ("patched_v2", "pass"),
    ):
        item = tests.get(name) or {}
        if item.get("result") not in TEST_RESULT_VALUES or item.get("expected") != expected:
            errors.append(name)
    if "Validated on" in manifest["data_notice"]:
        errors.append("validated wording")
    return errors
