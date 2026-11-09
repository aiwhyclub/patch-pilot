# 난이도: Mid
# 학습 키워드: SHA-256, Evidence, Integrity
"""단계가 끝난 파일의 path, sha256, stage, run_id를 기록하고 나중에 다시 해시한다."""

from __future__ import annotations

import hashlib
import stat
from pathlib import Path

from patchpilot.schema.codes import B_EVIDENCE_GATE, E_RUNTIME_NOT_READY


def hash_file(path: Path) -> str:
    """symlink가 아닌 일반 파일의 sha256을 계산한다."""
    st = path.lstat()
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode) or st.st_nlink > 1:
        raise OSError("refusing to hash a link")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def file_record(path: Path, stage: str, run_id: str) -> dict:
    """collector index 한 줄에 해당하는 레코드를 만든다."""
    return {"path": path.as_posix(), "sha256": hash_file(path), "stage": stage, "run_id": run_id}


# 고객 테스트 세 단계의 collector 기록. 이 이름이 없다고 baseline이 끝난 것이 아니다.
BASELINE_STAGES = ("test_baseline_v1", "test_unpatched_v2", "test_patched_v2")


def plan_lock_snapshots(lock_record: dict) -> list[dict]:
    """실행 전에 lock hash를 세 테스트 단계에 계획으로만 붙인다. executed는 False다."""
    if not lock_record.get("path") or not lock_record.get("sha256") or not lock_record.get("run_id"):
        raise ValueError("lock record")
    rows = []
    for stage in BASELINE_STAGES:
        rows.append(
            {
                "path": lock_record["path"],
                "sha256": lock_record["sha256"],
                "stage": stage,
                "run_id": lock_record["run_id"],
                "executed": False,
            }
        )
    return rows


def baseline_stages_recorded(records: list[dict]) -> bool:
    """세 단계가 executed=True로 모두 있을 때만 True다. 계획 행은 완료가 아니다."""
    if not isinstance(records, list) or not records:
        return False
    finished = set()
    for record in records:
        if isinstance(record, dict) and record.get("executed") is True:
            finished.add(record.get("stage"))
    return set(BASELINE_STAGES).issubset(finished)


def index_rehash_decision(*, matches: bool, sequence_finished: bool) -> str | None:
    """테스트가 끝나지 않았으면 증거 gate 통과로 세지 않는다."""
    if sequence_finished is not True:
        return E_RUNTIME_NOT_READY
    if matches is True:
        return None
    return B_EVIDENCE_GATE


def rehash_matches(records: list[dict]) -> bool:
    """기록된 hash와 현재 파일 hash가 모두 같으면 True를 돌려준다."""
    if not isinstance(records, list):
        return False
    for record in records:
        if not isinstance(record, dict):
            return False
        if not record.get("path") or not record.get("sha256") or not record.get("stage") or not record.get("run_id"):
            return False
        try:
            fresh = hash_file(Path(record["path"]))
        except OSError:
            return False
        if fresh != record["sha256"]:
            return False
    return True
