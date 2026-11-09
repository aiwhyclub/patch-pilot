# 난이도: Mid
# 학습 키워드: Classify, AST, Unified Diff
"""샘플 식별자만 받아 정적 분석 envelope를 만든다. 실행과 PR은 하지 않는다."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from patchpilot.diff_spec.classify import classify_documents
from patchpilot.patch.validate import validate_patch
from patchpilot.scan.ast_scan import scan_source
from patchpilot.schema.acceptance import AC_STATUS
from patchpilot.schema.codes import (
    E_RUNTIME_NOT_READY,
    H_PATCH_REJECTED,
    H_UNRESOLVED,
    PR_NOT_ATTEMPTED,
    reason_text,
)
from patchpilot.web.samples import CLIENT_PATH, SAMPLES

ENVELOPE_KIND = "pp-web-static-analysis/1"
SEOUL = ZoneInfo("Asia/Seoul")

_CLASSIFY_OK = "Supported same-parent rename. This is not a customer test result."
_SCAN_OK = "One direct JSON binding. This is not a model call."
_PATCH_OK = (
    "Static preview of the last-key rename passed the patch checks. "
    "This is not a model-generated repair or a customer test result."
)
_PATCH_SKIPPED = "Patch preview was not produced because an earlier static check did not pass."


def analyze_sample(sample_id: str, *, now: datetime | None = None) -> dict:
    """한 샘플의 완전한 웹 envelope. 샘플이 없으면 KeyError다."""
    sample = SAMPLES[sample_id]
    moment = now or datetime.now(SEOUL)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=SEOUL)
    classified = classify_documents(sample["spec_old"], sample["spec_new"], sample["mapping"])
    supported = [item for item in classified.changes if item.supported]
    change = supported[0] if classified.supported and len(supported) == 1 else None
    classify_stage = _classify_stage(sample_id, classified, change)
    scan_stage, operation = _scan_stage(sample, change)
    patch_stage, diff_text, files = _patch_stage(sample, change, classify_stage, scan_stage, operation)
    static_analysis = {
        "classify": classify_stage,
        "scan": scan_stage,
        "patch_preview": patch_stage,
    }
    if any(static_analysis[name]["status"] != "ok" for name in static_analysis):
        diff_text = None
        files = []
        if patch_stage["status"] == "ok":
            patch_stage = _stage("hold", H_UNRESOLVED, _PATCH_SKIPPED, [], sample_id)
            static_analysis["patch_preview"] = patch_stage
    envelope = {
        "envelope_kind": ENVELOPE_KIND,
        "sample_id": sample_id,
        "analyzed_at": moment.astimezone(SEOUL).isoformat(timespec="milliseconds"),
        "static_analysis": static_analysis,
        "patch_preview": {"diff": diff_text, "files": files},
        "runtime": {
            "status": "not_run",
            "reason_code": E_RUNTIME_NOT_READY,
            "user_message": reason_text(E_RUNTIME_NOT_READY),
        },
        "pr": {"existence": PR_NOT_ATTEMPTED},
        "ac24": AC_STATUS["PP-AC-024"],
        "cli_manifest_claim": False,
        "downloadable": False,
    }
    envelope["downloadable"] = _complete(envelope)
    return envelope


def _classify_stage(sample_id: str, classified, change) -> dict:
    """분류 결과만 옮긴다. supported가 아니면 hold다."""
    refs = [
        f"web/samples/{sample_id}/spec_old.json",
        f"web/samples/{sample_id}/spec_new.json",
        f"web/samples/{sample_id}/mapping.json",
    ]
    if change is None:
        reason = classified.reason_code or H_UNRESOLVED
        summary = "Classification did not yield one supported rename."
        return _stage("hold", reason, summary, refs, sample_id)
    summary = f"1 supported {change.kind} change."
    return _stage("ok", None, summary, refs, sample_id, ok_message=_CLASSIFY_OK)


def _scan_stage(sample, change):
    """분류가 단일 지원 변경일 때만 소스를 스캔한다."""
    sample_id = sample["id"]
    refs = [f"web/samples/{sample_id}/{CLIENT_PATH}"]
    if change is None:
        return _stage("hold", H_UNRESOLVED, "Scan did not run.", refs, sample_id), None
    operation = (change.operation["method"], change.operation["path"])
    pointers = [change.old_pointer.split(".")]
    scanned = scan_source(CLIENT_PATH, sample["source"], pointers, operation)
    if scanned.unresolved or not scanned.sites:
        summary = "The scan did not accept a direct binding."
        return _stage("hold", H_UNRESOLVED, summary, refs, sample_id), operation
    summary = f"{len(scanned.sites)} direct JSON binding."
    return _stage("ok", None, summary, refs, sample_id, ok_message=_SCAN_OK), operation


def _patch_stage(sample, change, classify_stage, scan_stage, operation):
    """앞 단계가 모두 ok일 때만 결정적 diff를 만들고 validate_patch로 확인한다."""
    sample_id = sample["id"]
    refs = [f"web/samples/{sample_id}/{CLIENT_PATH}"]
    if classify_stage["status"] != "ok" or scan_stage["status"] != "ok" or change is None or operation is None:
        reason = scan_stage["reason_code"] or classify_stage["reason_code"] or H_UNRESOLVED
        return _stage("hold", reason, _PATCH_SKIPPED, refs, sample_id), None, []
    old_keys = change.old_pointer.split(".")
    new_key = change.new_pointer.split(".")[-1] if change.new_pointer else ""
    updated = _rename_last_key(sample["source"], old_keys[-1], new_key)
    diff_text = _unified(CLIENT_PATH, sample["source"], updated) if updated else None
    if diff_text is None:
        return _stage("hold", H_PATCH_REJECTED, "No static preview diff.", refs, sample_id), None, []
    renames = [{"path": CLIENT_PATH, "old_keys": old_keys, "new_key": new_key}]
    rejected = validate_patch({CLIENT_PATH: sample["source"]}, diff_text, renames)
    if rejected is not None:
        return _stage("hold", rejected, "Patch checks rejected the preview.", refs, sample_id), None, []
    return _stage("ok", None, "1 file, last-key rename.", refs, sample_id, ok_message=_PATCH_OK), diff_text, [CLIENT_PATH]


def _rename_last_key(source: str, old_key: str, new_key: str) -> str | None:
    """문자열 키 한 곳만 바꾼다. 없거나 여러 곳이면 None이다."""
    if not old_key or not new_key or old_key == new_key:
        return None
    patterns = (
        (f'["{old_key}"]', f'["{new_key}"]'),
        (f"['{old_key}']", f"['{new_key}']"),
        (f'.get("{old_key}")', f'.get("{new_key}")'),
        (f".get('{old_key}')", f".get('{new_key}')"),
    )
    hits = []
    for old, new in patterns:
        start = 0
        while True:
            index = source.find(old, start)
            if index < 0:
                break
            hits.append((index, old, new))
            start = index + len(old)
    if len(hits) != 1:
        return None
    index, old, new = hits[0]
    return source[:index] + new + source[index + len(old) :]


def _unified(path: str, original: str, updated: str) -> str | None:
    """한 줄만 다른 unified diff. 문맥이 원문과 같게 만든다."""
    if not original.endswith("\n") or not updated.endswith("\n"):
        return None
    old_lines = original.splitlines(keepends=True)
    new_lines = updated.splitlines(keepends=True)
    if len(old_lines) != len(new_lines):
        return None
    changed = [index for index, (left, right) in enumerate(zip(old_lines, new_lines)) if left != right]
    if len(changed) != 1:
        return None
    index = changed[0]
    has_context = index > 0
    start = index if has_context else index + 1
    count = 2 if has_context else 1
    parts = [
        f"--- a/{path}\n",
        f"+++ b/{path}\n",
        f"@@ -{start},{count} +{start},{count} @@\n",
    ]
    if has_context:
        parts.append(" " + old_lines[index - 1])
    parts.append("-" + old_lines[index])
    parts.append("+" + new_lines[index])
    return "".join(parts)


def _stage(status: str, reason: str | None, summary: str, refs: list[str], sample_id: str, ok_message: str = "") -> dict:
    """단계 객체. reason이 있으면 계약 문장을 그대로 쓴다."""
    del sample_id
    message = reason_text(reason) if reason else ok_message
    return {
        "status": status,
        "reason_code": reason,
        "user_message": message,
        "evidence": {"summary": summary, "refs": refs},
    }


def _complete(envelope: dict) -> bool:
    """diff 규칙과 고정 필드가 맞을 때만 다운로드를 허용한다."""
    static_analysis = envelope["static_analysis"]
    all_ok = all(static_analysis[name]["status"] == "ok" for name in ("classify", "scan", "patch_preview"))
    diff = envelope["patch_preview"]["diff"]
    if all_ok:
        diff_ok = isinstance(diff, str) and diff != ""
    else:
        diff_ok = diff is None
    runtime = envelope["runtime"]
    return bool(
        diff_ok
        and envelope["envelope_kind"] == ENVELOPE_KIND
        and envelope["cli_manifest_claim"] is False
        and runtime["status"] == "not_run"
        and runtime["reason_code"] == E_RUNTIME_NOT_READY
        and envelope["pr"]["existence"] == PR_NOT_ATTEMPTED
        and envelope["ac24"] == "NOT_RUN"
        and isinstance(envelope["patch_preview"]["files"], list)
    )
