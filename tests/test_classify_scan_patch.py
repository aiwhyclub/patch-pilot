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

    def test_path_item_fields_are_not_a_supported_rename(self) -> None:
        """path item의 parameter, summary, description, servers, x-*는 rename 지원이 아니다."""
        pairs = {}
        parameters = spec("temperature_2m")
        parameters["paths"]["/v1/weather"]["parameters"] = [{"name": "q", "in": "query", "schema": {"type": "string"}}]
        pairs["parameters"] = parameters
        summary = spec("temperature_2m")
        summary["paths"]["/v1/weather"]["summary"] = "changed"
        pairs["summary"] = summary
        description = spec("temperature_2m")
        description["paths"]["/v1/weather"]["description"] = "changed"
        pairs["description"] = description
        servers = spec("temperature_2m")
        servers["paths"]["/v1/weather"]["servers"] = [{"url": "https://example.test"}]
        pairs["servers"] = servers
        extension = spec("temperature_2m")
        extension["paths"]["/v1/weather"]["x-team"] = "changed"
        pairs["x-team"] = extension
        for name, new_doc in pairs.items():
            result = classify_documents(
                spec("temperature"),
                new_doc,
                mapping("current_weather.temperature", "current_weather.temperature_2m"),
            )
            self.assertEqual(result.reason_code, H_UNSUPPORTED_KIND, name)
            self.assertFalse(result.supported, name)
        operation_parameters = spec("temperature_2m")
        operation_parameters["paths"]["/v1/weather"]["get"]["parameters"] = [
            {"name": "q", "in": "query", "schema": {"type": "string"}}
        ]
        inside = classify_documents(
            spec("temperature"),
            operation_parameters,
            mapping("current_weather.temperature", "current_weather.temperature_2m"),
        )
        self.assertEqual(inside.reason_code, H_UNSUPPORTED_KIND)
        root_servers = spec("temperature_2m")
        root_servers["servers"] = [{"url": "https://example.test"}]
        root = classify_documents(
            spec("temperature"),
            root_servers,
            mapping("current_weather.temperature", "current_weather.temperature_2m"),
        )
        self.assertTrue(root.supported)


OPERATION = ("get", "/v1/weather")
POINTER = [["current_weather", "temperature"]]


def _scan(source: str):
    """승인된 GET /v1/weather 기준으로 한 소스를 탐색한다."""
    return scan_source("client.py", source, POINTER, OPERATION)


