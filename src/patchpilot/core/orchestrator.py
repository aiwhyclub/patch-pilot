# 난이도: Difficult
# 학습 키워드: Orchestration, Fail Closed, Manifest, Exit Code
"""입력 검사, 분류, 정적 탐색까지 실행하고 고객 실행·모델·PR 앞에서는 멈춘다."""

from __future__ import annotations

import hashlib
import json
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from patchpilot.collector.evidence import file_record
from patchpilot.core.capability import enforce_unproven_block
from patchpilot.core.paths import (
    BoundaryError,
    glob_match,
    iter_checkout,
    lexical_path,
    prepare_out_dir,
    require_real_dir,
    require_real_file,
)
from patchpilot.diff_spec.classify import classify_documents, load_json_bytes
from patchpilot.runner.guard import execution_block_reason
from patchpilot.scan.ast_scan import scan_files
from patchpilot.schema.codes import (
    DATA_NOTICE,
    E_INPUT,
    E_INTERNAL,
    E_MODE_UNSUPPORTED,
    E_OUTPUT_ROOT,
    E_PATH_BOUNDARY,
    H_UNRESOLVED,
    H_UNSUPPORTED_SPEC,
    OUTCOME_EXIT,
    REASON_TEXT,
)
from patchpilot.schema.limits import SCAN_MAX_FILE_BYTES, SCAN_MAX_FILES, SPEC_MAX_BYTES
from patchpilot.schema.manifest import new_manifest, set_stage, validate_manifest
from patchpilot.schema.redact import mask_obj, mask_text

_KST = ZoneInfo("Asia/Seoul")


@dataclass
class RunConfig:
    """CLI가 넘기는 한 run의 입력. base_sha는 여기서 만들지 않는다."""

    mode: str
    spec_old: str
    spec_new: str
    change_mapping: str
    specs_root: str
    customer_repo: str
    customer_base_ref: str
    customer_checkout: str
    test_lock: str
    lock_root: str
    allowlist: list[str]
    pr_repo: str
    pr_base_branch: str
    open_pr: bool
    approval_ref: str | None
    model_send_consent: bool
    out_dir: str
    cwd: Path


