# 난이도: Mid
# 학습 키워드: Atomic Operation, Append-Only Log, File Lock
"""원자적 lock 파일과 append-only ledger. 내구성 복구는 아직 증명되지 않았다."""

from __future__ import annotations

import json
import os
from pathlib import Path

from patchpilot.core.capability import LEDGER_DURABILITY_PROVEN
from patchpilot.schema.codes import E_INTERNAL, E_PR_CREATE_FAILED, E_PR_RESULT_UNKNOWN, E_RUNTIME_NOT_READY


def pr_stage_blocked() -> bool:
    """ledger 내구성이 증명되기 전에는 PR 단계가 막혀 있는지 확인한다."""
    return not LEDGER_DURABILITY_PROVEN


def acquire_lock(path: Path) -> bool:
    """O_EXCL로 lock 파일을 만들고, 이미 있으면 False를 돌려준다."""
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError:
        return False
    try:
        os.write(fd, b"pending\n")
    finally:
        os.close(fd)
    return True


def append_record(path: Path, record: dict) -> None:
    """ledger 끝에 JSON 한 줄을 추가하고 fsync한다. 기존 줄은 수정하지 않는다."""
    line = (json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    fd = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
    try:
        os.write(fd, line)
        os.fsync(fd)
    finally:
        os.close(fd)


_PENDING_FIELDS = ("run_id", "idem_key", "repo", "base_branch", "diff_sha256", "state")


def replay_lines(lines: list[str]) -> dict:
    """append된 줄만 해석한다. 디스크 내구성이 증명됐다는 뜻은 아니다."""
    pending_ids = []
    for line in lines:
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            return _replay_stop(E_PR_RESULT_UNKNOWN)
        if not isinstance(item, dict) or any(item.get(key) in (None, "") for key in _PENDING_FIELDS):
            return _replay_stop(E_PR_RESULT_UNKNOWN)
        if item.get("state") not in ("pending", "unknown"):
            return _replay_stop(E_INTERNAL)
        if item["state"] == "pending":
            pending_ids.append(item["run_id"])
    if len(pending_ids) != len(set(pending_ids)):
        stopped = _replay_stop(E_RUNTIME_NOT_READY)
        stopped["cause"] = "duplicate pending run"
        return stopped
    return {
        "ok": True,
        "keep_lock": bool(pending_ids),
        "auto_reissue": False,
        "publish": False,
        "reason_code": None,
        "durable_proven": LEDGER_DURABILITY_PROVEN,
        "network": False,
    }


def crash_view(point: str) -> dict:
    """중단 지점별 lock과 재발행 금지. 알 수 없는 지점은 예상 밖 bug다."""
    known = {
        "before_lock": {"keep_lock": False, "reason_code": None},
        "lock_without_ledger": {"keep_lock": True, "reason_code": E_RUNTIME_NOT_READY},
        "pending_not_flushed": {"keep_lock": True, "reason_code": E_RUNTIME_NOT_READY},
        "after_remote_unknown": {"keep_lock": True, "reason_code": E_PR_RESULT_UNKNOWN},
    }
    found = known.get(point)
    if found is None:
        found = {"keep_lock": True, "reason_code": E_INTERNAL}
    return {
        **found,
        "auto_reissue": False,
        "publish": False,
        "durable_proven": False,
        "network": False,
    }


def _replay_stop(reason: str) -> dict:
    """깨진 ledger는 잠금을 유지하고 자동 재발행하지 않는다."""
    return {
        "ok": False,
        "keep_lock": True,
        "auto_reissue": False,
        "publish": False,
        "reason_code": reason,
        "durable_proven": False,
        "network": False,
    }


def reconcile(existence: str) -> dict:
    """조회 결과별로 lock 유지와 자동 재발행 금지를 돌려준다."""
    if existence == "not_attempted":
        return {"keep_lock": False, "auto_reissue": False, "reason_code": None}
    if existence == "absent":
        return {"keep_lock": True, "auto_reissue": False, "reason_code": E_PR_CREATE_FAILED}
    if existence == "unknown":
        return {"keep_lock": True, "auto_reissue": False, "reason_code": E_PR_RESULT_UNKNOWN}
    return {"keep_lock": True, "auto_reissue": False, "reason_code": None}
