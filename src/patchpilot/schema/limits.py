# 난이도: Easy
# 학습 키워드: Timeout, Retry, Resource Limit, cgroup
"""계약 C4·C8·C17의 수치를 보관한다. 수치만 있고 강제됐다는 뜻은 아니다."""

from __future__ import annotations

# 계약 C8. approval_gate는 실행시간 제외, 시도 상한만 있다.
STAGE_LIMITS = {
    "diff_spec": {"timeout_seconds": 60, "max_attempts": 1},
    "scan": {"timeout_seconds": 60, "max_attempts": 1},
    "test_baseline_v1": {"timeout_seconds": 300, "max_attempts": 1},
    "test_unpatched_v2": {"timeout_seconds": 300, "max_attempts": 1},
    "patch_generate": {"timeout_seconds": 120, "max_attempts": 3},
    "patch_validate": {"timeout_seconds": 30, "max_attempts": 1},
    "test_patched_v2": {"timeout_seconds": 300, "max_attempts": 1},
    "approval_gate": {"timeout_seconds": None, "max_attempts": 1},
    "base_sha_check": {"timeout_seconds": 30, "max_attempts": 2},
    "pr_evidence_gate": {"timeout_seconds": 30, "max_attempts": 1},
    "pr_open": {"timeout_seconds": 60, "max_attempts": 3},
}

OVERALL_TIMEOUT_SECONDS = 20 * 60

# 계약 C4 [TL-제안]. 이 상한을 넘으면 일부를 성공으로 쓰지 않는다.
SCAN_MAX_FILES = 200
SCAN_MAX_FILE_BYTES = 1_000_000

# 계약 C6 worker 결과 상한.
WORKER_MAX_VALUES = 32
WORKER_MAX_ELEMENT_CHARS = 64
WORKER_MAX_JSON_BYTES = 8 * 1024

# 계약 C17 계획값. cgroup 강제가 증명되기 전에는 runner를 열지 않는다.
RESOURCE_LIMITS = {
    "cpu": 1,
    "memory_mib": 512,
    "pids": 64,
    "cpu_time_seconds": 60,
    "test_wall_seconds": 300,
    "log_bytes_per_stage": 1 * 1024 * 1024,
    "log_bytes_total": 10 * 1024 * 1024,
    "disk_bytes": 50 * 1024 * 1024,
}

SPEC_MAX_BYTES = 1_000_000


def within_stage_attempt(stage: str, attempts: int) -> bool:
    """시도 횟수가 그 stage의 max_attempts 안인지 확인한다."""
    limit = STAGE_LIMITS[stage]["max_attempts"]
    return 1 <= attempts <= limit


def within_log_budget(stage_bytes: int, total_bytes: int) -> bool:
    """단계 로그와 전체 로그가 C17 계획 용량 안인지 확인한다."""
    return (
        0 <= stage_bytes <= RESOURCE_LIMITS["log_bytes_per_stage"]
        and 0 <= total_bytes <= RESOURCE_LIMITS["log_bytes_total"]
    )


def overall_timed_out(elapsed_seconds: float) -> bool:
    """전체 20분 상한을 넘었는지 확인한다."""
    return elapsed_seconds > OVERALL_TIMEOUT_SECONDS