def execute(config: RunConfig, stdout=None, stderr=None) -> int:
    """한 번의 점검을 끝내고 계약 exit code를 돌려준다. 고객 프로세스는 시작하지 않는다."""
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    logs: list[str] = []

    def log(message: str) -> None:
        text = mask_text(message)
        logs.append(text)
        print(text, file=stderr)

    started = _now()
    manifest = new_manifest(_inputs(config), uuid.uuid4().hex, started)
    _set_evidence_paths(manifest, config.out_dir)
    records: list[dict] = []
    scan_body = {"status": "not_run", "sites": []}

    def finish(outcome: str, reason: str | None) -> int:
        return _finish(config, manifest, outcome, reason, logs, records, scan_body, stdout, stderr)

    others = []
    for raw in (config.specs_root, config.customer_checkout, config.lock_root):
        try:
            others.append(lexical_path(config.cwd, raw))
        except BoundaryError:
            others.append(None)
    try:
        prepare_out_dir(config.cwd, config.out_dir, [item for item in others if item is not None])
    except BoundaryError:
        return _emit_without_files(manifest, "error", E_OUTPUT_ROOT, stdout, stderr)

    if config.mode in ("B", "C"):
        log("mode is not A; execution stopped and the requested mode was kept")
        return finish("error", E_MODE_UNSUPPORTED)
    if not _identity_ok(config):
        log("customer_repo and pr_target.repo must be the same non-empty value")
        return finish("error", E_INPUT)
    try:
        specs_root = require_real_dir(config.cwd, config.specs_root)
        checkout = require_real_dir(config.cwd, config.customer_checkout)
        lock_root = require_real_dir(config.cwd, config.lock_root)
        spec_old = require_real_file(specs_root, config.spec_old)
        spec_new = require_real_file(specs_root, config.spec_new)
        mapping_path = require_real_file(specs_root, config.change_mapping)
        lock_path = require_real_file(lock_root, config.test_lock)
    except BoundaryError:
        _reject_inputs(manifest)
        log(REASON_TEXT[E_PATH_BOUNDARY])
        return finish("error", E_PATH_BOUNDARY)
    except FileNotFoundError:
        log(REASON_TEXT[E_INPUT])
        return finish("error", E_INPUT)

    try:
        old_bytes = _read_capped(spec_old, SPEC_MAX_BYTES)
        new_bytes = _read_capped(spec_new, SPEC_MAX_BYTES)
        map_bytes = _read_capped(mapping_path, SPEC_MAX_BYTES)
    except ValueError:
        _mark(manifest, "diff_spec", "passed", H_UNSUPPORTED_SPEC)
        log("OpenAPI input exceeds the MVP size limit")
        return finish("hold", H_UNSUPPORTED_SPEC)
    try:
        lock_bytes = _read_capped(lock_path, SPEC_MAX_BYTES)
    except ValueError:
        log("test lock exceeds the MVP size limit")
        return finish("error", E_INPUT)

    manifest["inputs"]["spec_old_sha256"] = hashlib.sha256(old_bytes).hexdigest()
    manifest["inputs"]["spec_new_sha256"] = hashlib.sha256(new_bytes).hexdigest()
    manifest["inputs"]["change_mapping_sha256"] = hashlib.sha256(map_bytes).hexdigest()
    manifest["tests"]["lock"] = [
        {"path": f"{config.lock_root}/{config.test_lock}", "sha256": hashlib.sha256(lock_bytes).hexdigest()}
    ]
    manifest["acquisition"]["spec_old"] = {"status": "acquired", "reason_code": None}
    manifest["acquisition"]["spec_new"] = {"status": "acquired", "reason_code": None}
    manifest["acquisition"]["change_mapping"] = {"status": "acquired", "reason_code": None}
    manifest["acquisition"]["test_lock"] = {"status": "acquired", "reason_code": None}
    manifest["acquisition"]["customer_checkout"] = {"status": "acquired", "reason_code": None}
    manifest["acquisition"]["allowlist"] = {"status": "acquired", "reason_code": None}
    records.append(file_record(spec_old, "diff_spec", manifest["run_id"]))
    records.append(file_record(spec_new, "diff_spec", manifest["run_id"]))
    records.append(file_record(mapping_path, "diff_spec", manifest["run_id"]))

    old_doc, old_err = load_json_bytes(old_bytes)
    new_doc, new_err = load_json_bytes(new_bytes)
    map_doc, map_err = load_json_bytes(map_bytes)
    if old_err or new_err or map_err:
        _mark(manifest, "diff_spec", "passed", H_UNSUPPORTED_SPEC)
        log("OpenAPI or mapping JSON was rejected")
        return finish("hold", H_UNSUPPORTED_SPEC)
    classified = classify_documents(old_doc, new_doc, map_doc)
    manifest["changes"] = [item.as_dict() for item in classified.changes]
    _mark(manifest, "diff_spec", "passed", classified.reason_code)
    log(f"diff_spec reason={classified.reason_code or 'supported'}")
    if not classified.supported:
        return finish("hold", classified.reason_code or H_UNSUPPORTED_SPEC)

    try:
        status, files = _collect_py(checkout, config.allowlist)
    except BoundaryError:
        _reject_inputs(manifest)
        log(REASON_TEXT[E_PATH_BOUNDARY])
        return finish("error", E_PATH_BOUNDARY)
    if status != "ok":
        scan_body = {"status": "unresolved", "sites": []}
        _mark(manifest, "scan", "passed", H_UNRESOLVED)
        log("static scan could not cover the allowlist inside its limits")
        return finish("hold", H_UNRESOLVED)
    supported = [item for item in classified.changes if item.supported]
    operations = {(item.operation.get("method"), item.operation.get("path")) for item in supported}
    if len(operations) != 1:
        scan_body = {"status": "unresolved", "sites": []}
        _mark(manifest, "scan", "passed", H_UNRESOLVED)
        log("static scan needs one approved operation")
        return finish("hold", H_UNRESOLVED)
    pointers = [item.old_pointer.split(".") for item in supported]
    scanned = scan_files(files, pointers, next(iter(operations)))
    scan_body = {
        "status": "unresolved" if scanned.unresolved else "sites_found",
        "sites": [site.as_dict() for site in scanned.sites],
    }
    _mark(manifest, "scan", "passed", H_UNRESOLVED if scanned.unresolved else None)
    log(f"scan sites={len(scanned.sites)} unresolved={scanned.unresolved}")
    if scanned.unresolved or not scanned.sites:
        return finish("hold", H_UNRESOLVED)

    block = execution_block_reason()
    _mark(manifest, "test_baseline_v1", "blocked", E_INTERNAL)
    # C14에 런타임 미검증 전용 코드가 없다. E_INTERNAL은 그 공백의 기존 error이고
    # E_BASELINE_FAIL이나 pr_gate_blocked가 아니다. 테스트 결과는 not_run으로 둔다.
    log(
        "test_baseline_v1 status=blocked reason=E_INTERNAL. "
        "This is not E_BASELINE_FAIL. baseline_v1 result stays not_run. "
        "pr_gate_blocked is not used. No customer process was started. "
        f"guard={block}."
    )
    return finish("error", E_INTERNAL)


