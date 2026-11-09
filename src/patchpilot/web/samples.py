# 난이도: Mid
# 학습 키워드: Fixture, OpenAPI, Synthetic
"""브라우저가 고를 수 있는 팀 합성 샘플. 고객 코드나 URL을 받지 않는다."""

from __future__ import annotations

import json

from patchpilot.schema.codes import DATA_NOTICE

SPEC_OLD = {
    "openapi": "3.0.3",
    "info": {"title": "team-synthetic", "version": "1"},
    "paths": {
        "/v1/weather": {
            "get": {
                "operationId": "getWeather",
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
                                            "required": ["temperature", "windspeed"],
                                            "properties": {
                                                "temperature": {"type": "number"},
                                                "windspeed": {"type": "number"},
                                            },
                                        }
                                    },
                                }
                            }
                        },
                    }
                },
            }
        }
    },
}

SPEC_NEW = {
    "openapi": "3.0.3",
    "info": {"title": "team-synthetic", "version": "2"},
    "paths": {
        "/v1/weather": {
            "get": {
                "operationId": "getWeather",
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
                                            "required": ["temperature_2m", "windspeed"],
                                            "properties": {
                                                "temperature_2m": {"type": "number"},
                                                "windspeed": {"type": "number"},
                                            },
                                        }
                                    },
                                }
                            }
                        },
                    }
                },
            }
        }
    },
}

MAPPING = {
    "old_pointer": "current_weather.temperature",
    "new_pointer": "current_weather.temperature_2m",
    "type_same": True,
    "unit_same": True,
    "semantic_same": True,
}

SOURCE_DIRECT = (
    "def read_temp():\n"
    "    body = requests.get(\"https://example.test/v1/weather\").json()\n"
    "    return body[\"current_weather\"][\"temperature\"]\n"
)

SOURCE_SPLIT = (
    "def read_temp():\n"
    "    body = requests.get(\"https://example.test/v1/weather\").json()\n"
    "    saved = body[\"current_weather\"]\n"
    "    shown = body[\"current_weather\"][\"temperature\"]\n"
    "    hidden = saved[\"temperature\"]\n"
    "    return shown\n"
)

CLIENT_PATH = "client.py"


def _pretty(document) -> str:
    """미리보기 문자열. 분석은 같은 객체를 다시 파싱하지 않고 그대로 쓴다."""
    return json.dumps(document, ensure_ascii=False, indent=2) + "\n"


def _sample(sample_id: str, label: str, kind: str, source: str) -> dict:
    """목록과 미리보기를 한 샘플로 묶는다. 미리보기는 읽기 전용이다."""
    return {
        "id": sample_id,
        "label": label,
        "kind": kind,
        "spec_old": SPEC_OLD,
        "spec_new": SPEC_NEW,
        "mapping": MAPPING,
        "source": source,
        "preview": {
            "spec_old": _pretty(SPEC_OLD),
            "spec_new": _pretty(SPEC_NEW),
            "mapping": _pretty(MAPPING),
            "source": source,
        },
    }


SAMPLES = {
    "supported_rename": _sample(
        "supported_rename",
        "팀 합성: 직접 JSON 키 사용",
        "supported_rename",
        SOURCE_DIRECT,
    ),
    "split_parent_alias": _sample(
        "split_parent_alias",
        "팀 합성: 부모 조각을 나눈 이름",
        "hold_variant",
        SOURCE_SPLIT,
    ),
}

SAMPLE_IDS = tuple(SAMPLES)


def samples_document() -> dict:
    """GET /api/v1/samples 본문. 필수 필드 외에 읽기 전용 미리보기와 고지를 붙인다."""
    listed = []
    for sample_id in SAMPLE_IDS:
        item = SAMPLES[sample_id]
        listed.append(
            {
                "id": item["id"],
                "label": item["label"],
                "kind": item["kind"],
                "preview": item["preview"],
            }
        )
    return {"samples": listed, "data_notice": DATA_NOTICE}
