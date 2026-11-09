# 난이도: Difficult
# 학습 키워드: AST, Static Analysis, Subscript, Name Binding
"""응답 변수 파라미터의 직접 문자열 키 체인만 찾고, 별칭과 동적 키는 보류한다."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field


@dataclass
class Site:
    """직접 바인딩으로 확인된 키 접근 한 곳이다."""

    path: str
    line: int
    base: str
    keys: list[str]

    def as_dict(self) -> dict:
        """scan report에 넣을 위치 정보만 만든다. 소스 본문은 넣지 않는다."""
        return {"path": self.path, "line": self.line, "base": self.base, "keys": list(self.keys)}


@dataclass
class ScanResult:
    """파일 단위가 아니라 allowlist 전체의 탐색 결과다."""

    sites: list[Site] = field(default_factory=list)
    unresolved: bool = False


def as_chain(node):
    """Subscript와 .get(문자열) 체인이면 (변수명, 키 목록, 마지막 상수)를 돌려준다."""
    keys = []
    current = node
    last_const = None
    while True:
        if isinstance(current, ast.Subscript) and isinstance(current.slice, ast.Constant) and isinstance(current.slice.value, str):
            keys.append(current.slice.value)
            if last_const is None:
                last_const = current.slice
            current = current.value
            continue
        if (
            isinstance(current, ast.Call)
            and isinstance(current.func, ast.Attribute)
            and current.func.attr == "get"
            and len(current.args) == 1
            and not current.keywords
            and isinstance(current.args[0], ast.Constant)
            and isinstance(current.args[0].value, str)
        ):
            keys.append(current.args[0].value)
            if last_const is None:
                last_const = current.args[0]
            current = current.func.value
            continue
        break
    if not isinstance(current, ast.Name) or not keys or last_const is None:
        return None
    keys.reverse()
    return current.id, keys, last_const


def _assigned_names(fn: ast.AST) -> set[str]:
    """함수 안에서 다시 대입되는 이름을 모아 파라미터 재대입을 찾는다."""
    assigned = set()
    for node in _local_nodes(fn):
        targets = []
        if isinstance(node, ast.Assign):
            targets.extend(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets.append(node.target)
        elif isinstance(node, ast.AugAssign):
            targets.append(node.target)
        elif isinstance(node, ast.NamedExpr):
            targets.append(node.target)
        elif isinstance(node, ast.For):
            targets.append(node.target)
        for target in targets:
            if isinstance(target, ast.Name):
                assigned.add(target.id)
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            assigned.update(node.names)
    return assigned


def _local_nodes(fn: ast.AST):
    """중첩 함수 본문을 제외한 이 함수의 노드만 순서대로 돌려준다."""
    nested = set()
    for node in ast.walk(fn):
        if node is not fn and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            nested.update(ast.walk(node))
    for node in ast.walk(fn):
        if node is not fn and node not in nested:
            yield node


def _parameters(fn: ast.AST) -> set[str]:
    """함수와 lambda의 직접 파라미터 이름을 돌려준다."""
    args = fn.args
    names = [item.arg for item in list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs)]
    if args.vararg is not None:
        names.append(args.vararg.arg)
    if args.kwarg is not None:
        names.append(args.kwarg.arg)
    return set(names)


def _dynamic_access(fn: ast.AST) -> bool:
    """상수 문자열이 아닌 첨자나 .get이 있으면 True를 돌려준다."""
    for node in _local_nodes(fn):
        if isinstance(node, ast.Subscript) and not (
            isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str)
        ):
            return True
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get":
            simple = (
                len(node.args) == 1
                and not node.keywords
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            )
            if not simple:
                return True
    return False


def _module_level_chain(tree: ast.AST, pointers: list[list[str]]) -> bool:
    """함수 밖에 포인터 체인이 있으면 True를 돌려준다."""
    hidden = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            hidden.update(ast.walk(node))
    for node in ast.walk(tree):
        if node in hidden:
            continue
        parsed = as_chain(node)
        if parsed and parsed[1] in pointers:
            return True
    return False


def scan_source(path: str, source: str, pointers: list[list[str]]) -> ScanResult:
    """한 파일의 소스 문자열만 파싱해 직접 접근 위치 또는 unresolved를 돌려준다."""
    needles = {part for pointer in pointers for part in pointer}
    if not any(part in source for part in needles):
        return ScanResult()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ScanResult(unresolved=True)
    if _module_level_chain(tree, pointers):
        return ScanResult(unresolved=True)
    sites = []
    for fn in [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))]:
        if _dynamic_access(fn):
            return ScanResult(unresolved=True)
        params = _parameters(fn)
        assigned = _assigned_names(fn)
        for node in _local_nodes(fn):
            parsed = as_chain(node)
            if parsed is None or parsed[1] not in pointers:
                continue
            base, keys, const = parsed
            if base not in params or base in assigned:
                return ScanResult(unresolved=True)
            sites.append(Site(path=path, line=const.lineno, base=base, keys=list(keys)))
    if not sites:
        return ScanResult(unresolved=True)
    return ScanResult(sites=sites, unresolved=False)


def scan_files(files: list[tuple[str, str]], pointers: list[list[str]]) -> ScanResult:
    """여러 파일을 보고, 하나라도 unresolved면 사이트를 모두 버린다."""
    found = []
    for path, source in files:
        result = scan_source(path, source, pointers)
        if result.unresolved:
            return ScanResult(unresolved=True)
        found.extend(result.sites)
    if not found:
        return ScanResult(unresolved=True)
    return ScanResult(sites=found, unresolved=False)
