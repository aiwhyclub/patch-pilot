# 난이도: Easy
# 학습 키워드: Enum, API Contract, Exit Code
"""계약 C12·C14의 outcome, exit, reason 문구를 한곳에 둔다."""

from __future__ import annotations

# 계약 C13 원문. 성공 run 전이므로 validation pending을 유지한다.
DATA_NOTICE = (
    "Weather data by Open-Meteo.com (CC BY 4.0). The v2 rename "
    "(current_weather.temperature → current_weather.temperature_2m) is a "
    "team-made change; the new key name is borrowed from Open-Meteo's "
    "`current` block, but this path does not exist in Open-Meteo. Demo scope: "
    "1 API, 1 customer repo, 1 change type; validation pending."
)

SCHEMA_VERSION = "pp-manifest/1"

# 계약 C11 stage_order. 순서를 바꾸지 않는다.
STAGE_ORDER = (
    "diff_spec",
    "scan",
    "test_baseline_v1",
    "test_unpatched_v2",
    "patch_generate",
    "patch_validate",
    "test_patched_v2",
    "approval_gate",
    "base_sha_check",
    "pr_evidence_gate",
    "pr_open",
)

# 계약 C14 코드. 값은 표의 철자와 같고 의미를 바꾸지 않는다.
H_NO_CHANGE = "H_NO_CHANGE"
H_UNSUPPORTED_KIND = "H_UNSUPPORTED_KIND"
H_UNSUPPORTED_SPEC = "H_UNSUPPORTED_SPEC"
H_NO_MAPPING = "H_NO_MAPPING"
H_METADATA_MISSING = "H_METADATA_MISSING"
H_UNIT_OR_SEMANTIC = "H_UNIT_OR_SEMANTIC"
H_UNRESOLVED = "H_UNRESOLVED"
H_PATCH_REJECTED = "H_PATCH_REJECTED"
H_MODEL_SEND_BLOCKED = "H_MODEL_SEND_BLOCKED"
H_BASE_MOVED = "H_BASE_MOVED"
H_REUSED_PR_MISMATCH = "H_REUSED_PR_MISMATCH"
H_CANCELLED = "H_CANCELLED"
B_NO_APPROVAL = "B_NO_APPROVAL"
B_BINDING_MISMATCH = "B_BINDING_MISMATCH"
B_NO_PERMISSION = "B_NO_PERMISSION"
B_EVIDENCE_GATE = "B_EVIDENCE_GATE"
E_MODE_UNSUPPORTED = "E_MODE_UNSUPPORTED"
E_INPUT = "E_INPUT"
E_PATH_BOUNDARY = "E_PATH_BOUNDARY"
E_WORKER_RESULT = "E_WORKER_RESULT"
E_TEST_TAMPERED = "E_TEST_TAMPERED"
E_BASELINE_FAIL = "E_BASELINE_FAIL"
E_NO_REPRO = "E_NO_REPRO"
E_PATCH_TEST_FAIL = "E_PATCH_TEST_FAIL"
E_TIMEOUT = "E_TIMEOUT"
E_PR_CREATE_FAILED = "E_PR_CREATE_FAILED"
E_PR_RESULT_UNKNOWN = "E_PR_RESULT_UNKNOWN"
E_OUTPUT_ROOT = "E_OUTPUT_ROOT"
E_RESOURCE_LIMIT = "E_RESOURCE_LIMIT"
E_RUNTIME_NOT_READY = "E_RUNTIME_NOT_READY"
E_INTERNAL = "E_INTERNAL"

