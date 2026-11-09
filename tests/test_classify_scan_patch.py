# 난이도: Mid
# 학습 키워드: unittest, OpenAPI, AST, Unified Diff
"""분류, 정적 AST, 패치 검증을 합성 문자열로만 확인한다."""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from patchpilot.diff_spec.classify import classify_documents, load_json_bytes
from patchpilot.patch.validate import validate_patch
from patchpilot.scan.ast_scan import scan_source
from patchpilot.schema.codes import (
    H_METADATA_MISSING,
    H_NO_CHANGE,
    H_NO_MAPPING,
    H_PATCH_REJECTED,
    H_UNIT_OR_SEMANTIC,
    H_UNSUPPORTED_KIND,
    H_UNSUPPORTED_SPEC,
)


def spec(prop: str, parent: str = "current_weather", extra_operation: bool = False, ref: bool = False) -> dict:
    """테스트용 OpenAPI 3.0.3 문서 하나를 만든다."""
    schema = {
        "type": "object",
        "properties": {
            parent: {
                "type": "object",
                "required": [prop, "windspeed"],
                "properties": {prop: {"type": "number"}, "windspeed": {"type": "number"}},
            }
        },
    }
    if ref:
        schema["properties"][parent]["properties"][prop] = {"$ref": "#/components/schemas/Temp"}
    operation = {
        "operationId": "getWeather",
        "responses": {"200": {"description": "ok", "content": {"application/json": {"schema": schema}}}},
    }
    path_item = {"get": operation}
    if extra_operation:
        path_item["post"] = copy.deepcopy(operation)
    return {
        "openapi": "3.0.3",
        "info": {"title": "demo", "version": "1"},
        "paths": {"/v1/weather": path_item},
    }


def mapping(old: str, new: str, **flags) -> dict:
    """필수 bool이 채워진 mapping 객체를 만든다."""
    body = {
        "old_pointer": old,
        "new_pointer": new,
        "type_same": True,
        "unit_same": True,
        "semantic_same": True,
    }
    body.update(flags)
    return body


