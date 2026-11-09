# 난이도: Mid
# 학습 키워드: CLI, Manifest, Fail Closed
"""CLI run이 정적 단계 뒤에서 고객 실행 없이 멈추는지 확인한다."""

from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from patchpilot.cli.main import main
from patchpilot.collector.evidence import baseline_stages_recorded
from patchpilot.core.orchestrator import RunConfig, execute
from patchpilot.schema.codes import DATA_NOTICE, E_BASELINE_FAIL, E_INTERNAL, E_MODE_UNSUPPORTED, H_UNRESOLVED
from patchpilot.schema.manifest import validate_manifest


DIRECT_CLIENT = (
    "def read_temp():\n"
    "    body = requests.get(\"https://example.test/v1/weather\").json()\n"
    "    return body[\"current_weather\"][\"temperature\"]\n"
)
PARAMETER_CLIENT = "def read_temp(payload):\n    return payload[\"current_weather\"][\"temperature\"]\n"


def write_tree(base: Path, client: str) -> None:
    """합성 spec, mapping, checkout, lock을 임시 디렉터리에 만든다."""
    (base / "specs").mkdir()
    (base / "checkout").mkdir()
    (base / "locks").mkdir()
    old = spec("temperature")
    new = spec("temperature_2m")
    (base / "specs" / "v1.json").write_text(json.dumps(old), encoding="utf-8")
    (base / "specs" / "v2.json").write_text(json.dumps(new), encoding="utf-8")
    (base / "specs" / "map.json").write_text(
        json.dumps(
            {
                "old_pointer": "current_weather.temperature",
                "new_pointer": "current_weather.temperature_2m",
                "type_same": True,
                "unit_same": True,
                "semantic_same": True,
            }
        ),
        encoding="utf-8",
    )
    (base / "checkout" / "client.py").write_text(client, encoding="utf-8")
    (base / "locks" / "tests.lock").write_text("{}\n", encoding="utf-8")


def spec(prop: str) -> dict:
    """한 operation과 inline object만 있는 합성 OpenAPI다."""
    return {
        "openapi": "3.0.3",
        "info": {"title": "demo", "version": "1"},
        "paths": {
            "/v1/weather": {
                "get": {
                    "responses": {
                        "200": {
                            "description": "ok",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "current_weather": {
                                                "type": "object",
                                                "properties": {
                                                    prop: {"type": "number"},
                                                    "windspeed": {"type": "number"},
                                                },
                                            }
                                        },
                                    }
                                }
                            },
                        }
                    }
                }
            }
        },
    }


def config(base: Path, **overrides) -> RunConfig:
    """임시 트리에 대한 기본 run 설정이다."""
    values = dict(
        mode="A",
        spec_old="v1.json",
        spec_new="v2.json",
        change_mapping="map.json",
        specs_root="specs",
        customer_repo="acme/app",
        customer_base_ref="main",
        customer_checkout="checkout",
        test_lock="tests.lock",
        lock_root="locks",
        allowlist=["client.py"],
        pr_repo="acme/app",
        pr_base_branch="main",
        open_pr=False,
        approval_ref=None,
        model_send_consent=True,
        out_dir="out",
        cwd=base,
    )
    values.update(overrides)
    return RunConfig(**values)