# 계약 C14 영문 안내. 번역하거나 의미를 바꾸지 않는다.
REASON_TEXT = {
    "H_NO_CHANGE": "No supported API change found. No PR was opened.",
    "H_UNSUPPORTED_KIND": "Change type not supported (only same-parent field rename). Manual review needed.",
    "H_UNSUPPORTED_SPEC": "OpenAPI input outside MVP limits. Manual review needed.",
    "H_NO_MAPPING": "No provider-approved mapping for this change. Manual review needed.",
    "H_METADATA_MISSING": "Mapping lacks type/unit/semantic confirmation. Manual review needed.",
    "H_UNIT_OR_SEMANTIC": "Unit or meaning changed; not auto-patched. Manual review needed.",
    "H_UNRESOLVED": "Some usages could not be resolved statically. Manual review needed.",
    "H_PATCH_REJECTED": "Generated patch failed safety checks and was discarded.",
    "H_MODEL_SEND_BLOCKED": "Model send blocked (no consent, uncertainty, or secret in excerpt).",
    "H_BASE_MOVED": "Customer branch changed since approval. Re-run required.",
    "H_REUSED_PR_MISMATCH": "An existing PR does not match this verified patch or approval. Manual review needed.",
    "H_CANCELLED": "Run cancelled before any PR side effect.",
    "B_NO_APPROVAL": "PR requested but no bound human approval found. No PR was opened.",
    "B_BINDING_MISMATCH": "Approval does not match this repo, base SHA, or diff. Re-approval needed. No PR was opened.",
    "B_NO_PERMISSION": "Insufficient permission for the target repository. No PR was opened.",
    "B_EVIDENCE_GATE": "Pre-PR evidence check failed. No PR was opened.",
    "E_MODE_UNSUPPORTED": "Mode not implemented. Requested mode preserved; execution is A-only.",
    "E_INPUT": "Invalid input. See report.",
    "E_PATH_BOUNDARY": "File path outside allowed roots; access denied.",
    "E_WORKER_RESULT": "Untrusted worker result invalid or out of bounds.",
    "E_TEST_TAMPERED": "Locked tests or fixtures changed; run invalid.",
    "E_BASELINE_FAIL": "Tests fail on v1; baseline invalid.",
    "E_NO_REPRO": "Tests pass on unpatched v2; breakage not reproduced.",
    "E_PATCH_TEST_FAIL": "Patched code fails locked tests.",
    "E_TIMEOUT": "Time limit exceeded.",
    "E_PR_CREATE_FAILED": "PR creation failed (confirmed absent). Manual check before retry.",
    "E_PR_RESULT_UNKNOWN": "PR state unknown. Check the repository manually before any retry.",
    "E_OUTPUT_ROOT": "Output directory unsafe or not writable; minimal diagnostics only.",
    "E_RESOURCE_LIMIT": "Resource limit exceeded.",
    "E_RUNTIME_NOT_READY": "Runtime prerequisites are not verified. No customer tests were executed.",
    "E_INTERNAL": "Internal error. See report.",
}

HOLD_CODES = tuple(code for code in REASON_TEXT if code.startswith("H_"))
BLOCK_CODES = tuple(code for code in REASON_TEXT if code.startswith("B_"))
ERROR_CODES = tuple(code for code in REASON_TEXT if code.startswith("E_"))

# 계약 C12 exit. usage error 2는 manifest가 없을 때만 쓴다.
OUTCOME_EXIT = {
    "draft_pr_opened": 0,
    "patch_only": 10,
    "pr_gate_blocked": 11,
    "hold": 20,
    "error": 30,
}

PR_EXISTS = "exists"
PR_ABSENT = "absent"
PR_UNKNOWN = "unknown"
PR_NOT_ATTEMPTED = "not_attempted"

PR_ABSENT_TEXT = "PR not created (confirmed absent)."
PR_UNKNOWN_TEXT = "PR creation status unknown. Manual verification required. Do not retry automatically."
PR_NOT_ATTEMPTED_TEXT = "PR creation not attempted."

UNKNOWN_CODE_TEXT = "Unknown status code. Manual review needed."

TEST_RESULT_VALUES = ("pass", "fail", "not_run")
STAGE_STATUS_VALUES = ("pending", "skipped", "running", "passed", "failed", "blocked")


def reason_text(code: str | None) -> str:
    """알려진 reason이면 계약 문장을, 아니면 escape용 원문과 미정의 안내를 돌려준다."""
    if code is None:
        return ""
    if code in REASON_TEXT:
        return REASON_TEXT[code]
    return f"{code} {UNKNOWN_CODE_TEXT}"


def outcome_for_reason(code: str) -> str | None:
    """reason 접두사에 해당하는 outcome을 돌려주고, 표에 없으면 None을 돌려준다."""
    if code in HOLD_CODES:
        return "hold"
    if code in BLOCK_CODES:
        return "pr_gate_blocked"
    if code in ERROR_CODES:
        return "error"
    return None
