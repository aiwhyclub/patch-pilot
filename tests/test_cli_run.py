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
from patchpilot.core.orchestrator import RunConfig, execute
from patchpilot.schema.codes import DATA_NOTICE, E_INTERNAL, E_MODE_UNSUPPORTED
from patchpilot.schema.manifest import validate_manifest


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
    def test_supported_scan_blocks_before_customer_execution(self) -> None:
        """직접 접근을 찾은 뒤 baseline은 blocked이고 고객 파일은 그대로다."""
        client = 'def read_temp(payload):\n    return payload["current_weather"]["temperature"]\n'
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            write_tree(base, client)
            before = hashlib.sha256((base / "checkout" / "client.py").read_bytes()).hexdigest()
            stdout, stderr = io.StringIO(), io.StringIO()
            code = execute(config(base), stdout, stderr)
            manifest = json.loads((base / "out" / "manifest.json").read_text(encoding="utf-8"))
            report = (base / "out" / "report.md").read_text(encoding="utf-8")
            self.assertEqual(code, 30)
            self.assertEqual(validate_manifest(manifest), [])
            self.assertEqual(manifest["outcome"], "error")
            self.assertEqual(manifest["reason_code"], E_INTERNAL)
            self.assertEqual(manifest["mode"], "A")
            self.assertIsNone(manifest["inputs"]["base_sha"])
            self.assertEqual(manifest["acquisition"]["base_sha"]["status"], "not_attempted")
            self.assertFalse(manifest["tests"]["lock_verified_before"])
            self.assertEqual(manifest["tests"]["baseline_v1"], {"result": "not_run", "expected": "pass"})
            self.assertEqual(manifest["tests"]["unpatched_v2"]["expected"], "fail")
            self.assertEqual(manifest["pr"]["existence"], "not_attempted")
            self.assertIsNone(manifest["patch"])
            stages = {item["name"]: item["status"] for item in manifest["stages"]}
            self.assertEqual(stages["diff_spec"], "passed")
            self.assertEqual(stages["scan"], "passed")
            self.assertEqual(stages["test_baseline_v1"], "blocked")
            self.assertEqual(stages["patch_generate"], "skipped")
            self.assertEqual(stages["pr_open"], "skipped")
            self.assertEqual(hashlib.sha256((base / "checkout" / "client.py").read_bytes()).hexdigest(), before)
            self.assertFalse((base / "out" / "patch.diff").exists())
            self.assertIn(DATA_NOTICE, report)
            self.assertIn("BLOCKED", stderr.getvalue())
            self.assertIn("Internal error. See report.", stdout.getvalue())
            self.assertNotIn("temperature_2m", (base / "checkout" / "client.py").read_text(encoding="utf-8"))

    def test_mode_c_preserves_mode_and_skips_reads(self) -> None:
        """B/C는 요청 mode를 유지하고 파일을 읽지 않은 채 error가 된다."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            write_tree(base, "x = 1\n")
            stdout, stderr = io.StringIO(), io.StringIO()
            code = execute(config(base, mode="C", spec_old="missing.json"), stdout, stderr)
            manifest = json.loads((base / "out" / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(code, 30)
            self.assertEqual(manifest["mode"], "C")
            self.assertEqual(manifest["reason_code"], E_MODE_UNSUPPORTED)
            self.assertTrue(all(item["status"] == "skipped" for item in manifest["stages"]))
            self.assertEqual(manifest["acquisition"]["spec_old"]["status"], "not_attempted")
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