def _finish(config, manifest, outcome, reason, logs, records, scan_body, stdout, stderr) -> int:
    """outcome을 미증명 성공에서 내리고 manifest, report, collector index를 쓴다."""
    outcome = enforce_unproven_block(outcome)
    if outcome == "error" and reason not in REASON_TEXT:
        reason = E_INTERNAL
    if outcome == "error" and reason is None:
        reason = E_INTERNAL
    manifest["outcome"] = outcome
    manifest["reason_code"] = reason
    manifest["finished_at"] = _now()
    problems = validate_manifest(manifest)
    if problems:
        print(mask_text("manifest validation: " + ",".join(problems)), file=stderr)
    out = config.cwd.joinpath(*config.out_dir.split("/"))
    scan_path = out / "scan-report.json"
    index_path = out / "collector-index.json"
    report_path = out / "report.md"
    manifest_path = out / "manifest.json"
    log_path = out / "run.log"
    _write_json(scan_path, scan_body)
    records.append(file_record(scan_path, "scan", manifest["run_id"]))
    _write_json(index_path, records)
    visible = mask_obj(manifest, skip_keys=frozenset({"data_notice"}))
    if visible.get("data_notice") != DATA_NOTICE:
        visible["data_notice"] = DATA_NOTICE
    render_stdout, render_report = _renderers()
    report = render_report(visible)
    summary = render_stdout(visible)
    _write_text(report_path, report)
    _write_json(manifest_path, visible)
    _write_text(log_path, "\n".join(logs) + ("\n" if logs else ""))
    stdout.write(summary)
    return OUTCOME_EXIT[outcome]


def _emit_without_files(manifest, outcome, reason, stdout, stderr) -> int:
    """out_dir이 위험하면 파일을 만들지 않고 stdout과 stderr만 낸다."""
    manifest["outcome"] = outcome
    manifest["reason_code"] = reason
    manifest["finished_at"] = _now()
    render_stdout, _render_report = _renderers()
    stdout.write(render_stdout(manifest))
    print(mask_text(REASON_TEXT[reason]), file=stderr)
    return OUTCOME_EXIT[outcome]


def _renderers():
    """presentation 패키지를 repo 루트에서 찾아 stdout/report 함수를 불러온다."""
    try:
        from presentation.renderers.text import render_report, render_stdout
    except ImportError:
        root = Path(__file__).resolve().parents[3]
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        from presentation.renderers.text import render_report, render_stdout
    return render_stdout, render_report


