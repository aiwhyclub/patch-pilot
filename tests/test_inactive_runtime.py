# 난이도: Mid
# 학습 키워드: Inactive Gate, Pure Function, Fail Closed
"""네트워크와 고객 프로세스를 열지 않는 T8 판정."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from patchpilot.broker.adapter import send_gate
from patchpilot.collector.evidence import (
    baseline_stages_recorded,
    file_record,
    index_rehash_decision,
    plan_lock_snapshots,
)
from patchpilot.core.approval import execution_binding_decision
from patchpilot.core.base_sha import adapter_block_cause, readonly_adapter_connected
from patchpilot.pr.ledger import crash_view, replay_lines
from patchpilot.pr.publisher import publisher_decision
from patchpilot.runner.supervisor import (
    classify_worker_fixture,
    decide_dispatch,
    lock_snapshot,
    lock_still_same,
    readiness_from_constants,
)
from patchpilot.schema.codes import (
    B_EVIDENCE_GATE,
    E_BASELINE_FAIL,
    E_INTERNAL,
    E_NO_REPRO,
    E_PATCH_TEST_FAIL,
    E_PR_RESULT_UNKNOWN,
    E_RUNTIME_NOT_READY,
    E_TEST_TAMPERED,
    E_WORKER_RESULT,
    H_MODEL_SEND_BLOCKED,
)
from patchpilot.schema.manifest import new_manifest, set_stage, validate_manifest


LINE = '{"ok":true,"values":[1],"stderr_digest":"' + ("a" * 64) + '"}\n'


class DispatchTests(unittest.TestCase):
    def test_constants_block_once_without_recording_success(self) -> None:
        decision = readiness_from_constants()
        self.assertFalse(decision["ready"])
        self.assertFalse(decision["dispatch"])
        self.assertFalse(decision["worker_invoked"])
        self.assertFalse(decision["recorded_success"])
        self.assertEqual(decision["attempts"], 1)
        self.assertEqual(decision["test_result"], "not_run")
        self.assertEqual(decision["reason_code"], E_RUNTIME_NOT_READY)
        self.assertGreaterEqual(len(decision["causes"]), 3)

    def test_injected_ready_flags_still_do_not_dispatch(self) -> None:
        decision = decide_dispatch(
            {
                "container_isolation_proven": True,
                "resource_enforcement_proven": True,
                "customer_execution_approved": True,
            }
        )
        self.assertTrue(decision["ready"])
        self.assertFalse(decision["dispatch"])
        self.assertFalse(decision["worker_invoked"])
        self.assertFalse(decision["recorded_success"])
        self.assertEqual(decision["attempts"], 0)
        self.assertEqual(decision["test_result"], "not_run")

    def test_missing_line_is_not_run_and_matching_fixture_is_not_product_success(self) -> None:
        missing = classify_worker_fixture("baseline_v1", [1], None, lock_same=True)
        self.assertEqual(missing["result"], "not_run")
        self.assertEqual(missing["reason_code"], E_RUNTIME_NOT_READY)
        self.assertFalse(missing["recorded_success"])
        matched = classify_worker_fixture("baseline_v1", [1], LINE, lock_same=True)
        self.assertEqual(matched["result"], "pass")
        self.assertFalse(matched["recorded_success"])
        self.assertFalse(matched["worker_invoked"])
        failed = classify_worker_fixture("baseline_v1", [2], LINE, lock_same=True)
        self.assertEqual(failed["reason_code"], E_BASELINE_FAIL)
        self.assertFalse(failed["recorded_success"])

    def test_stage_expectations_and_tamper_stay_not_product_success(self) -> None:
        reproduced = classify_worker_fixture("unpatched_v2", [1], LINE, lock_same=True)
        self.assertEqual(reproduced["reason_code"], E_NO_REPRO)
        broken = classify_worker_fixture("unpatched_v2", [2], LINE, lock_same=True)
        self.assertEqual(broken["result"], "fail")
        self.assertIsNone(broken["reason_code"])
        patched = classify_worker_fixture("patched_v2", [2], LINE, lock_same=True)
        self.assertEqual(patched["reason_code"], E_PATCH_TEST_FAIL)
        bad = classify_worker_fixture("patched_v2", [1], "{", lock_same=True)
        self.assertEqual(bad["reason_code"], E_WORKER_RESULT)
        moved = classify_worker_fixture("patched_v2", [1], LINE, lock_same=False)
        self.assertEqual(moved["result"], "not_run")
        self.assertEqual(moved["reason_code"], E_TEST_TAMPERED)
        for item in (reproduced, broken, patched, bad, moved):
            self.assertFalse(item["recorded_success"])

    def test_lock_snapshot_requires_equal_hash_and_no_worker_write(self) -> None:
        before = lock_snapshot("lock.json", "ab", None)
        self.assertFalse(before["verified"])
        after = lock_snapshot("lock.json", "ab", "ab")
        self.assertFalse(lock_still_same(before, after))
        same = lock_snapshot("lock.json", "ab", None)
        self.assertTrue(lock_still_same(before, same))


class BindingAndAdapterTests(unittest.TestCase):
    def test_method_path_is_not_an_approval_record(self) -> None:
        missing = execution_binding_decision(None, customer_repo="acme/app", base_branch="main")
        self.assertFalse(missing["allowed"])
        self.assertFalse(missing["network"])
        self.assertEqual(missing["reason_code"], E_RUNTIME_NOT_READY)
        method_path = execution_binding_decision(
            {"method": "get", "path": "/v1/weather"},
            customer_repo="acme/app",
            base_branch="main",
        )
        self.assertFalse(method_path["shape_ok"])
        self.assertFalse(method_path["network"])
        self.assertIn("provider_identity", method_path["cause"])

    def test_matching_shape_still_keeps_network_off(self) -> None:
        record = {
            "provider_identity": "unset-provider",
            "api_identity": "unset-api",
            "customer_repo": "acme/app",
            "base_branch": "main",
            "model_send_consent": True,
        }
        decision = execution_binding_decision(record, customer_repo="acme/app", base_branch="main")
        self.assertTrue(decision["shape_ok"])
        self.assertFalse(decision["allowed"])
        self.assertFalse(decision["network"])
        self.assertEqual(decision["reason_code"], E_RUNTIME_NOT_READY)
        mismatch = execution_binding_decision(record, customer_repo="acme/other", base_branch="main")
        self.assertFalse(mismatch["shape_ok"])
        self.assertFalse(mismatch["network"])

    def test_base_sha_adapter_reports_disconnected(self) -> None:
        self.assertFalse(readonly_adapter_connected())
        cause = adapter_block_cause()
        self.assertFalse(cause["connected"])
        self.assertFalse(cause["network"])
        self.assertFalse(cause["invokes_git"])
        self.assertEqual(cause["reason_code"], E_RUNTIME_NOT_READY)


class CollectorAndLedgerTests(unittest.TestCase):
    def test_planned_rows_are_not_finished_and_rehash_is_not_a_gate_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lock.json"
            path.write_text("{}\n", encoding="utf-8")
            rows = plan_lock_snapshots(file_record(path, "test_baseline_v1", "run-1"))
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(item["executed"] is False for item in rows))
        self.assertFalse(baseline_stages_recorded(rows))
        finished = [{**item, "executed": True} for item in rows]
        self.assertTrue(baseline_stages_recorded(finished))
        self.assertEqual(index_rehash_decision(matches=True, sequence_finished=False), E_RUNTIME_NOT_READY)
        self.assertIsNone(index_rehash_decision(matches=True, sequence_finished=True))
        self.assertEqual(index_rehash_decision(matches=False, sequence_finished=True), B_EVIDENCE_GATE)

    def test_crash_points_keep_lock_and_do_not_reissue(self) -> None:
        pending = crash_view("pending_not_flushed")
        self.assertTrue(pending["keep_lock"])
        self.assertFalse(pending["auto_reissue"])
        self.assertFalse(pending["publish"])
        self.assertFalse(pending["durable_proven"])
        self.assertEqual(pending["reason_code"], E_RUNTIME_NOT_READY)
        unknown = crash_view("after_remote_unknown")
        self.assertEqual(unknown["reason_code"], E_PR_RESULT_UNKNOWN)
        self.assertFalse(unknown["auto_reissue"])
        self.assertEqual(crash_view("not-a-point")["reason_code"], E_INTERNAL)
        self.assertFalse(crash_view("before_lock")["keep_lock"])

    def test_replay_rejects_duplicate_pending_without_network(self) -> None:
        line = json.dumps(
            {
                "run_id": "run-1",
                "idem_key": "k",
                "repo": "acme/app",
                "base_branch": "main",
                "diff_sha256": "ab",
                "state": "pending",
            }
        )
        once = replay_lines([line])
        self.assertTrue(once["ok"])
        self.assertTrue(once["keep_lock"])
        self.assertFalse(once["auto_reissue"])
        self.assertFalse(once["network"])
        self.assertFalse(once["durable_proven"])
        twice = replay_lines([line, line])
        self.assertFalse(twice["ok"])
        self.assertEqual(twice["reason_code"], E_RUNTIME_NOT_READY)
        self.assertFalse(twice["publish"])


class PublisherAndBrokerTests(unittest.TestCase):
    def test_complete_gates_do_not_call_or_record_success(self) -> None:
        decision = publisher_decision({name: True for name in (
            "ledger_durable",
            "approval_verified",
            "evidence_gate_passed",
            "sha_checked_twice",
            "customer_pr_approved",
            "provider_binding_ok",
        )})
        self.assertFalse(decision["call"])
        self.assertFalse(decision["network"])
        self.assertEqual(decision["existence"], "not_attempted")
        self.assertIsNone(decision["url"])
        self.assertFalse(decision["recorded_success"])
        self.assertEqual(decision["reason_code"], E_RUNTIME_NOT_READY)
        self.assertIn("customer_pr_approved_constant", decision["missing"])

    def test_unset_provider_blocks_before_consent_reason(self) -> None:
        unset = send_gate(consent=False, excerpt=None, binding=None)
        self.assertEqual(unset["reason_code"], E_RUNTIME_NOT_READY)
        self.assertFalse(unset["network"])
        self.assertIsNone(unset["diff"])
        refused = send_gate(
            consent=False,
            excerpt="temperature",
            binding={"provider_identity": "unset-provider", "api_identity": "unset-api", "model_send_consent": False},
        )
        self.assertEqual(refused["reason_code"], H_MODEL_SEND_BLOCKED)
        self.assertFalse(refused["sent"])
        self.assertIsNone(refused["diff"])
        approved_shape = send_gate(
            consent=True,
            excerpt="temperature",
            binding={"provider_identity": "unset-provider", "api_identity": "unset-api", "model_send_consent": True},
        )
        self.assertFalse(approved_shape["network"])
        self.assertFalse(approved_shape["sent"])
        self.assertIsNone(approved_shape["diff"])


class ManifestRuntimeTests(unittest.TestCase):
    def test_runtime_reason_rejects_a_failed_test_result(self) -> None:
        manifest = new_manifest(
            {
                "mode": "A",
                "customer_repo": "acme/app",
                "spec_old_sha256": "a" * 64,
                "mapping_sha256": "b" * 64,
                "base_branch": "main",
                "base_sha": None,
                "allowlist": [],
                "model_send_consent": False,
                "open_pr": False,
            },
            "run",
            "2026-11-09T00:00:00.000+09:00",
        )
        manifest["finished_at"] = "2026-11-09T00:00:01.000+09:00"
        manifest["outcome"] = "error"
        manifest["reason_code"] = E_RUNTIME_NOT_READY
        set_stage(
            manifest,
            "test_baseline_v1",
            "blocked",
            "2026-11-09T00:00:00.000+09:00",
            "2026-11-09T00:00:01.000+09:00",
            E_RUNTIME_NOT_READY,
        )
        self.assertEqual(validate_manifest(manifest), [])
        manifest["tests"]["baseline_v1"]["result"] = "fail"
        self.assertIn("baseline_v1 not_run", validate_manifest(manifest))


if __name__ == "__main__":
    unittest.main()
