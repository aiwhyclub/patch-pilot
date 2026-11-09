# 난이도: Mid
# 학습 키워드: unittest, Gate, Ledger, Redaction
"""승인, 증거, worker 형식, ledger, 차단 adapter를 함수 단위로 확인한다."""

from __future__ import annotations

import hashlib
import inspect
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from patchpilot.broker.adapter import ObviousFakeModel, accept_model_result, model_send_decision, send_to_provider
from patchpilot.collector.evidence import file_record, rehash_matches
from patchpilot.core.capability import capabilities_proven, enforce_unproven_block, full_success_allowed
from patchpilot.core.paths import BoundaryError, glob_match, prepare_out_dir, require_real_file
from patchpilot.pr.ledger import acquire_lock, append_record, pr_stage_blocked, reconcile
from patchpilot.pr.policy import approval_decision, evidence_gate_decision, idem_key, may_auto_reissue, pr_match
from patchpilot.runner.worker_result import assert_expected, parse_worker_line
from patchpilot.schema.acceptance import AC_IDS, all_not_run
from patchpilot.schema.codes import (
    B_BINDING_MISMATCH,
    B_EVIDENCE_GATE,
    B_NO_APPROVAL,
    DATA_NOTICE,
    E_PR_RESULT_UNKNOWN,
    E_WORKER_RESULT,
    H_MODEL_SEND_BLOCKED,
    H_REUSED_PR_MISMATCH,
)
from patchpilot.schema.limits import STAGE_LIMITS, within_log_budget
from patchpilot.schema.redact import contains_secret, mask_text


