# 난이도: Mid
# 학습 키워드: HTTP, JSON, Fail Closed
"""샘플 API의 요청 한계와 안전 오류. 본문은 로그에 남기지 않는다."""

from __future__ import annotations

import json

from patchpilot.web.analyze import analyze_sample
from patchpilot.web.samples import SAMPLE_IDS, samples_document

MAX_BODY_BYTES = 4 * 1024
NO_STORE = {"Cache-Control": "no-store"}

_MESSAGES = {
    "WEB_BAD_SAMPLE": "Unknown sample.",
    "WEB_PAYLOAD": "The request must be a sample id only.",
    "WEB_TIMEOUT": "The analysis timed out.",
    "WEB_OVERLOAD": "The analysis service is not accepting work.",
    "WEB_INTERNAL": "The analysis stopped because of an unexpected error.",
}


def error_document(code: str, http_status: int, user_message: str | None = None) -> dict:
    """§5 안전 오류. CLI outcome이나 stack을 넣지 않는다."""
    return {
        "ok": False,
        "error": {
            "http_status": http_status,
            "code": code,
            "user_message": user_message or _MESSAGES[code],
        },
    }


def handle(method: str, target: str, body: bytes, *, runner=analyze_sample) -> tuple[int, dict[str, str], bytes]:
    """허용된 두 경로만 처리한다. 예외 문자열은 응답에 넣지 않는다."""
    if target == "/api/v1/samples" and method == "GET":
        return 200, dict(NO_STORE), _dump(samples_document())
    if target != "/api/v1/analyze":
        return _fail(400, "WEB_PAYLOAD")
    if method != "POST":
        return _fail(400, "WEB_PAYLOAD")
    if len(body) > MAX_BODY_BYTES:
        return _fail(413, "WEB_PAYLOAD", "The request is larger than 4 KiB.")
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        return _fail(400, "WEB_PAYLOAD")
    if not isinstance(data, dict) or set(data) != {"sample_id"} or not isinstance(data.get("sample_id"), str):
        return _fail(400, "WEB_PAYLOAD")
    sample_id = data["sample_id"]
    if sample_id not in SAMPLE_IDS:
        return _fail(400, "WEB_BAD_SAMPLE")
    try:
        envelope = runner(sample_id)
    except Exception:
        return _fail(500, "WEB_INTERNAL")
    return 200, dict(NO_STORE), _dump(envelope)


def _fail(status: int, code: str, user_message: str | None = None) -> tuple[int, dict[str, str], bytes]:
    """오류도 no-store JSON이다."""
    return status, dict(NO_STORE), _dump(error_document(code, status, user_message))


def _dump(payload: dict) -> bytes:
    """응답 바이트. 호출자가 본문을 로그로 찍지 않는다."""
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")
