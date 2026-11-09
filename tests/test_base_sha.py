# 난이도: Mid
# 학습 키워드: SHA-256, Manifest, Fail Closed
"""base_sha는 주입된 관찰만 판정하고, 성공 manifest의 null을 거부한다."""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from patchpilot.core.base_sha import (
    mismatch_reason,
    observe_injected,
    readonly_adapter_connected,
    success_sha_ok,
)
from patchpilot.schema.codes import H_BASE_MOVED
from patchpilot.schema.manifest import new_manifest, set_stage, validate_manifest


SHA_A = "a" * 40
SHA_B = "b" * 40


def _manifest(outcome: str, status: str, sha: str | None) -> dict:
    """base_sha만 바꾼 계약 manifest를 만든다."""
    manifest = new_manifest(
        {
            "mode": "A",
            "spec_old": "v1.json",
            "spec_new": "v2.json",
            "change_mapping": "map.json",
            "specs_root": "specs",
            "customer_repo": "acme/app",
            "customer_base_ref": "main",
            "customer_checkout": "checkout",
            "test_lock": "tests.lock",
            "lock_root": "locks",
            "allowlist": ["client.py"],
            "pr_target": {"repo": "acme/app", "base_branch": "main"},
            "open_pr": False,
            "approval_ref": None,
            "model_send_consent": False,
            "out_dir": "out",
            "base_sha": sha,
            "spec_old_sha256": None,
            "spec_new_sha256": None,
            "change_mapping_sha256": None,
        },
        "run",
        "2026-11-09T12:00:00+09:00",
    )
    manifest["outcome"] = outcome
    manifest["reason_code"] = None if outcome in ("draft_pr_opened", "patch_only") else "E_INTERNAL"
    manifest["finished_at"] = "2026-11-09T12:01:00+09:00"
    manifest["acquisition"]["base_sha"] = {"status": status, "reason_code": None}
    return manifest


class BaseShaTests(unittest.TestCase):
    def test_adapter_is_not_connected_and_source_has_no_git_invocation(self) -> None:
        """읽기 전용 SHA adapter는 꺼져 있고 git 명령을 만들지 않는다."""
        source = (ROOT / "src/patchpilot/core/base_sha.py").read_text(encoding="utf-8")
        self.assertFalse(readonly_adapter_connected())
        self.assertNotIn("subprocess", source)
        self.assertNotIn("os.system", source)
        self.assertNotIn("rev-" + "parse", source)
        self.assertNotIn("GIT_", source)

    def test_not_attempted_null_is_not_terminal_success(self) -> None:
        """획득 전 null은 최종 성공 조건이 아니다."""
        first = observe_injected(None)
        second = observe_injected(None)
        self.assertEqual(first["status"], "not_attempted")
        self.assertIsNone(first["base_sha"])
        self.assertIsNone(mismatch_reason(first, second))
        self.assertFalse(success_sha_ok(first, second))
        manifest = _manifest("error", "not_attempted", None)
        self.assertEqual(validate_manifest(manifest), [])
        success = _manifest("draft_pr_opened", "not_attempted", None)
        self.assertIn("base_sha success", validate_manifest(success))
        patch_only = _manifest("patch_only", "not_attempted", None)
        self.assertIn("base_sha success", validate_manifest(patch_only))

    def test_injected_mismatch_is_h_base_moved(self) -> None:
        """두 주입 SHA가 다르면 H_BASE_MOVED이고 성공이 아니다."""
        first = observe_injected({"status": "acquired", "base_sha": SHA_A})
        second = observe_injected({"status": "acquired", "base_sha": SHA_B})
        self.assertEqual(mismatch_reason(first, second), H_BASE_MOVED)
        self.assertFalse(success_sha_ok(first, second))
        same = observe_injected({"status": "acquired", "base_sha": SHA_A})
        self.assertIsNone(mismatch_reason(first, same))
        self.assertTrue(success_sha_ok(first, same))

    def test_injected_command_text_is_not_a_sha(self) -> None:
        """git -c 나 hook 경로처럼 보이는 문자열은 SHA로 받지 않고 실행하지 않는다."""
        observed = observe_injected(
            {
                "status": "acquired",
                "base_sha": "git -c core.hooksPath=/tmp/hook",
                "command": "git -c core.hooksPath=/tmp " + "rev-" + "parse HEAD",
            }
        )
        self.assertEqual(observed["status"], "failed")
        self.assertIsNone(observed["base_sha"])
        self.assertFalse(success_sha_ok(observed, observed))

    def test_success_manifest_requires_acquired_sha_and_second_check(self) -> None:
        """draft_pr_opened는 acquired SHA와 통과한 base_sha_check가 있어야 한다."""
        manifest = _manifest("draft_pr_opened", "acquired", SHA_A)
        self.assertIn("base_sha check", validate_manifest(manifest))
        manifest["tests"]["lock_base_sha"] = SHA_A
        set_stage(
            manifest,
            "base_sha_check",
            "passed",
            "2026-11-09T12:00:30+09:00",
            "2026-11-09T12:00:31+09:00",
            None,
        )
        manifest["stages"][manifest["stage_order"].index("base_sha_check")]["attempts"] = 2
        self.assertEqual(validate_manifest(manifest), [])
        moved = copy.deepcopy(manifest)
        moved["inputs"]["base_sha"] = SHA_B
        self.assertIn("lock_base_sha", validate_manifest(moved))


if __name__ == "__main__":
    unittest.main()