class GateTests(unittest.TestCase):
    def test_capabilities_block_success_outcomes(self) -> None:
        """미증명 능력으로는 최종 성공 outcome을 유지하지 않는다."""
        self.assertFalse(capabilities_proven())
        self.assertEqual(enforce_unproven_block("draft_pr_opened"), "error")
        self.assertEqual(enforce_unproven_block("patch_only"), "error")
        self.assertEqual(enforce_unproven_block("hold"), "hold")
        flags = {name: True for name in (
            "acquisition_complete",
            "evidence_gate_passed",
            "supported_change",
            "patch_validated",
            "locks_match",
            "sequence_pass_fail_pass",
            "approval_verified",
            "sha_checked_twice",
            "pr_lookup_matches",
            "secrets_clear",
            "customer_equals_target",
            "customer_execution_approved",
            "model_endpoint_approved",
            "customer_pr_approved",
            "resource_enforcement_proven",
            "ledger_durability_proven",
            "container_isolation_proven",
        )}
        self.assertTrue(full_success_allowed(flags))
        flags["customer_execution_approved"] = False
        self.assertFalse(full_success_allowed(flags))

    def test_acceptance_ids_stay_not_run(self) -> None:
        """제품 AC 24개는 코드 안에서도 NOT_RUN으로 남아 있다."""
        self.assertEqual(len(AC_IDS), 24)
        self.assertTrue(all_not_run())
        self.assertNotIn("Validated on", DATA_NOTICE)

    def test_model_adapter_is_obviously_fake_and_closed(self) -> None:
        """가짜 adapter는 diff를 만들지 않고, 전송 함수는 네트워크 표시를 하지 않는다."""
        fake = ObviousFakeModel().propose_diff("payload['temperature']")
        self.assertTrue(fake["fake"])
        self.assertIsNone(fake["diff"])
        self.assertFalse(accept_model_result(fake, endpoint_approved=True))
        self.assertFalse(accept_model_result({"is_real_provider": True, "diff": "x"}, endpoint_approved=False))
        self.assertEqual(model_send_decision(consent=False, excerpt="safe", endpoint_approved=True), H_MODEL_SEND_BLOCKED)
        self.assertEqual(model_send_decision(consent=True, excerpt="token=AKIAFAKEFAKEFAKEFAKE", endpoint_approved=True), H_MODEL_SEND_BLOCKED)
        self.assertIsNone(model_send_decision(consent=True, excerpt="safe line", endpoint_approved=True))
        sent = send_to_provider("safe line", True)
        self.assertFalse(sent["network"])
        self.assertFalse(sent["sent"])
        self.assertIsNone(sent["diff"])

    def test_worker_bounds_and_assertion_ignore_exit_code(self) -> None:
        """worker JSON 한계와 기대값 비교는 exit code 인자 없이 동작한다."""
        ok, err = parse_worker_line('{"ok": true, "values": [21.5], "stderr_digest": "abc"}\n')
        self.assertIsNone(err)
        self.assertTrue(assert_expected([21.5], ok))
        self.assertFalse(assert_expected([1], ok))
        self.assertFalse(assert_expected([21.5], {"ok": False, "values": [21.5], "stderr_digest": "abc"}))
        self.assertNotIn("exit", inspect.signature(assert_expected).parameters)
        values = [1] * 33
        raw = '{"ok": true, "values": ' + str(values).replace(" ", "") + ', "stderr_digest": "abc"}'
        _bad, code = parse_worker_line(raw)
        self.assertEqual(code, E_WORKER_RESULT)
        _bad, code = parse_worker_line('{"ok": true, "values": [], "stderr_digest": "abc", "exit": 0}\n')
        self.assertEqual(code, E_WORKER_RESULT)

    def test_pr_policy_and_ledger_do_not_reissue(self) -> None:
        """불일치 PR과 unknown 상태는 자동 재발행하지 않고 lock을 유지한다."""
        key = idem_key("acme/app", "acme/app", "main", "abc", "spec", "diff")
        manual = hashlib.sha256(b"\0".join([b"acme/app", b"acme/app", b"main", b"abc", b"spec", b"diff"])).hexdigest()
        self.assertEqual(key, manual)
        target = {"repo": "acme/app", "base_branch": "main", "base_sha": "abc", "diff_sha256": "diff"}
        self.assertEqual(approval_decision(open_pr=True, binding=None, target=target), B_NO_APPROVAL)
        bad = {"repo": "other/app", "base_branch": "main", "base_sha": "abc", "diff_sha256": "diff", "operation": "open_draft_pr"}
        self.assertEqual(approval_decision(open_pr=True, binding=bad, target=target), B_BINDING_MISMATCH)
        self.assertEqual(evidence_gate_decision(hashes_match=False, sequence_ok=True), B_EVIDENCE_GATE)
        remote = {"existence": "exists", "repo": "acme/app", "base_branch": "main", "base_sha": "zzz", "head_diff_sha256": "diff", "draft": True, "merged": False, "approval_ref": "ap"}
        self.assertEqual(pr_match(remote, {**target, "approval_ref": "ap"}), H_REUSED_PR_MISMATCH)
        self.assertEqual(pr_match({"existence": "unknown"}, target), E_PR_RESULT_UNKNOWN)
        self.assertFalse(may_auto_reissue("unknown"))
        self.assertTrue(pr_stage_blocked())
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            self.assertTrue(acquire_lock(base / "lock"))
            self.assertFalse(acquire_lock(base / "lock"))
            append_record(base / "ledger.jsonl", {"state": "pending", "run_id": "r"})
            append_record(base / "ledger.jsonl", {"state": "pending", "run_id": "s"})
            lines = (base / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 2)
            self.assertIn("r", lines[0])
        unknown = reconcile("unknown")
        self.assertTrue(unknown["keep_lock"])
        self.assertFalse(unknown["auto_reissue"])

    def test_evidence_rehash_detects_change(self) -> None:
        """기록 뒤 파일이 바뀌면 재해시가 실패한다."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "note.txt"
            path.write_text("one", encoding="utf-8")
            record = file_record(path, "scan", "run")
            self.assertTrue(rehash_matches([record]))
            path.write_text("two", encoding="utf-8")
            self.assertFalse(rehash_matches([record]))

    def test_secret_mask_and_limits(self) -> None:
        """가짜 비밀은 가리고, 계약 시간표와 로그 상한은 문서 값과 같다."""
        self.assertTrue(contains_secret("aws AKIAFAKEFAKEFAKEFAKE key"))
        self.assertTrue(contains_secret("password=supersecretvalue"))
        self.assertTrue(contains_secret("api_key=supersecretvalue"))
        self.assertEqual(
            model_send_decision(consent=True, excerpt="password=supersecretvalue", endpoint_approved=True),
            H_MODEL_SEND_BLOCKED,
        )
        self.assertEqual(mask_text("AKIAFAKEFAKEFAKEFAKE"), "[REDACTED]")
        self.assertEqual(STAGE_LIMITS["pr_evidence_gate"], {"timeout_seconds": 30, "max_attempts": 1})
        self.assertEqual(STAGE_LIMITS["patch_generate"]["max_attempts"], 3)
        self.assertEqual(STAGE_LIMITS["test_baseline_v1"]["timeout_seconds"], 300)
        self.assertTrue(within_log_budget(100, 200))
        self.assertFalse(within_log_budget(2 * 1024 * 1024, 200))

    def test_path_boundary_and_glob(self) -> None:
        """절대경로, symlink, hardlink, 겹치는 out_dir, 느슨한 glob을 거부한다."""
        self.assertTrue(glob_match("client.py", "client.py"))
        self.assertFalse(glob_match("pkg/client.py", "client.py"))
        self.assertFalse(glob_match("pkg/client.py", "*.py"))
        self.assertTrue(glob_match("pkg/sub/a.py", "**/*.py"))
        self.assertTrue(glob_match("client.py", "**/*.py"))
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "specs").mkdir()
            (base / "specs" / "v1.json").write_text("{}", encoding="utf-8")
            (base / "specs" / "link.json").symlink_to(base / "specs" / "v1.json")
            (base / "specs" / "hard.json").write_text("{}", encoding="utf-8")
            (base / "specs" / "hard.json").unlink()
            (base / "specs" / "hard.json").write_text("{}", encoding="utf-8")
            other = base / "specs" / "hard-target.json"
            other.write_text("{}", encoding="utf-8")
            other.unlink()
            target = base / "specs" / "v1.json"
            link = base / "specs" / "hard.json"
            link.write_text("x", encoding="utf-8")
            twin = base / "specs" / "twin.json"
            twin.write_text("x", encoding="utf-8")
            twin.unlink()
            import os
            os.link(link, base / "specs" / "twin.json")
            with self.assertRaises(BoundaryError):
                require_real_file(base / "specs", "link.json")
            with self.assertRaises(BoundaryError):
                require_real_file(base / "specs", "twin.json")
            with self.assertRaises(BoundaryError):
                prepare_out_dir(base, "specs", [base / "specs"])
            with self.assertRaises(BoundaryError):
                prepare_out_dir(base, "../out", [base / "specs"])


class SourceBoundaryTests(unittest.TestCase):
    def test_runtime_modules_have_no_execution_imports(self) -> None:
        """runner, broker, publisher 소스에 실행·네트워크 호출 구문이 없다."""
        paths = [
            ROOT / "src/patchpilot/runner/guard.py",
            ROOT / "src/patchpilot/runner/worker_result.py",
            ROOT / "src/patchpilot/broker/adapter.py",
            ROOT / "src/patchpilot/pr/publisher.py",
        ]
        banned = ("subprocess", "urllib", "requests", "http.client", "import socket", "eval(", "exec(", "os.system")
        for path in paths:
            text = path.read_text(encoding="utf-8")
            for word in banned:
                self.assertNotIn(word, text, path.name)
        self.assertNotIn("temperature_2m", (ROOT / "src/patchpilot/broker/adapter.py").read_text(encoding="utf-8"))

    def test_cli_and_orchestrator_do_not_call_worker_or_publisher(self) -> None:
        """테스트와 CLI 소스는 worker와 고객 PR publisher를 호출하지 않는다."""
        calls = ("publish_draft_" + "pr(", "run_customer_" + "worker(", "subprocess.", "rev-" + "parse")
        paths = [
            ROOT / "src/patchpilot/cli/main.py",
            ROOT / "src/patchpilot/core/orchestrator.py",
            ROOT / "src/patchpilot/core/base_sha.py",
            ROOT / "tests/test_cli_run.py",
            ROOT / "tests/test_classify_scan_patch.py",
            ROOT / "tests/test_base_sha.py",
            ROOT / "tests/test_inactive_runtime.py",
            ROOT / "src/patchpilot/runner/supervisor.py",
            ROOT / "src/patchpilot/core/approval.py",
            ROOT / "tests/presentation/test_renderers.py",
            ROOT / "src/patchpilot/web/analyze.py",
            ROOT / "src/patchpilot/web/http.py",
            ROOT / "src/patchpilot/web/app.py",
            ROOT / "src/patchpilot/web/samples.py",
            ROOT / "src/patchpilot/web/local.py",
            ROOT / "src/app.py",
        ]
        for path in paths:
            text = path.read_text(encoding="utf-8")
            for call in calls:
                self.assertNotIn(call, text, path.name)


if __name__ == "__main__":
    unittest.main()
