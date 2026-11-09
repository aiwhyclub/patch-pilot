# 난이도: Easy
# 학습 키워드: Read-only, Renderer, Plain Text
"""렌더러가 manifest를 바꾸지 않고 계약 문장만 돌려주는지 확인한다."""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from patchpilot.schema.codes import DATA_NOTICE, PR_NOT_ATTEMPTED_TEXT, REASON_TEXT
from presentation.renderers.text import render_report, render_stdout


def sample(outcome: str, reason: str | None, existence: str, url=None) -> dict:
    """표시 테스트용 manifest 조각을 만든다."""
    long_id = "a" * 64
    return {
        "outcome": outcome,
        "reason_code": reason,
        "mode": "C",
        "stages": [
            {"name": "diff_spec", "status": "skipped", "attempts": 0},
            {"name": "test_baseline_v1", "status": "blocked", "attempts": 1, "reason_code": "E_RUNTIME_NOT_READY"},
        ],
        "tests": {
            "baseline_v1": {"result": "not_run", "expected": "pass"},
            "unpatched_v2": {"result": "not_run", "expected": "fail"},
            "patched_v2": {"result": "not_run", "expected": "pass"},
        },
        "changes": [{"kind": "field_renamed", "supported": False, "reason": "H_NO_CHANGE", "old_pointer": "a\x1bb", "new_pointer": long_id}],
        "pr": {"existence": existence, "url": url},
        "data_notice": DATA_NOTICE,
    }


class RendererTests(unittest.TestCase):
    def test_stdout_keeps_mode_and_contract_sentences(self) -> None:
        """요청 mode C와 PR 미시도 문장을 그대로 보여 준다."""
        manifest = sample("error", "E_MODE_UNSUPPORTED", "not_attempted")
        before = copy.deepcopy(manifest)
        text = render_stdout(manifest)
        self.assertEqual(manifest, before)
        self.assertIn("outcome: error", text)
        self.assertIn("mode: C", text)
        self.assertIn(REASON_TEXT["E_MODE_UNSUPPORTED"], text)
        self.assertIn(PR_NOT_ATTEMPTED_TEXT, text)
        self.assertNotIn("\x1b", text)
        self.assertNotIn("none", text.lower())

    def test_report_shows_expected_fail_and_full_identifier(self) -> None:
        """예상 v2 실패, not_run, 긴 식별자, 데이터 고지를 축약하지 않는다."""
        manifest = sample("error", "E_RUNTIME_NOT_READY", "unknown")
        report = render_report(manifest)
        self.assertIn("result=not_run expected=fail", report)
        self.assertIn("a" * 64, report)
        self.assertIn(DATA_NOTICE, report)
        self.assertIn("PR creation status unknown. Manual verification required. Do not retry automatically.", report)
        self.assertIn("Blocked stages were not executed: test_baseline_v1", report)
        self.assertIn("status=blocked", report)
        self.assertIn("reason=E_RUNTIME_NOT_READY", report)
        self.assertIn("Runtime prerequisites are not verified. No customer tests were executed.", report)
        self.assertNotIn("Internal error. See report.", report)
        self.assertNotIn("\x1b", report)
        self.assertNotIn("Validated on", report)

    def test_exists_without_url_does_not_invent_one(self) -> None:
        """exists인데 URL이 없으면 URL을 만들어 내지 않는다."""
        text = render_stdout(sample("pr_gate_blocked", "B_EVIDENCE_GATE", "exists", None))
        self.assertIn("no verified URL", text)
        self.assertNotIn("https://", text)

    def test_unknown_code_uses_fallback(self) -> None:
        """표에 없는 코드는 미정의 안내로만 보여 준다."""
        text = render_stdout(sample("error", "E_NOT_A_REAL_CODE", "absent"))
        self.assertIn("Unknown status code. Manual review needed.", text)
        self.assertIn("PR not created (confirmed absent).", text)

    def test_pr_existence_four_states_are_explicit(self) -> None:
        """exists, absent, unknown, not_attempted를 서로 다른 문장으로 보여 준다."""
        exists = render_stdout(sample("error", "E_RUNTIME_NOT_READY", "exists", "https://example.test/pull/1"))
        self.assertIn("Runtime prerequisites are not verified. No customer tests were executed.", exists)
        absent = render_stdout(sample("error", "E_PR_CREATE_FAILED", "absent"))
        unknown = render_stdout(sample("error", "E_PR_RESULT_UNKNOWN", "unknown"))
        skipped = render_stdout(sample("hold", "H_UNRESOLVED", "not_attempted"))
        self.assertIn("https://example.test/pull/1", exists)
        self.assertIn("PR not created (confirmed absent).", absent)
        self.assertIn("PR creation status unknown. Manual verification required. Do not retry automatically.", unknown)
        self.assertIn("PR creation not attempted.", skipped)

    def test_renderer_source_does_not_import_cli_or_core(self) -> None:
        """표시 모듈은 CLI와 core orchestration을 가져오지 않는다."""
        source = (ROOT / "presentation/renderers/text.py").read_text(encoding="utf-8")
        self.assertNotIn("patchpilot.cli", source)
        self.assertNotIn("patchpilot.core", source)
        self.assertNotIn("subprocess", source)


if __name__ == "__main__":
    unittest.main()
