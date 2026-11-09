# 난이도: Mid
# 학습 키워드: JSON Schema, Fail Closed, Assertion
"""비신뢰 worker가 내놓은 한 줄 JSON의 형식만 검사하고, 기대값은 따로 비교한다."""

from __future__ import annotations

import json
import math

from patchpilot.schema.codes import E_WORKER_RESULT
from patchpilot.schema.limits import (
    WORKER_MAX_ELEMENT_CHARS,
    WORKER_MAX_JSON_BYTES,
    WORKER_MAX_VALUES,
)


def parse_worker_line(line: str):
    """한 줄 JSON이 계약 범위 안이면 dict를, 아니면 (None, E_WORKER_RESULT)를 돌려준다."""
    if not isinstance(line, str) or line.count("\n") > 1 or "\r" in line:
        return None, E_WORKER_RESULT
    raw = line[:-1] if line.endswith("\n") else line
    if "\n" in raw or raw == "":
        return None, E_WORKER_RESULT
    encoded = raw.encode("utf-8")
    if len(encoded) > WORKER_MAX_JSON_BYTES:
        return None, E_WORKER_RESULT
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        return None, E_WORKER_RESULT
    if not isinstance(obj, dict) or set(obj) != {"ok", "values", "stderr_digest"}:
        return None, E_WORKER_RESULT
    if not isinstance(obj["ok"], bool) or not isinstance(obj["stderr_digest"], str):
        return None, E_WORKER_RESULT
    if len(obj["stderr_digest"]) > WORKER_MAX_ELEMENT_CHARS:
        return None, E_WORKER_RESULT
    values = obj["values"]
    if not isinstance(values, list) or len(values) > WORKER_MAX_VALUES:
        return None, E_WORKER_RESULT
    for value in values:
        if not _element_ok(value):
            return None, E_WORKER_RESULT
    return obj, None


def _element_ok(value) -> bool:
    """null, bool, 유한 수, 길이 제한 문자열만 원소로 허용한다."""
    if value is None or isinstance(value, bool):
        return True
    if isinstance(value, str):
        return len(value) <= WORKER_MAX_ELEMENT_CHARS
    if isinstance(value, (int, float)) and math.isfinite(value):
        return len(json.dumps(value)) <= WORKER_MAX_ELEMENT_CHARS
    return False


def assert_expected(expected: list, worker: dict) -> bool:
    """values가 기대와 같고 ok가 True일 때만 통과시킨다. exit code는 받지 않는다."""
    if not isinstance(worker, dict) or not isinstance(expected, list):
        return False
    if worker.get("ok") is not True:
        return False
    return worker.get("values") == expected
