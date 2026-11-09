# 난이도: Difficult
# 학습 키워드: Unified Diff, AST Equality, Patch Validation
"""unified diff의 변경이 허용된 마지막 문자열 키뿐인지 AST와 토큰으로 확인한다."""

from __future__ import annotations

import ast
import copy
import io
import tokenize

from patchpilot.schema.codes import H_PATCH_REJECTED
from patchpilot.schema.redact import contains_secret
from patchpilot.scan.ast_scan import as_chain

FORBIDDEN_DIRS = {".github", ".git", "tests", "test", "fixtures", "fixture", "__tests__"}
FORBIDDEN_NAMES = {
    "conftest.py",
    "pytest.ini",
    "tox.ini",
    "setup.py",
    "setup.cfg",
    "pyproject.toml",
    "pipfile",
    "pipfile.lock",
    "poetry.lock",
    "requirements.txt",
    ".env",
    "mypy.ini",
    "ruff.toml",
}
_SKIP_TOKENS = {tokenize.ENCODING, tokenize.ENDMARKER}
_MAX_DIFF_BYTES = 1_000_000


def validate_patch(original_files: dict[str, str], diff_text: str, renames: list[dict]) -> str | None:
    """패치가 안전하면 None, 거절이면 H_PATCH_REJECTED를 돌려준다."""
    if not isinstance(diff_text, str) or len(diff_text.encode("utf-8")) > _MAX_DIFF_BYTES:
        return H_PATCH_REJECTED
    if contains_secret(diff_text):
        return H_PATCH_REJECTED
    parsed = _parse_diff(diff_text)
    if parsed is None:
        return H_PATCH_REJECTED
    expected = {}
    for item in renames:
        expected.setdefault(item["path"], []).append((list(item["old_keys"]), item["new_key"]))
    if set(parsed) != set(expected):
        return H_PATCH_REJECTED
    for path, hunks in parsed.items():
        if _forbidden_path(path) or path not in original_files:
            return H_PATCH_REJECTED
        try:
            updated = _apply(original_files[path], hunks)
        except ValueError:
            return H_PATCH_REJECTED
        if contains_secret(updated):
            return H_PATCH_REJECTED
        if not _tokens_ok(original_files[path], updated, expected[path]):
            return H_PATCH_REJECTED
        if not _ast_ok(original_files[path], updated, expected[path]):
            return H_PATCH_REJECTED
    return None


_PROTECTED_FILES = {"test.py", "tests.py", "fixture.py", "fixtures.py"}


def _forbidden_path(path: str) -> bool:
    """테스트, fixture, lock, CI, 설정, 의존성 경로면 True를 돌려준다.

    디렉터리와 파일 이름은 casefold로 비교한다. 이름 일부에 test가 들어간
    일반 모듈은 여기서 막지 않는다.
    """
    parts = [part.casefold() for part in path.split("/")]
    folded_dirs = {part.casefold() for part in FORBIDDEN_DIRS}
    folded_names = {part.casefold() for part in FORBIDDEN_NAMES}
    if any(part in folded_dirs or part.endswith(".lock") for part in parts):
        return True
    name = parts[-1]
    if name in folded_names or name in _PROTECTED_FILES:
        return True
    if name.startswith("test_") or name.endswith("_test.py"):
        return True
    if name.startswith("requirements") and name.endswith(".txt"):
        return True
    return False


def _parse_diff(diff_text: str):
    """허용한 unified diff만 경로별 hunk로 나누고, 그 외는 None을 돌려준다."""
    if "\x00" in diff_text:
        return None
    lines = diff_text.splitlines(keepends=True)
    patches = {}
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if stripped == "" or stripped.startswith("diff --git ") or stripped.startswith("index "):
            index += 1
            continue
        if stripped.startswith(
            (
                "old mode",
                "new mode",
                "new file",
                "deleted file",
                "rename from",
                "rename to",
                "copy from",
                "copy to",
                "similarity ",
                "dissimilarity ",
                "Binary files",
                "GIT binary",
            )
        ):
            return None
        if not line.startswith("--- "):
            return None
        old_path = _clean_path(line[4:])
        index += 1
        if index >= len(lines) or not lines[index].startswith("+++ "):
            return None
        new_path = _clean_path(lines[index][4:])
        index += 1
        if old_path is None or new_path is None or old_path != new_path:
            return None
        hunks = []
        while index < len(lines) and lines[index].startswith("@@"):
            hunk = [lines[index]]
            index += 1
            while index < len(lines) and not lines[index].startswith(("@@", "--- ", "diff --git ")):
                if lines[index].startswith("\\"):
                    return None
                hunk.append(lines[index])
                index += 1
            hunks.append(hunk)
        if not hunks or old_path in patches:
            return None
        patches[old_path] = hunks
    return patches or None


def _clean_path(raw: str):
    """a/ b/ 접두만 떼고, 절대경로와 상위 경로와 /dev/null은 거부한다."""
    path = raw.split("\t", 1)[0].strip()
    if path == "/dev/null" or path.startswith("/"):
        return None
    if path.startswith("a/") or path.startswith("b/"):
        path = path[2:]
    if path == "" or ".." in path.split("/") or path.startswith("/"):
        return None
    return path


