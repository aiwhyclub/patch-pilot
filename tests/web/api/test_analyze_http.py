# 난이도: Mid
# 학습 키워드: HTTP, Envelope, Alias
"""샘플 분석 API가 정적 결과와 안전 오류만 돌려주는지 확인한다."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from patchpilot.patch.validate import validate_patch
from patchpilot.scan.ast_scan import scan_source
from patchpilot.schema.codes import DATA_NOTICE, E_RUNTIME_NOT_READY, H_UNRESOLVED, reason_text
from patchpilot.web.http import MAX_BODY_BYTES, error_document, handle
from patchpilot.web.samples import CLIENT_PATH, SAMPLES, SOURCE_SPLIT

ROOT = Path(__file__).resolve().parents[3]


class AnalyzeHttpTests(unittest.TestCase):
    def test_samples_are_the_fixed_enum(self) -> None:
        """목록은 지원 rename과 hold 샘플만 보여주고 고지는 계약 문장이다."""
        status, _headers, payload = handle("GET", "/api/v1/samples", b"")
        body = json.loads(payload)
        self.assertEqual(status, 200)
        self.assertEqual(body["data_notice"], DATA_NOTICE)
        kinds = {item["id"]: item["kind"] for item in body["samples"]}
        self.assertEqual(kinds, {"supported_rename": "supported_rename", "split_parent_alias": "hold_variant"})
        self.assertIn("current_weather", body["samples"][0]["preview"]["source"])

    def test_supported_sample_has_a_checked_static_preview(self) -> None:
        """직접 바인딩은 diff가 있고, 그 diff는 패치 검사를 통과한 정적 미리보기다."""
        body = self._analyze("supported_rename")
        self.assertEqual(body["envelope_kind"], "pp-web-static-analysis/1")
        self.assertTrue(body["analyzed_at"].endswith("+09:00"))
        self.assertEqual(body["static_analysis"]["classify"]["status"], "ok")
        self.assertEqual(body["static_analysis"]["scan"]["status"], "ok")
        self.assertEqual(body["static_analysis"]["patch_preview"]["status"], "ok")
        self.assertIsNone(body["static_analysis"]["patch_preview"]["reason_code"])
        diff = body["patch_preview"]["diff"]
        self.assertIsInstance(diff, str)
        self.assertIn("temperature_2m", diff)
        self.assertEqual(body["patch_preview"]["files"], [CLIENT_PATH])
        self.assertIn("not a model-generated repair", body["static_analysis"]["patch_preview"]["user_message"])
        sample = SAMPLES["supported_rename"]
        renames = [{
            "path": CLIENT_PATH,
            "old_keys": ["current_weather", "temperature"],
            "new_key": "temperature_2m",
        }]
        self.assertIsNone(validate_patch({CLIENT_PATH: sample["source"]}, diff, renames))
        self._assert_unclaimed(body)

    def test_split_parent_alias_sample_has_no_diff(self) -> None:
        """부모 조각을 나눈 샘플은 unresolved이고 diff는 null이다."""
        scanned = scan_source(
            CLIENT_PATH,
            SOURCE_SPLIT,
            [["current_weather", "temperature"]],
            ("get", "/v1/weather"),
        )
        self.assertTrue(scanned.unresolved)
        self.assertEqual(scanned.sites, [])
        body = self._analyze("split_parent_alias")
        self.assertEqual(body["static_analysis"]["classify"]["status"], "ok")
        scan = body["static_analysis"]["scan"]
        self.assertEqual(scan["status"], "hold")
        self.assertEqual(scan["reason_code"], H_UNRESOLVED)
        self.assertEqual(scan["user_message"], reason_text(H_UNRESOLVED))
        self.assertIsNone(body["patch_preview"]["diff"])
        self.assertEqual(body["patch_preview"]["files"], [])
        self.assertNotEqual(body["static_analysis"]["patch_preview"]["status"], "ok")
        self._assert_unclaimed(body)

    def test_bad_sample_and_payload_do_not_echo_the_body(self) -> None:
        """알 수 없는 샘플, 추가 필드, 큰 본문은 안전 오류이고 원문을 되풀이하지 않는다."""
        unknown = self._post({"sample_id": "customer-repo"})
        self.assertEqual(unknown[0], 400)
        self.assertEqual(json.loads(unknown[2])["error"]["code"], "WEB_BAD_SAMPLE")
        self.assertNotIn(b"customer-repo", unknown[2])
        extra = self._post({"sample_id": "supported_rename", "note": "password=supersecretvalue"})
        self.assertEqual(extra[0], 400)
        self.assertEqual(json.loads(extra[2])["error"]["code"], "WEB_PAYLOAD")
        self.assertNotIn(b"supersecretvalue", extra[2])
        raw = b'{"sample_id":"supported_rename","password":"supersecretvalue"}'
        status, _headers, payload = handle("POST", "/api/v1/analyze", raw)
        self.assertEqual(status, 400)
        self.assertNotIn(b"supersecretvalue", payload)
        oversized = b"x" * (MAX_BODY_BYTES + 1)
        status, headers, payload = handle("POST", "/api/v1/analyze", oversized)
        self.assertEqual(status, 413)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertNotIn(b"xxxx", payload)
        self.assertEqual(handle("POST", "/api/v1/analyze", b"")[0], 400)
        self.assertEqual(handle("GET", "/api/v1/analyze", b"")[0], 400)
        self.assertNotIn("outcome", json.loads(unknown[2]))

    def test_runner_exception_hides_the_traceback(self) -> None:
        """분석 예외는 WEB_INTERNAL이고 예외 문장을 넣지 않는다."""
        def boom(_sample_id: str) -> dict:
            raise RuntimeError("password=supersecretvalue")

        raw = json.dumps({"sample_id": "supported_rename"}).encode("utf-8")
        status, _headers, payload = handle("POST", "/api/v1/analyze", raw, runner=boom)
        body = json.loads(payload)
        self.assertEqual(status, 500)
        self.assertEqual(body["error"]["code"], "WEB_INTERNAL")
        self.assertNotIn("password", payload.decode("utf-8"))
        self.assertNotIn("Traceback", payload.decode("utf-8"))
        self.assertNotIn("diff", body)

    def test_error_catalog_matches_the_safe_shape(self) -> None:
        """정의된 웹 오류 코드는 ok false와 http_status만 가진다."""
        codes = {
            "WEB_BAD_SAMPLE": 400,
            "WEB_PAYLOAD": 400,
            "WEB_TIMEOUT": 408,
            "WEB_OVERLOAD": 503,
            "WEB_INTERNAL": 500,
        }
        for code, status in codes.items():
            document = error_document(code, status)
            self.assertFalse(document["ok"])
            self.assertEqual(document["error"]["code"], code)
            self.assertEqual(document["error"]["http_status"], status)
            self.assertNotIn("exit", document["error"])

    def test_web_sources_do_not_call_customer_execution(self) -> None:
        """웹 모듈은 worker, publisher, 프로세스 실행을 호출하지 않는다."""
        calls = (
            "publish_draft_" + "pr(",
            "run_customer_" + "worker(",
            "sub" + "process.",
            "rev-" + "parse",
            "ev" + "al(",
            "ex" + "ec(",
            "import " + "requests",
        )
        paths = list((ROOT / "src/patchpilot/web").glob("*.py"))
        self.assertGreaterEqual(len(paths), 4)
        for path in paths:
            text = path.read_text(encoding="utf-8")
            for call in calls:
                self.assertNotIn(call, text, path.name)

    def test_fastapi_routes_are_same_origin_json(self) -> None:
        """FastAPI 경로가 같은 핸들러를 쓰고 analyze에 no-store를 붙인다."""
        try:
            from fastapi.testclient import TestClient
            from patchpilot.web.app import app
        except ImportError as exc:
            self.fail(f"web requirements missing: {exc}")
        client = TestClient(app)
        listed = client.get("/api/v1/samples")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.headers["cache-control"], "no-store")
        analyzed = client.post("/api/v1/analyze", json={"sample_id": "split_parent_alias"})
        self.assertEqual(analyzed.status_code, 200)
        self.assertEqual(analyzed.headers["cache-control"], "no-store")
        self.assertIsNone(analyzed.json()["patch_preview"]["diff"])
        huge = client.post("/api/v1/analyze", content=b"y" * (MAX_BODY_BYTES + 1))
        self.assertEqual(huge.status_code, 413)
        self.assertNotIn("yyyy", huge.text)
        self.assertEqual(client.get("/openapi.json").status_code, 404)

    def _analyze(self, sample_id: str) -> dict:
        status, headers, payload = self._post({"sample_id": sample_id})
        self.assertEqual(status, 200, payload)
        self.assertEqual(headers["Cache-Control"], "no-store")
        return json.loads(payload)

    def _post(self, document: dict):
        raw = json.dumps(document).encode("utf-8")
        return handle("POST", "/api/v1/analyze", raw)

    def _assert_unclaimed(self, body: dict) -> None:
        runtime = body["runtime"]
        self.assertEqual(runtime["status"], "not_run")
        self.assertEqual(runtime["reason_code"], E_RUNTIME_NOT_READY)
        self.assertEqual(runtime["user_message"], reason_text(E_RUNTIME_NOT_READY))
        self.assertEqual(body["pr"]["existence"], "not_attempted")
        self.assertEqual(body["ac24"], "NOT_RUN")
        self.assertFalse(body["cli_manifest_claim"])
        self.assertTrue(body["downloadable"])
        self.assertNotIn("outcome", body)
        self.assertNotIn("schema_version", body)
        self.assertNotEqual(body["envelope_kind"], "pp-manifest/1")


if __name__ == "__main__":
    unittest.main()
