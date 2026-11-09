# 난이도: Difficult
# 학습 키워드: Path Traversal, Symlink, Hard Link, Canonical Path
"""절대경로, .., symlink, hardlink를 따라가지 않고 허용 root 안인지 확인한다."""

from __future__ import annotations

import os
import stat
from pathlib import Path


class BoundaryError(Exception):
    """경로 경계 위반. code는 E_PATH_BOUNDARY 또는 E_OUTPUT_ROOT다."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def validate_relative(raw: str, code: str = "E_PATH_BOUNDARY") -> None:
    """상대 경로 문자열에 절대경로, 빈 조각, . , .. 가 있으면 예외를 낸다."""
    if not isinstance(raw, str) or raw == "" or raw != raw.strip():
        raise BoundaryError(code)
    if "\x00" in raw or "\\" in raw or raw.startswith("/"):
        raise BoundaryError(code)
    if len(raw) >= 2 and raw[1] == ":":
        raise BoundaryError(code)
    parts = raw.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise BoundaryError(code)


def _join(base: Path, raw: str, code: str) -> Path:
    """base 아래에 raw를 붙이되 symlink와 hardlink는 거부한다."""
    validate_relative(raw, code)
    current = base
    parts = raw.split("/")
    for index, part in enumerate(parts):
        current = current / part
        try:
            st = current.lstat()
        except FileNotFoundError:
            if index != len(parts) - 1:
                raise BoundaryError(code)
            return current
        except OSError as exc:
            raise BoundaryError(code) from exc
        if stat.S_ISLNK(st.st_mode):
            raise BoundaryError(code)
        if stat.S_ISREG(st.st_mode) and st.st_nlink > 1:
            raise BoundaryError(code)
    return current


def lexical_path(cwd: Path, raw: str, code: str = "E_PATH_BOUNDARY") -> Path:
    """cwd 기준 경로를 만들고, 문자열이 안전하지 않으면 예외를 낸다."""
    validate_relative(raw, code)
    return cwd.joinpath(*raw.split("/"))


def require_real_dir(cwd: Path, raw: str, code: str = "E_PATH_BOUNDARY") -> Path:
    """존재하는 실제 디렉터리만 허용하고 symlink 디렉터리는 거부한다."""
    path = _join(cwd, raw, code)
    if path.is_symlink():
        raise BoundaryError(code)
    if not path.exists():
        raise FileNotFoundError(raw)
    st = path.lstat()
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        raise BoundaryError(code)
    return path


def require_real_file(root: Path, raw: str, code: str = "E_PATH_BOUNDARY") -> Path:
    """root 안의 일반 파일만 허용하고 symlink와 hardlink는 거부한다."""
    path = _join(root, raw, code)
    try:
        st = path.lstat()
    except FileNotFoundError as exc:
        raise FileNotFoundError(raw) from exc
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode) or st.st_nlink > 1:
        raise BoundaryError(code)
    if root != path and root not in path.parents:
        raise BoundaryError(code)
    return path


def paths_overlap(left: Path, right: Path) -> bool:
    """두 경로가 같거나 한쪽이 다른 쪽 아래이면 True를 돌려준다."""
    left_parts = left.parts
    right_parts = right.parts
    if left_parts == right_parts:
        return True
    if len(left_parts) < len(right_parts) and right_parts[: len(left_parts)] == left_parts:
        return True
    if len(right_parts) < len(left_parts) and left_parts[: len(right_parts)] == right_parts:
        return True
    return False


def prepare_out_dir(cwd: Path, raw: str, others: list[Path]) -> Path:
    """안전한 out_dir을 만들거나, 위험하면 만들지 않고 E_OUTPUT_ROOT를 낸다."""
    try:
        path = lexical_path(cwd, raw, "E_OUTPUT_ROOT")
    except BoundaryError:
        raise
    for other in others:
        if paths_overlap(path, other):
            raise BoundaryError("E_OUTPUT_ROOT")
    parent = path.parent
    try:
        parent_stat = parent.lstat()
    except FileNotFoundError as exc:
        raise BoundaryError("E_OUTPUT_ROOT") from exc
    if stat.S_ISLNK(parent_stat.st_mode) or not stat.S_ISDIR(parent_stat.st_mode):
        raise BoundaryError("E_OUTPUT_ROOT")
    if path.exists() or path.is_symlink():
        try:
            st = path.lstat()
        except FileNotFoundError as exc:
            raise BoundaryError("E_OUTPUT_ROOT") from exc
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
            raise BoundaryError("E_OUTPUT_ROOT")
    else:
        path.mkdir(mode=0o700)
    return path


def iter_checkout(root: Path):
    """checkout을 symlink를 따라가지 않고 순회해 (종류, 경로, stat)를 돌려준다."""
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            entries = list(os.scandir(current))
        except OSError as exc:
            raise BoundaryError("E_PATH_BOUNDARY") from exc
        for entry in entries:
            try:
                st = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise BoundaryError("E_PATH_BOUNDARY") from exc
            path = Path(entry.path)
            if stat.S_ISLNK(st.st_mode):
                yield ("symlink", path, st)
            elif stat.S_ISDIR(st.st_mode):
                stack.append(path)
            elif stat.S_ISREG(st.st_mode):
                yield ("file", path, st)


def glob_match(relative_path: str, pattern: str) -> bool:
    """전체 상대 경로에 glob을 맞춘다. 별은 슬래시를 넘지 않고 **만 넘긴다."""
    return _match_parts(relative_path.split("/"), pattern.split("/"))


def _segment_match(text: str, pattern: str) -> bool:
    """한 경로 조각이 *와 ? 패턴과 일치하는지 확인한다."""
    index_text = 0
    index_pattern = 0
    star_text = -1
    star_pattern = -1
    while index_text < len(text):
        if index_pattern < len(pattern) and pattern[index_pattern] == "*":
            star_text = index_text
            star_pattern = index_pattern
            index_pattern += 1
        elif index_pattern < len(pattern) and (
            pattern[index_pattern] == "?" or pattern[index_pattern] == text[index_text]
        ):
            index_text += 1
            index_pattern += 1
        elif star_pattern >= 0:
            star_text += 1
            index_text = star_text
            index_pattern = star_pattern + 1
        else:
            return False
    while index_pattern < len(pattern) and pattern[index_pattern] == "*":
        index_pattern += 1
    return index_pattern == len(pattern)


def _match_parts(path_parts: list[str], pattern_parts: list[str]) -> bool:
    """**가 0개 이상의 조각을 소비하는 경로 glob 일치를 계산한다."""
    if not pattern_parts:
        return not path_parts
    if pattern_parts[0] == "**":
        if _match_parts(path_parts, pattern_parts[1:]):
            return True
        if path_parts and _match_parts(path_parts[1:], pattern_parts):
            return True
        return False
    if not path_parts:
        return False
    if not _segment_match(path_parts[0], pattern_parts[0]):
        return False
    return _match_parts(path_parts[1:], pattern_parts[1:])