def _inputs(config: RunConfig) -> dict:
    """CLI 원문과 아직 없는 획득 SHA 자리를 manifest inputs로 만든다."""
    return {
        "mode": config.mode,
        "spec_old": config.spec_old,
        "spec_new": config.spec_new,
        "change_mapping": config.change_mapping,
        "specs_root": config.specs_root,
        "customer_repo": config.customer_repo,
        "customer_base_ref": config.customer_base_ref,
        "customer_checkout": config.customer_checkout,
        "test_lock": config.test_lock,
        "lock_root": config.lock_root,
        "allowlist": list(config.allowlist),
        "pr_target": {"repo": config.pr_repo, "base_branch": config.pr_base_branch},
        "open_pr": config.open_pr,
        "approval_ref": config.approval_ref,
        "model_send_consent": config.model_send_consent,
        "out_dir": config.out_dir,
        "base_sha": None,
        "spec_old_sha256": None,
        "spec_new_sha256": None,
        "change_mapping_sha256": None,
    }


def _set_evidence_paths(manifest: dict, out_dir: str) -> None:
    """증거 파일의 상대 경로만 적고, PR 전 hash는 아직 null로 둔다."""
    manifest["evidence"] = {
        "log_path": f"{out_dir}/run.log",
        "scan_report_path": f"{out_dir}/scan-report.json",
        "report_path": f"{out_dir}/report.md",
        "pre_pr_snapshot_sha256": None,
        "collector_index_path": f"{out_dir}/collector-index.json",
    }


def _identity_ok(config: RunConfig) -> bool:
    """고객 repo와 PR 대상 repo가 빈 값 없이 같은 문자열인지 확인한다."""
    values = (config.customer_repo, config.pr_repo, config.customer_base_ref, config.pr_base_branch)
    if any(not isinstance(item, str) or item == "" or item != item.strip() for item in values):
        return False
    if any("\n" in item or "\x00" in item or "\r" in item for item in values):
        return False
    if not config.allowlist:
        return False
    return config.customer_repo == config.pr_repo


def _reject_inputs(manifest: dict) -> None:
    """경로 거부로 읽지 않은 입력의 acquisition을 rejected로 표시한다."""
    for name in ("spec_old", "spec_new", "change_mapping", "customer_checkout", "test_lock", "allowlist"):
        manifest["acquisition"][name] = {"status": "rejected", "reason_code": E_PATH_BOUNDARY}


def _collect_py(root: Path, patterns: list[str]):
    """allowlist와 .py에 맞는 일반 파일만 읽고, 링크면 경계 오류를 낸다."""
    matched = []
    for kind, path, st in iter_checkout(root):
        rel = path.relative_to(root).as_posix()
        if not rel.endswith(".py") or not any(glob_match(rel, pattern) for pattern in patterns):
            continue
        if kind == "symlink" or st.st_nlink > 1:
            raise BoundaryError(E_PATH_BOUNDARY)
        matched.append((rel, path, st))
        if len(matched) > SCAN_MAX_FILES:
            return "too_many", []
    files = []
    for rel, path, st in matched:
        if st.st_size > SCAN_MAX_FILE_BYTES:
            return "too_big", []
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return "unreadable", []
        files.append((rel, text))
    return "ok", files


def _read_capped(path: Path, limit: int) -> bytes:
    """크기 상한 안의 파일만 바이트로 읽고, 넘치면 ValueError를 낸다."""
    data = path.read_bytes()
    if len(data) > limit:
        raise ValueError("too_big")
    return data


def _mark(manifest: dict, name: str, status: str, reason: str | None) -> None:
    """한 stage를 터미널 상태로 기록한다."""
    stamp = _now()
    set_stage(manifest, name, status, stamp, stamp, reason)


def _now() -> str:
    """Asia/Seoul 기준 초 단위 ISO8601 시각을 만든다."""
    return datetime.now(_KST).isoformat(timespec="seconds")


def _write_json(path: Path, payload) -> None:
    """JSON 파일을 UTF-8로 쓰고 권한을 소유자 전용으로 줄인다."""
    text = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    _write_text(path, text)


def _write_text(path: Path, text: str) -> None:
    """텍스트 파일을 덮어쓰고 다른 사용자가 읽지 못하게 한다."""
    path.write_text(text, encoding="utf-8")
    path.chmod(0o600)
