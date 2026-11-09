# 난이도: Difficult
# 학습 키워드: OpenAPI, JSON, Schema, Field Rename
"""OpenAPI 3.0.3 JSON 한 operation의 같은 부모 키 개명만 지원으로 분류한다."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass, field

from patchpilot.schema.codes import (
    H_METADATA_MISSING,
    H_NO_CHANGE,
    H_NO_MAPPING,
    H_UNIT_OR_SEMANTIC,
    H_UNSUPPORTED_KIND,
    H_UNSUPPORTED_SPEC,
)

HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}
ALLOWED_ROOT = {"openapi", "info", "paths", "servers"}
MAPPING_KEYS = {"old_pointer", "new_pointer", "type_same", "unit_same", "semantic_same"}
POINTER_PART = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
FORBIDDEN_SCHEMA = {"$ref", "allOf", "anyOf", "oneOf", "not"}


@dataclass
class Change:
    """분류된 변경 한 건. supported가 아니면 패치로 넘어가지 않는다."""

    change_id: str
    kind: str
    operation: dict
    location: str
    old_pointer: str
    new_pointer: str | None
    same_parent: bool
    type_same: bool | None
    unit_same: bool | None
    semantic_same: bool | None
    mapping_source: str | None
    supported: bool
    reason: str | None

    def as_dict(self) -> dict:
        """manifest changes 항목으로 쓸 딕셔너리를 만든다."""
        return {
            "change_id": self.change_id,
            "kind": self.kind,
            "operation": self.operation,
            "location": self.location,
            "old_pointer": self.old_pointer,
            "new_pointer": self.new_pointer,
            "same_parent": self.same_parent,
            "type_same": self.type_same,
            "unit_same": self.unit_same,
            "semantic_same": self.semantic_same,
            "mapping_source": self.mapping_source,
            "supported": self.supported,
            "reason": self.reason,
        }


@dataclass
class ClassifyResult:
    """분류 결과. reason_code가 있으면 이번 run은 hold다."""

    changes: list[Change] = field(default_factory=list)
    reason_code: str | None = None

    @property
    def supported(self) -> bool:
        """지원 변경이 하나 이상이고 hold 이유가 없을 때만 True다."""
        return self.reason_code is None and any(item.supported for item in self.changes)


def load_json_bytes(data: bytes):
    """중복 키를 거부하며 JSON을 읽고, 실패하면 H_UNSUPPORTED_SPEC을 돌려준다."""

    def pairs(seq):
        obj = {}
        for key, value in seq:
            if key in obj:
                raise ValueError("duplicate key")
            obj[key] = value
        return obj

    try:
        text = data.decode("utf-8")
        return json.loads(text, object_pairs_hook=pairs), None
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return None, H_UNSUPPORTED_SPEC


def _canon(value) -> str:
    """키 순서를 고정한 JSON 문자열로 구조 비교 값을 만든다."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _has_ref(value) -> bool:
    """문서 어디에든 $ref가 있으면 True를 돌려준다."""
    if isinstance(value, dict):
        if "$ref" in value:
            return True
        return any(_has_ref(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_ref(item) for item in value)
    return False


def _schema_forbidden(value) -> bool:
    """합치기 키워드나 $ref가 schema 아래에 있으면 True를 돌려준다."""
    if isinstance(value, dict):
        if FORBIDDEN_SCHEMA.intersection(value):
            return True
        return any(_schema_forbidden(item) for item in value.values())
    if isinstance(value, list):
        return any(_schema_forbidden(item) for item in value)
    return False


def _operations(doc: dict):
    """operation이 정확히 하나일 때만 (method, path, operation) 목록을 돌려준다."""
    paths = doc.get("paths")
    if not isinstance(paths, dict) or not paths:
        return None
    found = []
    for path, item in paths.items():
        if not isinstance(path, str) or not path.startswith("/") or not isinstance(item, dict):
            return None
        for key, value in item.items():
            if key in ("summary", "description", "servers", "parameters") or key.startswith("x-"):
                continue
            if key not in HTTP_METHODS or not isinstance(value, dict):
                return None
            found.append((key, path, value))
    if len(found) != 1:
        return None
    return found


def _response_ok(operation: dict) -> bool:
    """200 application/json inline object properties만 허용하는지 확인한다."""
    responses = operation.get("responses")
    if not isinstance(responses, dict) or set(responses) != {"200"}:
        return False
    body = responses["200"]
    if not isinstance(body, dict):
        return False
    content = body.get("content")
    if not isinstance(content, dict) or set(content) != {"application/json"}:
        return False
    media = content["application/json"]
    if not isinstance(media, dict):
        return False
    schema = media.get("schema")
    if not isinstance(schema, dict):
        return False
    if schema.get("type") != "object" or not isinstance(schema.get("properties"), dict):
        return False
    if _schema_forbidden(schema):
        return False
    return True


def _valid_doc(doc) -> bool:
    """MVP OpenAPI 문서 루트와 단일 operation 조건을 확인한다."""
    if not isinstance(doc, dict):
        return False
    if doc.get("openapi") != "3.0.3":
        return False
    if not set(doc).issubset(ALLOWED_ROOT):
        return False
    info = doc.get("info")
    if not isinstance(info, dict) or not isinstance(info.get("title"), str) or not isinstance(info.get("version"), str):
        return False
    if _has_ref(doc):
        return False
    ops = _operations(doc)
    if ops is None:
        return False
    return _response_ok(ops[0][2])


def _split_pointer(pointer: str):
    """점 구분 포인터를 키 목록으로 나누고, 형식이 아니면 None을 돌려준다."""
    if not isinstance(pointer, str) or pointer == "":
        return None
    parts = pointer.split(".")
    if any(POINTER_PART.fullmatch(part) is None for part in parts):
        return None
    return parts


def _change_id(method: str, path: str, old_pointer: str, new_pointer: str | None) -> str:
    """method, path, pointer로 안정적인 change_id를 만든다."""
    raw = f"{method}\n{path}\n{old_pointer}\n{new_pointer or ''}".encode("utf-8")
    return "chg-" + hashlib.sha256(raw).hexdigest()[:16]


def _parent_props(schema: dict, parent_keys: list[str]):
    """부모 객체 schema와 properties를 찾고, 없으면 None을 돌려준다."""
    node = schema
    for key in parent_keys:
        props = node.get("properties") if isinstance(node, dict) else None
        if not isinstance(props, dict) or key not in props or not isinstance(props[key], dict):
            return None
        node = props[key]
    if not isinstance(node, dict) or not isinstance(node.get("properties"), dict):
        return None
    return node


def _response_schema(operation: dict) -> dict:
    """operation의 inline 응답 schema 객체를 돌려준다."""
    return operation["responses"]["200"]["content"]["application/json"]["schema"]


def _rename_key(schema: dict, parent_keys: list[str], source: str, dest: str) -> bool:
    """부모 properties와 required 안의 키 이름만 바꾸고 값 객체는 유지한다."""
    parent = _parent_props(schema, parent_keys)
    if parent is None:
        return False
    props = parent["properties"]
    if source not in props or dest in props:
        return False
    parent["properties"] = {dest if key == source else key: value for key, value in props.items()}
    required = parent.get("required")
    if isinstance(required, list) and source in required:
        parent["required"] = [dest if key == source else key for key in required]
    return True


def _parse_mapping(mapping):
    """mapping 객체 또는 목록을 검사하고, 형식 오류면 reason을 돌려준다."""
    if mapping is None:
        return [], H_NO_MAPPING
    entries = mapping if isinstance(mapping, list) else [mapping]
    if not isinstance(mapping, (list, dict)):
        return [], H_METADATA_MISSING
    if isinstance(mapping, list) and not mapping:
        return [], None
    parsed = []
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != MAPPING_KEYS:
            return [], H_METADATA_MISSING
        for name in ("type_same", "unit_same", "semantic_same"):
            if not isinstance(entry[name], bool):
                return [], H_METADATA_MISSING
        if not isinstance(entry["old_pointer"], str) or not isinstance(entry["new_pointer"], str):
            return [], H_METADATA_MISSING
        parsed.append(entry)
    return parsed, None


def _make_change(method, path, entry, kind, same_parent, supported, reason) -> Change:
    """mapping 항목 하나로 Change 레코드를 만든다."""
    return Change(
        change_id=_change_id(method, path, entry["old_pointer"], entry["new_pointer"]),
        kind=kind,
        operation={"method": method, "path": path},
        location="response",
        old_pointer=entry["old_pointer"],
        new_pointer=entry["new_pointer"],
        same_parent=same_parent,
        type_same=entry["type_same"],
        unit_same=entry["unit_same"],
        semantic_same=entry["semantic_same"],
        mapping_source="provider_mapping",
        supported=supported,
        reason=reason,
    )


def classify_documents(old_doc, new_doc, mapping) -> ClassifyResult:
    """두 OpenAPI 문서와 mapping을 비교해 지원 변경 또는 hold 이유를 돌려준다."""
    if not _valid_doc(old_doc) or not _valid_doc(new_doc):
        return ClassifyResult(reason_code=H_UNSUPPORTED_SPEC)
    old_method, old_path, old_op = _operations(old_doc)[0]
    new_method, new_path, new_op = _operations(new_doc)[0]
    entries, map_err = _parse_mapping(mapping)
    if map_err:
        return ClassifyResult(reason_code=map_err)
    if not entries:
        same = old_method == new_method and old_path == new_path and _canon(old_op) == _canon(new_op)
        return ClassifyResult(reason_code=H_NO_CHANGE if same else H_NO_MAPPING)
    if (old_method, old_path) != (new_method, new_path):
        entry = entries[0]
        change = _make_change(old_method, old_path, entry, "field_moved", False, False, H_UNSUPPORTED_KIND)
        return ClassifyResult(changes=[change], reason_code=H_UNSUPPORTED_KIND)
    working = copy.deepcopy(new_op)
    changes = []
    hold = None
    for entry in entries:
        old_keys = _split_pointer(entry["old_pointer"])
        new_keys = _split_pointer(entry["new_pointer"])
        if old_keys is None or new_keys is None:
            changes.append(_make_change(old_method, old_path, entry, "field_renamed", False, False, H_METADATA_MISSING))
            hold = hold or H_METADATA_MISSING
            continue
        same_parent = old_keys[:-1] == new_keys[:-1]
        if not same_parent:
            changes.append(_make_change(old_method, old_path, entry, "field_moved", False, False, H_UNSUPPORTED_KIND))
            hold = hold or H_UNSUPPORTED_KIND
            continue
        if not (entry["type_same"] and entry["unit_same"] and entry["semantic_same"]):
            changes.append(_make_change(old_method, old_path, entry, "field_renamed", True, False, H_UNIT_OR_SEMANTIC))
            hold = hold or H_UNIT_OR_SEMANTIC
            continue
        old_parent = _parent_props(_response_schema(old_op), old_keys[:-1])
        new_parent = _parent_props(_response_schema(working), new_keys[:-1])
        if old_parent is None or new_parent is None:
            changes.append(_make_change(old_method, old_path, entry, "field_renamed", True, False, H_NO_MAPPING))
            hold = hold or H_NO_MAPPING
            continue
        old_props = old_parent["properties"]
        new_props = new_parent["properties"]
        if old_keys[-1] not in old_props or new_keys[-1] not in new_props:
            changes.append(_make_change(old_method, old_path, entry, "field_renamed", True, False, H_NO_MAPPING))
            hold = hold or H_NO_MAPPING
            continue
        if old_keys[-1] in new_props or new_keys[-1] in old_props:
            changes.append(_make_change(old_method, old_path, entry, "field_renamed", True, False, H_UNSUPPORTED_KIND))
            hold = hold or H_UNSUPPORTED_KIND
            continue
        if _canon(old_props[old_keys[-1]]) != _canon(new_props[new_keys[-1]]):
            changes.append(_make_change(old_method, old_path, entry, "field_renamed", True, False, H_UNIT_OR_SEMANTIC))
            hold = hold or H_UNIT_OR_SEMANTIC
            continue
        if not _rename_key(_response_schema(working), new_keys[:-1], new_keys[-1], old_keys[-1]):
            changes.append(_make_change(old_method, old_path, entry, "field_renamed", True, False, H_UNSUPPORTED_KIND))
            hold = hold or H_UNSUPPORTED_KIND
            continue
        changes.append(_make_change(old_method, old_path, entry, "field_renamed", True, True, None))
    if hold:
        return ClassifyResult(changes=changes, reason_code=hold)
    if _canon(old_op) != _canon(working):
        if changes:
            changes[-1].supported = False
            changes[-1].reason = H_UNSUPPORTED_KIND
        return ClassifyResult(changes=changes, reason_code=H_UNSUPPORTED_KIND)
    return ClassifyResult(changes=changes, reason_code=None)
