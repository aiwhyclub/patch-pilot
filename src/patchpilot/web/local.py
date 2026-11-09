# 난이도: Easy
# 학습 키워드: Uvicorn, Static Files
"""로컬 확인용 서버. Vercel 진입점은 app.py이며 이 파일은 배포 대상이 아니다."""

from __future__ import annotations

from pathlib import Path

from fastapi.staticfiles import StaticFiles

from patchpilot.web.app import app

PUBLIC = Path(__file__).resolve().parents[3] / "public"
app.mount("/", StaticFiles(directory=str(PUBLIC), html=True), name="site")


def main() -> None:
    """127.0.0.1:8000에서 API와 public UI를 함께 연다."""
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000, access_log=False, log_level="info")


if __name__ == "__main__":
    main()
