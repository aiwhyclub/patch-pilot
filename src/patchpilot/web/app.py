# 난이도: Mid
# 학습 키워드: FastAPI, ASGI, Cache-Control
"""Vercel이 읽는 FastAPI 앱. public 디렉터리는 CDN이 담당한다."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import Response

from patchpilot.web.http import MAX_BODY_BYTES, handle

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


def _response(status: int, headers: dict[str, str], payload: bytes) -> Response:
    """JSON 바이트를 그대로 돌려준다."""
    return Response(content=payload, status_code=status, media_type="application/json", headers=headers)


@app.get("/api/v1/samples")
def list_samples() -> Response:
    """고정 샘플 목록."""
    status, headers, payload = handle("GET", "/api/v1/samples", b"")
    return _response(status, headers, payload)


@app.post("/api/v1/analyze")
async def analyze(request: Request) -> Response:
    """sample_id만 받아 정적 분석을 실행한다. 본문은 로그에 남기지 않는다."""
    length = request.headers.get("content-length")
    if length is not None:
        try:
            declared = int(length)
        except ValueError:
            declared = MAX_BODY_BYTES + 1
        if declared > MAX_BODY_BYTES:
            status, headers, payload = handle("POST", "/api/v1/analyze", b"x" * (MAX_BODY_BYTES + 1))
            return _response(status, headers, payload)
    body = await request.body()
    status, headers, payload = handle("POST", "/api/v1/analyze", body)
    return _response(status, headers, payload)
