# 난이도: Easy
# 학습 키워드: HTML, Download, Same Origin
"""public 화면이 샘플 선택과 현재 envelope 다운로드만 하는지 확인한다."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PUBLIC = ROOT / "public"


class PageTests(unittest.TestCase):
    def test_page_is_a_sample_workflow(self) -> None:
        """업로드, 자유 입력, 외부 주소 없이 네 구획만 있다."""
        html = (PUBLIC / "index.html").read_text(encoding="utf-8")
        self.assertLess(html.find('id="sample-panel"'), html.find('id="analysis-panel"'))
        self.assertLess(html.find('id="analysis-panel"'), html.find('id="block-panel"'))
        self.assertLess(html.find('id="block-panel"'), html.find('id="export-panel"'))
        self.assertIn("샘플을 먼저 선택", html)
        self.assertIn("분석 후 내보내기 가능", html)
        self.assertIn("aria-live=\"polite\"", html)
        lowered = html.lower()
        self.assertNotIn("<textarea", lowered)
        self.assertNotIn("type=\"file\"", lowered)
        self.assertNotIn("type=\"url\"", lowered)
        self.assertNotIn("type=\"text\"", lowered)
        self.assertNotIn("pass", lowered)

    def test_script_calls_only_the_same_origin_api(self) -> None:
        """분석 요청은 두 API뿐이고, 늦은 응답과 이전 다운로드를 버린다."""
        script = (PUBLIC / "app.js").read_text(encoding="utf-8")
        urls = re.findall(r'fetch\(\s*"([^"]+)"', script)
        self.assertEqual(urls, ["/api/v1/samples", "/api/v1/analyze"])
        self.assertIn("if (mine !== requestSerial) return;", script)
        self.assertIn("URL.revokeObjectURL", script)
        self.assertIn("서버 응답 없음", script)
        self.assertIn("패치 미리보기 없음", script)
        self.assertIn("응답 형식이 완전하지 않습니다.", script)
        self.assertIn("다시 분석", script)
        self.assertNotIn("innerHTML", script)
        self.assertNotIn("eval(", script)
        self.assertNotIn("https://", script)
        self.assertNotIn("http://", script)
        css = (PUBLIC / "app.css").read_text(encoding="utf-8")
        self.assertIn("[hidden] { display: none !important; }", css)
        self.assertIn("overflow-x: auto", css)
        self.assertIn("white-space: pre", css)
        self.assertIn("@media (min-width: 1024px)", css)
        self.assertIn("@media (max-width: 767px)", css)


if __name__ == "__main__":
    unittest.main()