class ScanTests(unittest.TestCase):
    def test_direct_json_assignment_of_fixed_operation_is_supported(self) -> None:
        """고정 GET의 .json()을 한 번 대입한 변수의 문자열 키만 사이트다."""
        source = (
            "def read_temp():\n"
            "    body = requests.get(\"https://example.test/v1/weather\").json()\n"
            "    return body[\"current_weather\"][\"temperature\"]\n"
        )
        result = _scan(source)
        self.assertFalse(result.unresolved)
        self.assertEqual(result.sites[0].base, "body")
        self.assertEqual(result.sites[0].keys, ["current_weather", "temperature"])
        self.assertEqual(result.sites[0].binding, "direct_json_response")

    def test_two_step_json_call_on_fixed_operation_is_supported(self) -> None:
        """고정 호출을 담은 이름에 바로 붙인 .json() 대입도 응답 변수다."""
        source = (
            "def read_temp():\n"
            "    response = requests.get(\"/v1/weather\")\n"
            "    body = response.json()\n"
            "    return body[\"current_weather\"][\"temperature\"]\n"
        )
        result = _scan(source)
        self.assertFalse(result.unresolved)
        self.assertEqual(result.sites[0].base, "body")

    def test_request_method_and_path_literals_are_supported(self) -> None:
        """method와 path가 모두 문자열 리터럴인 request 호출의 JSON 대입을 인정한다."""
        source = (
            "def read_temp():\n"
            "    body = client.request(\"GET\", \"/v1/weather\").json()\n"
            "    return body.get(\"current_weather\").get(\"temperature\")\n"
        )
        result = _scan(source)
        self.assertFalse(result.unresolved)
        self.assertEqual(len(result.sites), 1)

    def test_module_level_direct_json_assignment_is_supported(self) -> None:
        """함수 밖이어도 직접 JSON 대입이면 파라미터 규칙으로 버리지 않는다."""
        source = (
            "body = requests.get(\"/v1/weather\").json()\n"
            "TEMP = body[\"current_weather\"][\"temperature\"]\n"
        )
        result = _scan(source)
        self.assertFalse(result.unresolved)
        self.assertEqual(result.sites[0].base, "body")

    def test_unrelated_dynamic_index_does_not_reject_direct_binding(self) -> None:
        """응답 변수가 아닌 다른 시퀀스 첨자는 정상 바인딩을 보류로 만들지 않는다."""
        source = (
            "def read_temp(rows, index):\n"
            "    body = requests.get(\"/v1/weather\").json()\n"
            "    item = rows[index]\n"
            "    return body[\"current_weather\"][\"temperature\"]\n"
        )
        result = _scan(source)
        self.assertFalse(result.unresolved)
        self.assertEqual(result.sites[0].base, "body")

    def test_other_api_same_key_is_unresolved(self) -> None:
        """같은 키라도 다른 path의 JSON이면 승인 응답 변수가 아니다."""
        source = (
            "def read_temp():\n"
            "    body = requests.get(\"/v1/forecast\").json()\n"
            "    return body[\"current_weather\"][\"temperature\"]\n"
        )
        result = _scan(source)
        self.assertTrue(result.unresolved)
        self.assertEqual(result.sites, [])

    def test_other_method_same_path_is_unresolved(self) -> None:
        """같은 path라도 method가 다르면 승인 operation이 아니다."""
        source = (
            "def read_temp():\n"
            "    body = requests.post(\"/v1/weather\").json()\n"
            "    return body[\"current_weather\"][\"temperature\"]\n"
        )
        result = _scan(source)
        self.assertTrue(result.unresolved)
        self.assertEqual(result.sites, [])

    def test_arbitrary_parameter_is_unresolved(self) -> None:
        """함수 파라미터의 []/.get은 응답 변수로 과신하지 않는다."""
        source = "def read_temp(payload):\n    return payload[\"current_weather\"][\"temperature\"]\n"
        get_chain = "def read_temp(payload):\n    return payload.get(\"current_weather\").get(\"temperature\")\n"
        self.assertTrue(_scan(source).unresolved)
        self.assertEqual(_scan(source).sites, [])
        self.assertTrue(_scan(get_chain).unresolved)

    def test_alias_of_response_variable_is_unresolved(self) -> None:
        """응답 변수를 다른 이름에 옮기면 직접 접근이 아니다."""
        source = (
            "def read_temp():\n"
            "    body = requests.get(\"/v1/weather\").json()\n"
            "    data = body\n"
            "    return data[\"current_weather\"][\"temperature\"]\n"
        )
        result = _scan(source)
        self.assertTrue(result.unresolved)
        self.assertEqual(result.sites, [])

    def test_reassignment_of_response_variable_is_unresolved(self) -> None:
        """응답 변수를 다시 대입하면 그 이름을 사이트로 쓰지 않는다."""
        source = (
            "def read_temp():\n"
            "    body = requests.get(\"/v1/weather\").json()\n"
            "    body = body\n"
            "    return body[\"current_weather\"][\"temperature\"]\n"
        )
        result = _scan(source)
        self.assertTrue(result.unresolved)
        self.assertEqual(result.sites, [])

    def test_dynamic_key_on_response_variable_is_unresolved(self) -> None:
        """응답 변수의 동적 키는 정적 포인터로 풀지 않는다."""
        source = (
            "def read_temp(key):\n"
            "    body = requests.get(\"/v1/weather\").json()\n"
            "    return body[\"current_weather\"][key]\n"
        )
        result = _scan(source)
        self.assertTrue(result.unresolved)
        self.assertEqual(result.sites, [])

    def test_variable_url_is_unresolved(self) -> None:
        """URL이 이름이거나 이어 붙인 값이면 고정 API 호출이 아니다."""
        source = (
            "def read_temp(url):\n"
            "    body = requests.get(url).json()\n"
            "    return body[\"current_weather\"][\"temperature\"]\n"
        )
        result = _scan(source)
        self.assertTrue(result.unresolved)
        self.assertEqual(result.sites, [])

    def test_inline_json_call_without_assignment_is_unresolved(self) -> None:
        """변수에 직접 대입하지 않은 .json() 체인은 응답 변수가 아니다."""
        source = (
            "def read_temp():\n"
            "    return requests.get(\"/v1/weather\").json()[\"current_weather\"][\"temperature\"]\n"
        )
        result = _scan(source)
        self.assertTrue(result.unresolved)
        self.assertEqual(result.sites, [])

    def test_mixed_direct_and_parameter_is_unresolved(self) -> None:
        """직접 대입이 있어도 같은 키의 파라미터 접근이 있으면 일부만 인정하지 않는다."""
        source = (
            "def read_temp(payload):\n"
            "    body = requests.get(\"/v1/weather\").json()\n"
            "    left = body[\"current_weather\"][\"temperature\"]\n"
            "    right = payload[\"current_weather\"][\"temperature\"]\n"
            "    return left\n"
        )
        result = _scan(source)
        self.assertTrue(result.unresolved)
        self.assertEqual(result.sites, [])

    def test_scope_rebindings_of_the_response_name_are_unresolved(self) -> None:
        """같은 범위를 묶는 comprehension, except, with, async for, import, match는 응답 변수가 아니다."""
        samples = {
            "comprehension": (
                "def read_temp(rows):\n"
                "    body = requests.get('/v1/weather').json()\n"
                "    return [body['current_weather']['temperature'] for body in rows]\n"
            ),
            "except": (
                "def read_temp():\n"
                "    body = requests.get('/v1/weather').json()\n"
                "    try:\n"
                "        return 1\n"
                "    except Exception as body:\n"
                "        return body['current_weather']['temperature']\n"
            ),
            "with": (
                "def read_temp():\n"
                "    body = requests.get('/v1/weather').json()\n"
                "    with ctx() as body:\n"
                "        return body['current_weather']['temperature']\n"
            ),
            "async-with": (
                "async def read_temp():\n"
                "    body = requests.get('/v1/weather').json()\n"
                "    async with ctx() as body:\n"
                "        return body['current_weather']['temperature']\n"
            ),
            "async-for": (
                "async def read_temp(rows):\n"
                "    body = requests.get('/v1/weather').json()\n"
                "    async for body in rows:\n"
                "        return body['current_weather']['temperature']\n"
            ),
            "for": (
                "def read_temp(rows):\n"
                "    body = requests.get('/v1/weather').json()\n"
                "    for body in rows:\n"
                "        return body['current_weather']['temperature']\n"
            ),
            "import": (
                "def read_temp():\n"
                "    body = requests.get('/v1/weather').json()\n"
                "    import json as body\n"
                "    return body['current_weather']['temperature']\n"
            ),
            "match": (
                "def read_temp(item):\n"
                "    body = requests.get('/v1/weather').json()\n"
                "    match item:\n"
                "        case body:\n"
                "            return body['current_weather']['temperature']\n"
            ),
        }
        for name, source in samples.items():
            result = _scan(source)
            self.assertTrue(result.unresolved, name)
            self.assertEqual(result.sites, [], name)

    def test_other_scope_names_do_not_reject_the_response_variable(self) -> None:
        """다른 반복 이름, 다른 except, 다른 match capture는 응답 변수를 묶지 않는다."""
        samples = (
            "def read_temp(rows):\n"
            "    body = requests.get('/v1/weather').json()\n"
            "    return [body['current_weather']['temperature'] for row in rows]\n",
            "def read_temp():\n"
            "    body = requests.get('/v1/weather').json()\n"
            "    try:\n"
            "        return body['current_weather']['temperature']\n"
            "    except Exception as other:\n"
            "        return other\n",
            "def read_temp(item):\n"
            "    body = requests.get('/v1/weather').json()\n"
            "    match item:\n"
            "        case other:\n"
            "            return body['current_weather']['temperature']\n",
        )
        for source in samples:
            result = _scan(source)
            self.assertFalse(result.unresolved)
            self.assertEqual(result.sites[0].base, "body")

    def test_object_alias_mixed_with_direct_access_is_unresolved(self) -> None:
        """응답 객체를 속성이나 컨테이너에 넣으면 직접 사이트와 함께 있어도 보류한다."""
        holder = (
            "def read_temp():\n"
            "    body = requests.get('/v1/weather').json()\n"
            "    holder.payload = body\n"
            "    a = body['current_weather']['temperature']\n"
            "    b = holder.payload['current_weather']['temperature']\n"
            "    return a\n"
        )
        box = (
            "def read_temp():\n"
            "    body = requests.get('/v1/weather').json()\n"
            "    box['payload'] = body\n"
            "    a = body['current_weather']['temperature']\n"
            "    b = box['payload']['current_weather']['temperature']\n"
            "    return a\n"
        )
        self.assertTrue(_scan(holder).unresolved)
        self.assertEqual(_scan(holder).sites, [])
        self.assertTrue(_scan(box).unresolved)
        self.assertEqual(_scan(box).sites, [])

    def test_parent_slice_alias_mixed_with_direct_chain_is_unresolved(self) -> None:
        """부모 조각을 다른 이름에 나누면 전체 체인이 같이 있어도 직접 사이트로 끝내지 않는다."""
        split = (
            "def read_temp():\n"
            "    body = requests.get('/v1/weather').json()\n"
            "    saved = body['current_weather']\n"
            "    shown = body['current_weather']['temperature']\n"
            "    hidden = saved['temperature']\n"
            "    return shown\n"
        )
        dotted = (
            "def read_temp():\n"
            "    body = requests.get('/v1/weather').json()\n"
            "    saved = body.get('current_weather')\n"
            "    shown = body.get('current_weather').get('temperature')\n"
            "    hidden = saved.get('temperature')\n"
            "    return shown\n"
        )
        parent_only = (
            "def read_temp():\n"
            "    body = requests.get('/v1/weather').json()\n"
            "    saved = body['current_weather']\n"
            "    return saved['temperature']\n"
        )
        sibling = (
            "def read_temp():\n"
            "    body = requests.get('/v1/weather').json()\n"
            "    wind = body['current_weather']['windspeed']\n"
            "    return body['current_weather']['temperature']\n"
        )
        for name, source in (("split", split), ("get", dotted), ("parent", parent_only)):
            result = _scan(source)
            self.assertTrue(result.unresolved, name)
            self.assertEqual(result.sites, [], name)
        kept = _scan(sibling)
        self.assertFalse(kept.unresolved)
        self.assertEqual(kept.sites[0].keys, ["current_weather", "temperature"])

    def test_path_literal_outside_the_url_slot_is_unresolved(self) -> None:
        """path 문자열이 URL 칸이 아니면 승인 operation 호출이 아니다."""
        helper = (
            "def read_temp():\n"
            "    body = helper('GET', '/tmp/other', note='/v1/weather').json()\n"
            "    return body['current_weather']['temperature']\n"
        )
        noted = (
            "def read_temp():\n"
            "    body = requests.get('/tmp/other', note='/v1/weather').json()\n"
            "    return body['current_weather']['temperature']\n"
        )
        self.assertTrue(_scan(helper).unresolved)
        self.assertEqual(_scan(helper).sites, [])
        self.assertTrue(_scan(noted).unresolved)
        keyword = (
            "def read_temp():\n"
            "    body = requests.get(url='/v1/weather').json()\n"
            "    return body['current_weather']['temperature']\n"
        )
        request_keyword = (
            "def read_temp():\n"
            "    body = client.request(method='GET', url='/v1/weather').json()\n"
            "    return body['current_weather']['temperature']\n"
        )
        cache_get = (
            "def read_temp():\n"
            "    body = cache.get('/v1/weather').json()\n"
            "    return body['current_weather']['temperature']\n"
        )
        for source in (keyword, request_keyword, cache_get):
            result = _scan(source)
            self.assertFalse(result.unresolved)
            self.assertEqual(result.sites[0].binding, "direct_json_response")


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

    def test_arithmetic_injection_is_rejected(self) -> None:
        """마지막 키 옆에 산술을 넣으면 AST equality가 거절한다."""
        old = 'def read_temp(payload):\n    return payload["current_weather"]["temperature"]\n'
        diff = (
            "--- a/client.py\n+++ b/client.py\n@@ -1,2 +1,2 @@\n"
            " def read_temp(payload):\n"
            '-    return payload["current_weather"]["temperature"]\n'
            '+    return payload["current_weather"]["temperature_2m"] + 1\n'
        )
        renames = [{"path": "client.py", "old_keys": ["current_weather", "temperature"], "new_key": "temperature_2m"}]
        self.assertEqual(validate_patch({"client.py": old}, diff, renames), H_PATCH_REJECTED)

    def test_protected_aliases_are_rejected_without_blocking_ordinary_names(self) -> None:
        """test.py, Tests/, fixture.py는 거부하고 client.py와 contest.py는 그대로 둔다."""
        old = 'def read_temp(payload):\n    return payload["current_weather"]["temperature"]\n'
        renames_for = lambda path: [{"path": path, "old_keys": ["current_weather", "temperature"], "new_key": "temperature_2m"}]
        rejected = ("test.py", "tests.py", "Tests/client.py", "fixture.py", "fixtures.py", "TEST.PY")
        allowed = ("client.py", "contest.py", "latest.py")
        for path in rejected:
            diff = (
                f"--- a/{path}\n+++ b/{path}\n@@ -1,2 +1,2 @@\n"
                " def read_temp(payload):\n"
                '-    return payload["current_weather"]["temperature"]\n'
                '+    return payload["current_weather"]["temperature_2m"]\n'
            )
            self.assertEqual(validate_patch({path: old}, diff, renames_for(path)), H_PATCH_REJECTED, path)
        for path in allowed:
            diff = (
                f"--- a/{path}\n+++ b/{path}\n@@ -1,2 +1,2 @@\n"
                " def read_temp(payload):\n"
                '-    return payload["current_weather"]["temperature"]\n'
                '+    return payload["current_weather"]["temperature_2m"]\n'
            )
            self.assertIsNone(validate_patch({path: old}, diff, renames_for(path)), path)

    def test_unquoted_secret_assignment_rejects_the_diff(self) -> None:
        """따옴표 없는 password 대입이 문맥에 있으면 키 변경 diff를 통과시키지 않는다."""
        old = (
            "password=supersecretvalue\n"
            "def read_temp(payload):\n"
            '    return payload["current_weather"]["temperature"]\n'
        )
        diff = (
            "--- a/client.py\n+++ b/client.py\n@@ -1,3 +1,3 @@\n"
            " password=supersecretvalue\n"
            " def read_temp(payload):\n"
            '-    return payload["current_weather"]["temperature"]\n'
            '+    return payload["current_weather"]["temperature_2m"]\n'
        )
        renames = [{"path": "client.py", "old_keys": ["current_weather", "temperature"], "new_key": "temperature_2m"}]
        self.assertEqual(validate_patch({"client.py": old}, diff, renames), H_PATCH_REJECTED)


if __name__ == "__main__":
    unittest.main()