class CliRunTests(unittest.TestCase):
    def test_direct_binding_blocks_with_e_internal_not_baseline_fail(self) -> None:
        """직접 JSON 대입을 찾은 뒤의 E_INTERNAL은 baseline 실패가 아니고 프로세스를 시작하지 않는다."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            write_tree(base, DIRECT_CLIENT)
            before = hashlib.sha256((base / "checkout" / "client.py").read_bytes()).hexdigest()
            stdout, stderr = io.StringIO(), io.StringIO()
            code = execute(config(base), stdout, stderr)
            manifest = json.loads((base / "out" / "manifest.json").read_text(encoding="utf-8"))
            report = (base / "out" / "report.md").read_text(encoding="utf-8")
            err = stderr.getvalue()
            out = stdout.getvalue()
            self.assertEqual(code, 30)
            self.assertEqual(validate_manifest(manifest), [])
            self.assertEqual(manifest["outcome"], "error")
            self.assertEqual(manifest["reason_code"], E_INTERNAL)
            self.assertNotEqual(manifest["reason_code"], E_BASELINE_FAIL)
            self.assertNotEqual(manifest["outcome"], "pr_gate_blocked")
            self.assertEqual(manifest["mode"], "A")
            self.assertIsNone(manifest["idem_key"])
            self.assertIsNotNone(manifest["finished_at"])
            self.assertIn("+09:00", manifest["started_at"])
            self.assertIsNone(manifest["inputs"]["base_sha"])
            self.assertIsNotNone(manifest["inputs"]["spec_old_sha256"])
            self.assertEqual(manifest["acquisition"]["base_sha"], {"status": "not_attempted", "reason_code": None})
            self.assertEqual(manifest["acquisition"]["spec_old"]["status"], "acquired")
            self.assertFalse(manifest["tests"]["lock_verified_before"])
            self.assertIsNone(manifest["tests"]["lock_base_sha"])
            self.assertEqual(manifest["tests"]["baseline_v1"], {"result": "not_run", "expected": "pass"})
            self.assertNotEqual(manifest["tests"]["baseline_v1"]["result"], "fail")
            self.assertEqual(manifest["tests"]["unpatched_v2"]["expected"], "fail")
            self.assertEqual(manifest["tests"]["unpatched_v2"]["result"], "not_run")
            self.assertEqual(manifest["pr"]["existence"], "not_attempted")
            self.assertIsNone(manifest["pr"]["url"])
            self.assertIsNone(manifest["patch"])
            by_name = {item["name"]: item for item in manifest["stages"]}
            blocked = by_name["test_baseline_v1"]
            self.assertEqual(blocked["status"], "blocked")
            self.assertEqual(blocked["attempts"], 1)
            self.assertEqual(blocked["reason_code"], E_INTERNAL)
            self.assertIsNotNone(blocked["started_at"])
            self.assertIsNotNone(blocked["ended_at"])
            self.assertIn("+09:00", blocked["started_at"])
            self.assertEqual(by_name["diff_spec"]["status"], "passed")
            self.assertEqual(by_name["scan"]["status"], "passed")
            self.assertIsNone(by_name["scan"]["reason_code"])
            for name in (
                "test_unpatched_v2",
                "patch_generate",
                "patch_validate",
                "test_patched_v2",
                "approval_gate",
                "base_sha_check",
                "pr_evidence_gate",
                "pr_open",
            ):
                stage = by_name[name]
                self.assertEqual(stage["status"], "skipped", name)
                self.assertEqual(stage["attempts"], 0, name)
                self.assertIsNone(stage["started_at"], name)
                self.assertIsNone(stage["ended_at"], name)
            scan = json.loads((base / "out" / "scan-report.json").read_text(encoding="utf-8"))
            self.assertEqual(scan["sites"][0]["binding"], "direct_json_response")
            index = json.loads((base / "out" / "collector-index.json").read_text(encoding="utf-8"))
            self.assertFalse(baseline_stages_recorded(index))
            self.assertEqual(hashlib.sha256((base / "checkout" / "client.py").read_bytes()).hexdigest(), before)
            self.assertFalse((base / "out" / "patch.diff").exists())
            self.assertIn(DATA_NOTICE, report)
            self.assertIn("status=blocked", report)
            self.assertIn("reason=E_INTERNAL", report)
            self.assertIn("result=not_run", report)
            self.assertIn("not E_BASELINE_FAIL", err)
            self.assertIn("not_run", err)
            self.assertIn("No customer process was started", err)
            self.assertIn("Internal error. See report.", out)
            self.assertIn("PR creation not attempted.", out)
            self.assertNotIn("temperature_2m", (base / "checkout" / "client.py").read_text(encoding="utf-8"))

    def test_arbitrary_parameter_checkout_holds_without_blocking_baseline(self) -> None:
        """파라미터 키 접근은 hold이고 baseline stage를 blocked로 만들지 않는다."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            write_tree(base, PARAMETER_CLIENT)
            before = (base / "checkout" / "client.py").read_bytes()
            stdout, stderr = io.StringIO(), io.StringIO()
            code = execute(config(base), stdout, stderr)
            manifest = json.loads((base / "out" / "manifest.json").read_text(encoding="utf-8"))
            by_name = {item["name"]: item for item in manifest["stages"]}
            self.assertEqual(code, 20)
            self.assertEqual(validate_manifest(manifest), [])
            self.assertEqual(manifest["outcome"], "hold")
            self.assertEqual(manifest["reason_code"], H_UNRESOLVED)
            self.assertEqual(manifest["tests"]["baseline_v1"]["result"], "not_run")
            self.assertEqual(by_name["scan"]["status"], "passed")
            self.assertEqual(by_name["scan"]["reason_code"], H_UNRESOLVED)
            self.assertEqual(by_name["test_baseline_v1"]["status"], "skipped")
            self.assertEqual(by_name["test_baseline_v1"]["attempts"], 0)
            self.assertEqual((base / "checkout" / "client.py").read_bytes(), before)

    def test_open_pr_true_does_not_use_pr_gate_before_baseline(self) -> None:
        """PR을 요청해도 검증 시퀀스 전에는 pr_gate_blocked로 바꾸지 않는다."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            write_tree(base, DIRECT_CLIENT)
            code = execute(config(base, open_pr=True, approval_ref="ap-1"), io.StringIO(), io.StringIO())
            manifest = json.loads((base / "out" / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(code, 30)
            self.assertEqual(manifest["outcome"], "error")
            self.assertEqual(manifest["reason_code"], E_INTERNAL)
            self.assertEqual(manifest["pr"]["existence"], "not_attempted")
            self.assertFalse(manifest["approval"]["verified"])
            self.assertIsNone(manifest["approval"]["bound_base_sha"])

    def test_mode_b_and_c_preserve_requested_mode(self) -> None:
        """B와 C는 요청 mode를 유지하고 파일을 읽지 않은 채 error가 된다."""
        for mode in ("B", "C"):
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                write_tree(base, "x = 1\n")
                stdout, stderr = io.StringIO(), io.StringIO()
                code = execute(config(base, mode=mode, spec_old="missing.json"), stdout, stderr)
                manifest = json.loads((base / "out" / "manifest.json").read_text(encoding="utf-8"))
                self.assertEqual(code, 30, mode)
                self.assertEqual(manifest["mode"], mode)
                self.assertEqual(manifest["reason_code"], E_MODE_UNSUPPORTED)
                self.assertTrue(all(item["status"] == "skipped" for item in manifest["stages"]))
                self.assertEqual(manifest["acquisition"]["spec_old"]["status"], "not_attempted")
                self.assertIsNone(manifest["inputs"]["base_sha"])
                self.assertEqual(validate_manifest(manifest), [])

    def test_repo_mismatch_and_absolute_out_dir(self) -> None:
        """repo가 다르면 E_INPUT이고, 절대 out_dir에는 파일을 만들지 않는다."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            write_tree(base, "x = 1\n")
            code = execute(config(base, pr_repo="other/app"), io.StringIO(), io.StringIO())
            manifest = json.loads((base / "out" / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(code, 30)
            self.assertEqual(manifest["reason_code"], "E_INPUT")
            self.assertTrue(all(item["status"] == "skipped" for item in manifest["stages"]))
            unsafe = Path("/tmp/patchpilot-a12-unsafe-out")
            if unsafe.exists():
                self.fail("refusing to clean an unexpected directory")
            stdout, stderr = io.StringIO(), io.StringIO()
            code = execute(config(base, out_dir=str(unsafe)), stdout, stderr)
            self.assertEqual(code, 30)
            self.assertIn("E_OUTPUT_ROOT", stdout.getvalue())
            self.assertFalse(unsafe.exists())

    def test_usage_has_no_manifest(self) -> None:
        """필수 인자가 없으면 exit 2이고 manifest를 만들지 않는다."""
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.getcwd()
            os.chdir(tmp)
            try:
                code = main([])
                self.assertEqual(code, 2)
                self.assertFalse((Path(tmp) / "patchpilot-run" / "manifest.json").exists())
            finally:
                os.chdir(previous)


if __name__ == "__main__":
    unittest.main()
