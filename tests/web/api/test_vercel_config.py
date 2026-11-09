# 난이도: Easy
# 학습 키워드: vercel.json, Python entrypoint
"""배포 설정이 공식 entrypoint 탐색과 public CDN, Function 묶음을 따르는지 확인한다."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def resolve_module_attr(work: Path, value: str) -> tuple[str, str] | None:
    """packages/python/src/entrypoint.ts resolveModuleAttrEntrypoint와 같다.

    점은 슬래시가 되고, 저장소 루트의 ``<module>.py`` 또는
    ``<module>/__init__.py``만 본다. ``src/``를 따로 앞에 붙이지 않는다.
    """
    match = re.search(r"([A-Za-z_][\w.]*)\s*:\s*([A-Za-z_][\w]*)", value)
    if match is None:
        return None
    module_path, variable_name = match.group(1), match.group(2)
    relative = module_path.replace(".", "/")
    for candidate in (f"{relative}.py", f"{relative}/__init__.py"):
        if (work / candidate).is_file():
            return candidate, variable_name
    return None


def entrypoint_to_module(entrypoint: str) -> str:
    """entrypointToModule: 경로 구분자를 점으로 바꾸고 .py와 __init__을 뺀다."""
    text = entrypoint.replace("\\", "/")
    if text.lower().endswith(".py"):
        text = text[:-3]
    if text.lower().endswith("/__init__"):
        text = text[: -len("/__init__")]
    return text.replace("/", ".")


def matches_vercel_glob(relative: str, pattern: str) -> bool:
    """vercel.json의 ``{a/**,b/**}`` 제외 패턴이 이 상대 경로를 묶는지 본다."""
    body = pattern[1:-1] if pattern.startswith("{") and pattern.endswith("}") else pattern
    for part in body.split(","):
        part = part.strip()
        if part.endswith("/**"):
            prefix = part[:-3]
            if relative == prefix or relative.startswith(prefix + "/"):
                return True
        elif relative == part:
            return True
    return False


class VercelConfigTests(unittest.TestCase):
    def test_function_runtime_is_not_a_python_version_string(self) -> None:
        """functions.runtime은 패키지@version만 허용되므로 Python 버전을 넣지 않는다."""
        config = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
        self.assertNotIn("outputDirectory", config)
        self.assertNotIn("builds", config)
        self.assertEqual(list(config["functions"]), ["src/app.py"])
        function = config["functions"]["src/app.py"]
        self.assertNotIn("runtime", function)
        self.assertEqual(function["maxDuration"], 30)
        self.assertEqual(function["includeFiles"], "src/patchpilot/**")
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

    def test_declared_entrypoint_resolves_and_the_src_layout_value_does_not(self) -> None:
        """설정한 module:object는 파일이 있고, 실패한 patchpilot.web.app:app은 없다."""
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        declared = project["tool"]["vercel"]["entrypoint"]
        resolved = resolve_module_attr(ROOT, declared)
        self.assertIsNotNone(resolved)
        assert resolved is not None
        relative, variable = resolved
        self.assertEqual(relative, "src/app.py")
        self.assertEqual(variable, "app")
        self.assertEqual(entrypoint_to_module(relative), "src.app")
        self.assertIsNone(resolve_module_attr(ROOT, "patchpilot.web.app:app"))
        self.assertFalse((ROOT / "patchpilot/web/app.py").exists())
        self.assertTrue((ROOT / "src/patchpilot/web/app.py").is_file())

    def test_public_cdn_stays_out_of_the_function_bundle(self) -> None:
        """public 파일은 저장소에 있고 Function exclude에 들어가며 앱은 mount하지 않는다."""
        config = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
        function = config["functions"]["src/app.py"]
        exclude = function["excludeFiles"]
        include = function["includeFiles"]
        for name in ("index.html", "app.css", "app.js"):
            relative = f"public/{name}"
            self.assertTrue((ROOT / relative).is_file(), relative)
            self.assertTrue(matches_vercel_glob(relative, exclude), relative)
        self.assertTrue(matches_vercel_glob("src/patchpilot/web/app.py", include))
        self.assertFalse(matches_vercel_glob("src/app.py", exclude))
        self.assertFalse(matches_vercel_glob("src/patchpilot/web/app.py", exclude))
        entry = (ROOT / "src/app.py").read_text(encoding="utf-8")
        self.assertNotIn("StaticFiles", entry)
        self.assertNotIn("public", entry)
        web_app = (ROOT / "src/patchpilot/web/app.py").read_text(encoding="utf-8")
        self.assertNotIn("StaticFiles", web_app)

    def test_runtime_file_import_serves_the_sample_api(self) -> None:
        """런타임과 같이 파일 경로로 불러오면 samples와 analyze가 동작한다."""
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        declared = project["tool"]["vercel"]["entrypoint"]
        resolved = resolve_module_attr(ROOT, declared)
        self.assertIsNotNone(resolved)
        assert resolved is not None
        relative, variable = resolved
        module_name = entrypoint_to_module(relative)
        script = r"""
import importlib.util
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
relative, variable, module_name = sys.argv[2], sys.argv[3], sys.argv[4]
sys.path = [item for item in sys.path if item not in ("", str(root)) and str(root) not in item]
path = root / relative
spec = importlib.util.spec_from_file_location(module_name, path)
if spec is None or spec.loader is None:
    raise SystemExit("missing module spec")
module = importlib.util.module_from_spec(spec)
sys.modules[module_name] = module
spec.loader.exec_module(module)
app = getattr(module, variable)
from fastapi.testclient import TestClient

client = TestClient(app)
listed = client.get("/api/v1/samples")
preview = client.post("/api/v1/analyze", json={"sample_id": "supported_rename"})
held = client.post("/api/v1/analyze", json={"sample_id": "split_parent_alias"})
print(json.dumps({
    "samples": listed.status_code,
    "preview": preview.status_code,
    "preview_diff": preview.json()["patch_preview"]["diff"] is not None,
    "held": held.status_code,
    "held_diff": held.json()["patch_preview"]["diff"],
    "kind": preview.json()["envelope_kind"],
}))
"""
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        completed = subprocess.run(
            [sys.executable, "-c", script, str(ROOT), relative, variable, module_name],
            check=False,
            capture_output=True,
            text=True,
            env=env,
            cwd=ROOT,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["samples"], 200)
        self.assertEqual(payload["preview"], 200)
        self.assertTrue(payload["preview_diff"])
        self.assertEqual(payload["held"], 200)
        self.assertIsNone(payload["held_diff"])
        self.assertEqual(payload["kind"], "pp-web-static-analysis/1")


if __name__ == "__main__":
    unittest.main()
