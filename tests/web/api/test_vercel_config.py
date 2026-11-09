# 난이도: Easy
# 학습 키워드: vercel.json, Python Version
"""배포 설정이 공식 FastAPI 경로와 CLI Python 범위를 지키는지 확인한다."""

from __future__ import annotations

import json
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


class VercelConfigTests(unittest.TestCase):
    def test_function_runtime_is_not_a_python_version_string(self) -> None:
        """functions.runtime은 패키지@version만 허용되므로 Python 버전을 넣지 않는다."""
        config = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
        self.assertNotIn("outputDirectory", config)
        self.assertNotIn("builds", config)
        function = config["functions"]["src/patchpilot/web/app.py"]
        self.assertNotIn("runtime", function)
        self.assertEqual(function["maxDuration"], 30)
        for value in config["functions"].values():
            runtime = value.get("runtime")
            if runtime is not None:
                self.assertRegex(runtime, r"^[^@\s]+@.+$")

    def test_web_python_pin_does_not_narrow_the_cli(self) -> None:
        """웹은 .python-version 3.12이고, CLI requires-python은 >=3.11이다."""
        pinned = (ROOT / ".python-version").read_text(encoding="utf-8").strip()
        self.assertEqual(pinned, "3.12")
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(project["project"]["requires-python"], ">=3.11")
        self.assertEqual(project["tool"]["vercel"]["entrypoint"], "patchpilot.web.app:app")


if __name__ == "__main__":
    unittest.main()
