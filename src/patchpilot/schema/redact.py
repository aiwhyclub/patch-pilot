# 난이도: Mid
# 학습 키워드: Secret Scanning, Redaction, Regular Expression
"""출력에 실릴 수 있는 비밀 패턴을 찾고 [REDACTED]로 가린다."""

from __future__ import annotations

import re

# 후보 패턴이다. 비밀의 모든 형태를 찾는 스캐너가 아니다.
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    re.compile(
        r"(?i)\b(api[_-]?key|secret|token|password)\b\s*[:=]\s*['\"][^'\"]{8,}['\"]"
    ),
    re.compile(
        r"(?i)\b(api[_-]?key|secret|token|password)\b\s*[:=]\s*[A-Za-z0-9+/=_.\-]{8,}"
    ),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]{16,}\b"),
)


def contains_secret(text: str) -> bool:
    """문자열에 비밀 후보가 있으면 True를 돌려준다."""
    return any(pattern.search(text) for pattern in SECRET_PATTERNS)


def mask_text(text: str) -> str:
    """비밀 후보를 [REDACTED]로 바꾼 문자열을 돌려준다."""
    masked = text
    for pattern in SECRET_PATTERNS:
        masked = pattern.sub("[REDACTED]", masked)
    return masked


def mask_obj(value, skip_keys=frozenset()):
    """딕셔너리와 목록 안의 문자열만 가리고 숫자와 구조는 유지한다."""
    if isinstance(value, str):
        return mask_text(value)
    if isinstance(value, list):
        return [mask_obj(item, skip_keys) for item in value]
    if isinstance(value, dict):
        masked = {}
        for key, item in value.items():
            if key in skip_keys:
                masked[key] = item
            else:
                masked[key] = mask_obj(item, skip_keys)
        return masked
    return value