def _apply(original: str, hunks) -> str:
    """hunk 문맥이 원문과 같을 때만 메모리 안에서 패치를 적용한다."""
    orig = original.splitlines(keepends=True)
    if original and not original.endswith("\n"):
        raise ValueError("newline")
    out = []
    cursor = 0
    for hunk in hunks:
        header = hunk[0]
        old_start, old_len, new_start, new_len = _hunk_header(header)
        if old_start is None:
            raise ValueError("header")
        old_index = 0 if old_start == 0 else old_start - 1
        if old_index < cursor:
            raise ValueError("overlap")
        out.extend(orig[cursor:old_index])
        cursor = old_index
        consumed = 0
        produced = 0
        for item in hunk[1:]:
            if item.startswith(" "):
                _consume(orig, cursor, item[1:])
                out.append(orig[cursor])
                cursor += 1
                consumed += 1
                produced += 1
            elif item.startswith("-"):
                _consume(orig, cursor, item[1:])
                cursor += 1
                consumed += 1
            elif item.startswith("+"):
                text = item[1:]
                if not text.endswith("\n"):
                    text += "\n"
                out.append(text)
                produced += 1
            else:
                raise ValueError("line")
        if consumed != old_len or produced != new_len:
            raise ValueError("count")
    out.extend(orig[cursor:])
    return "".join(out)


def _consume(orig: list[str], cursor: int, expected: str) -> None:
    """삭제 또는 문맥 줄이 원문과 같은지 확인하고 다르면 예외를 낸다."""
    if cursor >= len(orig):
        raise ValueError("range")
    left = orig[cursor].rstrip("\r\n")
    right = expected.rstrip("\r\n")
    if left != right:
        raise ValueError("context")


def _hunk_header(header: str):
    """@@ -시작,길이 +시작,길이 @@ 헤더를 정수 네 개로 읽는다."""
    if not header.startswith("@@"):
        return None, None, None, None
    try:
        body = header.split("@@")[1].strip()
        old_part, new_part = body.split(" ", 1)[0], body.split(" ", 1)[1].split(" ", 1)[0]
        old_start, old_len = _range(old_part[1:])
        new_start, new_len = _range(new_part[1:])
        return old_start, old_len, new_start, new_len
    except (IndexError, ValueError):
        return None, None, None, None


def _range(text: str):
    """시작 또는 시작,길이 형식을 두 정수로 나눈다."""
    if "," in text:
        start, length = text.split(",", 1)
        return int(start), int(length)
    return int(text), 1


def _tokens(source: str):
    """인코딩 토큰을 뺀 토큰 (종류, 문자열) 목록을 만든다."""
    out = []
    reader = io.BytesIO(source.encode("utf-8")).readline
    for token in tokenize.tokenize(reader):
        if token.type not in _SKIP_TOKENS:
            out.append((token.type, token.string))
    return out


def _tokens_ok(old: str, new: str, pairs: list[tuple[list[str], str]]) -> bool:
    """문자열 토큰의 허용된 키 교체 외 토큰이 같아야 True다."""
    left = _tokens(old)
    right = _tokens(new)
    if len(left) != len(right):
        return False
    changes = 0
    for before, after in zip(left, right):
        if before == after:
            continue
        if before[0] == tokenize.STRING and after[0] == tokenize.STRING and _key_swap(before[1], after[1], pairs):
            changes += 1
            continue
        return False
    return changes >= 1


def _key_swap(before: str, after: str, pairs) -> bool:
    """따옴표 스타일을 유지한 채 마지막 키만 바뀌었는지 확인한다."""
    if not before or not after or before[0] != after[0]:
        return False
    try:
        old_value = ast.literal_eval(before)
        new_value = ast.literal_eval(after)
    except (SyntaxError, ValueError):
        return False
    return any(old_value == keys[-1] and new_value == new_key for keys, new_key in pairs)


def _count(tree: ast.AST, keys: list[str]) -> int:
    """AST 안에서 정확히 그 키 체인인 접근 개수를 센다."""
    return sum(1 for node in ast.walk(tree) if (parsed := as_chain(node)) and parsed[1] == keys)


def _rewrite(tree: ast.AST, keys: list[str], replacement: str) -> int:
    """일치하는 체인의 마지막 문자열 상수만 다른 키로 바꾼 횟수를 돌려준다."""
    count = 0
    for node in ast.walk(tree):
        parsed = as_chain(node)
        if parsed and parsed[1] == keys:
            parsed[2].value = replacement
            count += 1
    return count


def _dump(node):
    """위치 정보를 제외한 AST 구조를 비교 가능한 중첩 튜플로 만든다."""
    if isinstance(node, ast.AST):
        fields = []
        for name, value in ast.iter_fields(node):
            if name in ("lineno", "col_offset", "end_lineno", "end_col_offset", "ctx"):
                continue
            fields.append((name, _dump(value)))
        return (type(node).__name__, tuple(fields))
    if isinstance(node, list):
        return tuple(_dump(item) for item in node)
    return node


def _ast_ok(old: str, new: str, pairs: list[tuple[list[str], str]]) -> bool:
    """새 AST의 마지막 키만 되돌렸을 때 이전 AST와 같으면 True다."""
    try:
        old_tree = ast.parse(old)
        new_tree = ast.parse(new)
    except SyntaxError:
        return False
    rewritten = copy.deepcopy(new_tree)
    for old_keys, new_key in pairs:
        new_keys = old_keys[:-1] + [new_key]
        if _count(old_tree, old_keys) < 1:
            return False
        if _count(new_tree, new_keys) != _count(old_tree, old_keys):
            return False
        if _count(new_tree, old_keys) != 0:
            return False
        if _rewrite(rewritten, new_keys, old_keys[-1]) != _count(old_tree, old_keys):
            return False
    return _dump(old_tree) == _dump(rewritten)