class ClassifyTests(unittest.TestCase):
    def test_same_parent_rename_is_supported(self) -> None:
        """같은 부모의 키 개명과 명시 mapping은 supported field_renamed다."""
        result = classify_documents(
            spec("temperature"),
            spec("temperature_2m"),
            mapping("current_weather.temperature", "current_weather.temperature_2m"),
        )
        self.assertIsNone(result.reason_code)
        self.assertTrue(result.supported)
        self.assertEqual(result.changes[0].kind, "field_renamed")
        self.assertTrue(result.changes[0].same_parent)
        self.assertIsNone(result.changes[0].reason)

    def test_info_version_difference_does_not_block_rename(self) -> None:
        """응답 operation이 같으면 info.version 차이만으로 보류하지 않는다."""
        new_doc = spec("temperature_2m")
        new_doc["info"]["version"] = "2"
        result = classify_documents(
            spec("temperature"),
            new_doc,
            mapping("current_weather.temperature", "current_weather.temperature_2m"),
        )
        self.assertTrue(result.supported)

    def test_parent_move_is_unsupported_kind(self) -> None:
        """부모가 바뀌면 field_moved로 기록하고 지원하지 않는다."""
        result = classify_documents(
            spec("temperature"),
            spec("temperature_2m", parent="current"),
            mapping("current_weather.temperature", "current.temperature_2m"),
        )
        self.assertEqual(result.reason_code, H_UNSUPPORTED_KIND)
        self.assertEqual(result.changes[0].kind, "field_moved")
        self.assertFalse(result.changes[0].supported)

    def test_name_similarity_without_mapping_is_not_a_rename(self) -> None:
        """mapping이 없으면 이름이 비슷해도 rename으로 확정하지 않는다."""
        result = classify_documents(spec("temperature"), spec("temperature_2m"), [])
        self.assertEqual(result.reason_code, H_NO_MAPPING)
        self.assertEqual(result.changes, [])

    def test_identical_spec_without_mapping_is_no_change(self) -> None:
        """문서가 같고 mapping이 비어 있으면 변경 없음이다."""
        result = classify_documents(spec("temperature"), spec("temperature"), [])
        self.assertEqual(result.reason_code, H_NO_CHANGE)

    def test_ref_and_second_operation_and_yaml_are_unsupported(self) -> None:
        """$ref, operation 2개, JSON이 아닌 문서는 H_UNSUPPORTED_SPEC이다."""
        ref = classify_documents(spec("temperature", ref=True), spec("temperature_2m"), mapping("a.b", "a.c"))
        many = classify_documents(spec("temperature", extra_operation=True), spec("temperature_2m"), [])
        _doc, err = load_json_bytes(b"openapi: 3.0.3\n")
        self.assertEqual(ref.reason_code, H_UNSUPPORTED_SPEC)
        self.assertEqual(many.reason_code, H_UNSUPPORTED_SPEC)
        self.assertEqual(err, H_UNSUPPORTED_SPEC)

    def test_duplicate_json_key_is_unsupported(self) -> None:
        """중복 JSON 키는 마지막 값으로 덮지 않고 거부한다."""
        raw = b'{"openapi":"3.0.3","openapi":"3.0.0"}'
        _doc, err = load_json_bytes(raw)
        self.assertEqual(err, H_UNSUPPORTED_SPEC)

    def test_false_semantic_flag_and_missing_bool_hold(self) -> None:
        """의미가 다르거나 bool이 없으면 자동 수정하지 않는다."""
        semantic = classify_documents(
            spec("temperature"),
            spec("temperature_2m"),
            mapping("current_weather.temperature", "current_weather.temperature_2m", semantic_same=False),
        )
        missing = classify_documents(
            spec("temperature"),
            spec("temperature_2m"),
            {"old_pointer": "current_weather.temperature", "new_pointer": "current_weather.temperature_2m"},
        )
        self.assertEqual(semantic.reason_code, H_UNIT_OR_SEMANTIC)
        self.assertEqual(missing.reason_code, H_METADATA_MISSING)

    def test_leaf_schema_change_is_unit_or_semantic(self) -> None:
        """mapping이 같다고 해도 스키마 타입이 다르면 보류한다."""
        new_doc = spec("temperature_2m")
        new_doc["paths"]["/v1/weather"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["properties"]["current_weather"]["properties"]["temperature_2m"] = {"type": "string"}
        result = classify_documents(
            spec("temperature"),
            new_doc,
            mapping("current_weather.temperature", "current_weather.temperature_2m"),
        )
        self.assertEqual(result.reason_code, H_UNIT_OR_SEMANTIC)


class ScanTests(unittest.TestCase):
    def test_direct_parameter_chain_is_a_site(self) -> None:
        """파라미터에서 바로 이어진 문자열 키 체인만 사이트로 남긴다."""
        source = 'def read_temp(payload):\n    return payload["current_weather"]["temperature"]\n'
        result = scan_source("client.py", source, [["current_weather", "temperature"]])
        self.assertFalse(result.unresolved)
        self.assertEqual(result.sites[0].base, "payload")
        self.assertEqual(result.sites[0].keys, ["current_weather", "temperature"])

    def test_get_chain_is_a_site(self) -> None:
        """문자열 인자 하나인 .get 체인도 직접 접근으로 본다."""
        source = 'def read_temp(payload):\n    return payload.get("current_weather").get("temperature")\n'
        result = scan_source("client.py", source, [["current_weather", "temperature"]])
        self.assertFalse(result.unresolved)
        self.assertEqual(len(result.sites), 1)

    def test_alias_dynamic_and_reassignment_are_unresolved(self) -> None:
        """별칭, 동적 키, 파라미터 재대입은 사이트를 만들지 않는다."""
        alias = 'def read_temp(payload):\n    data = payload\n    return data["current_weather"]["temperature"]\n'
        dynamic = 'def read_temp(payload, key):\n    return payload["current_weather"][key]\n'
        again = 'def read_temp(payload):\n    payload = payload\n    return payload["current_weather"]["temperature"]\n'
        pointers = [["current_weather", "temperature"]]
        self.assertTrue(scan_source("a.py", alias, pointers).unresolved)
        self.assertTrue(scan_source("b.py", dynamic, pointers).unresolved)
        self.assertTrue(scan_source("c.py", again, pointers).unresolved)
        self.assertEqual(scan_source("a.py", alias, pointers).sites, [])


class PatchTests(unittest.TestCase):
    def test_last_key_diff_is_accepted(self) -> None:
        """마지막 문자열 키만 바뀐 diff는 통과한다."""
        old = 'def read_temp(payload):\n    return payload["current_weather"]["temperature"]\n'
        diff = (
            "--- a/client.py\n"
            "+++ b/client.py\n"
            "@@ -1,2 +1,2 @@\n"
            " def read_temp(payload):\n"
            '-    return payload["current_weather"]["temperature"]\n'
            '+    return payload["current_weather"]["temperature_2m"]\n'
        )
        renames = [{"path": "client.py", "old_keys": ["current_weather", "temperature"], "new_key": "temperature_2m"}]
        self.assertIsNone(validate_patch({"client.py": old}, diff, renames))

    def test_added_call_changed_constant_new_file_and_secret_are_rejected(self) -> None:
        """호출 추가, 다른 상수, 새 파일, 비밀 포함 diff는 거절한다."""
        old = 'def read_temp(payload):\n    return payload["current_weather"]["temperature"]\n'
        renames = [{"path": "client.py", "old_keys": ["current_weather", "temperature"], "new_key": "temperature_2m"}]
        call = (
            "--- a/client.py\n+++ b/client.py\n@@ -1,2 +1,3 @@\n"
            " def read_temp(payload):\n"
            '-    return payload["current_weather"]["temperature"]\n'
            '+    return payload["current_weather"]["temperature_2m"]\n'
            '+    eval("1")\n'
        )
        number = (
            "--- a/client.py\n+++ b/client.py\n@@ -1,2 +1,2 @@\n"
            " def read_temp(payload):\n"
            "-    return payload[\"current_weather\"][\"temperature\"]\n"
            "-    return 1\n"
        )
        # number diff above is intentionally malformed context; build a real constant change
        number = (
            "--- a/client.py\n+++ b/client.py\n@@ -1,2 +1,2 @@\n"
            " def read_temp(payload):\n"
            '-    return payload["current_weather"]["temperature"]\n'
            '+    return 1\n'
        )
        created = "--- /dev/null\n+++ b/client.py\n@@ -0,0 +1,1 @@\n+x = 1\n"
        secret = (
            "--- a/client.py\n+++ b/client.py\n@@ -1,2 +1,2 @@\n"
            " def read_temp(payload):\n"
            '-    return payload["current_weather"]["temperature"]\n'
            '+    return "AKIAFAKEFAKEFAKEFAKE"\n'
        )
        self.assertEqual(validate_patch({"client.py": old}, call, renames), H_PATCH_REJECTED)
        self.assertEqual(validate_patch({"client.py": old}, number, renames), H_PATCH_REJECTED)
        self.assertEqual(validate_patch({"client.py": old}, created, renames), H_PATCH_REJECTED)
        self.assertEqual(validate_patch({"client.py": old}, secret, renames), H_PATCH_REJECTED)

    def test_test_path_is_rejected(self) -> None:
        """테스트 파일 경로는 allowlist에 있어도 패치할 수 없다."""
        old = 'def read_temp(payload):\n    return payload["current_weather"]["temperature"]\n'
        diff = (
            "--- a/test_client.py\n+++ b/test_client.py\n@@ -1,2 +1,2 @@\n"
            " def read_temp(payload):\n"
            '-    return payload["current_weather"]["temperature"]\n'
            '+    return payload["current_weather"]["temperature_2m"]\n'
        )
        renames = [{"path": "test_client.py", "old_keys": ["current_weather", "temperature"], "new_key": "temperature_2m"}]
        self.assertEqual(validate_patch({"test_client.py": old}, diff, renames), H_PATCH_REJECTED)


if __name__ == "__main__":
    unittest.main()
