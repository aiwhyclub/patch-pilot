# 난이도: Difficult
# 학습 키워드: AST, Static Analysis, Subscript, Name Binding
"""승인 operation의 JSON 응답 변수에 직접 붙은 문자열 키만 찾는다.

C2a의 응답 객체 변수는 함수 파라미터가 아니다. 이 모듈이 사이트로 인정하는
변수는 범위 안에서 한 번만 대입되고, 그 값이 승인된 method/path의 고정 호출에
대한 인자 없는 .json() 호출인 이름이다. 별칭, 재대입, 동적 키, 다른 operation,
임의 파라미터는 사이트로 세지 않고 H_UNRESOLVED로 올린다.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field


_HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}
_META_NAMES = {"eval", "exec", "getattr", "setattr"}


@dataclass
class Site:
    """직접 JSON 응답 변수에서 확인된 키 접근 한 곳이다."""

    path: str
    line: int
    base: str
    keys: list[str]
    binding: str = "direct_json_response"

    def as_dict(self) -> dict:
        """scan report에 넣을 위치 정보만 만든다. 소스 본문은 넣지 않는다."""
        return {
            "path": self.path,
            "line": self.line,
            "base": self.base,
            "keys": list(self.keys),
            "binding": self.binding,
        }


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


def _parameters(fn: ast.AST) -> set[str]:
    """함수와 lambda의 직접 파라미터 이름을 돌려준다."""
    args = fn.args
    names = [item.arg for item in list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs)]
    if args.vararg is not None:
        names.append(args.vararg.arg)
    if args.kwarg is not None:
        names.append(args.kwarg.arg)
    return set(names)


def _operation_ok(operation) -> bool:
    """분류기가 넘긴 (method, path) 한 쌍만 승인 operation으로 받는다."""
    if not isinstance(operation, tuple) or len(operation) != 2:
        return False
    method, path = operation
    if method not in _HTTP_METHODS or not isinstance(path, str):
        return False
    if not path.startswith("/") or ".." in path.split("/"):
        return False
    return True


def _path_equal(value: str, expected: str) -> bool:
    """문자열 인자가 operation path 자체이거나 그 path만 가진 http(s) URL인지 본다."""
    if value == expected:
        return True
    if not value.startswith(("http://", "https://")):
        return False
    rest = value.split("://", 1)[1]
    slash = rest.find("/")
    if slash < 0:
        return False
    path = rest[slash:].split("?", 1)[0].split("#", 1)[0]
    return path == expected


def _string_constants(call: ast.Call) -> dict | None:
    """인자가 모두 상수일 때만 키워드 문자열과 상수 목록을 돌려준다."""
    if any(item.arg is None for item in call.keywords):
        return None
    values = list(call.args) + [item.value for item in call.keywords]
    if any(not isinstance(value, ast.Constant) for value in values):
        return None
    keywords = {item.arg: item.value.value for item in call.keywords if isinstance(item.value.value, str)}
    return {"keywords": keywords, "values": values}


def _is_fixed_call(expr: ast.AST, method: str, path: str) -> bool:
    """method는 호출 속성 또는 request의 method 칸, path는 URL 칸만 본다.

    note= 같은 다른 키워드에 path가 있어도 그 호출의 대상이 아니다.
    path와 같은 문자열이 둘 이상이면 대상을 하나로 정하지 않는다.
    계약이 callee 라이브러리를 정하지 않으므로 속성 이름이 method인 기존 모양은 유지한다.
    """
    if not isinstance(expr, ast.Call):
        return False
    parsed = _string_constants(expr)
    if parsed is None:
        return False
    path_hits = [
        value.value
        for value in parsed["values"]
        if isinstance(value.value, str) and _path_equal(value.value, path)
    ]
    if len(path_hits) != 1:
        return False
    keywords = parsed["keywords"]
    attr = expr.func.attr.lower() if isinstance(expr.func, ast.Attribute) else None
    if attr in _HTTP_METHODS:
        if attr != method or keywords.get("method", method).lower() != method:
            return False
        if expr.args and isinstance(expr.args[0].value, str):
            url = expr.args[0].value
        else:
            url = keywords.get("url")
        return isinstance(url, str) and _path_equal(url, path)
    if attr == "request":
        method_token = keywords.get("method")
        if method_token is None and expr.args and isinstance(expr.args[0].value, str):
            method_token = expr.args[0].value
        if not isinstance(method_token, str) or method_token.lower() != method:
            return False
        if "url" in keywords:
            url = keywords["url"]
        elif len(expr.args) >= 2 and isinstance(expr.args[1].value, str):
            url = expr.args[1].value
        else:
            return False
        return _path_equal(url, path)
    return False


def _is_direct_json(expr: ast.AST, fixed_names: set[str], method: str, path: str) -> bool:
    """인자 없는 .json()이 고정 호출이거나 그 호출을 담은 이름에 바로 붙으면 True다."""
    if not isinstance(expr, ast.Call) or expr.args or expr.keywords:
        return False
    func = expr.func
    if not isinstance(func, ast.Attribute) or func.attr != "json":
        return False
    receiver = func.value
    if _is_fixed_call(receiver, method, path):
        return True
    return isinstance(receiver, ast.Name) and receiver.id in fixed_names


def _simple_assign(node: ast.AST):
    """이름 하나 = 값 하나인 대입만 (이름, 값)으로 돌려주고 아니면 None이다."""
    if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
        return node.targets[0].id, node.value
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
        return node.target.id, node.value
    return None


def _store_names(target: ast.AST) -> set[str]:
    """대입 대상 중 Store인 이름만 모은다. 대상 안의 Load는 바인딩이 아니다."""
    names = set()
    for inner in ast.walk(target):
        if isinstance(inner, ast.Name) and isinstance(inner.ctx, ast.Store):
            names.add(inner.id)
    return names


def _pattern_bindings(pattern: ast.AST | None) -> set[str]:
    """match 패턴이 이 범위에 실제로 묶는 이름만 모은다."""
    names = set()
    if isinstance(pattern, ast.MatchAs):
        if pattern.name:
            names.add(pattern.name)
        names.update(_pattern_bindings(pattern.pattern))
    elif isinstance(pattern, ast.MatchStar) and pattern.name:
        names.add(pattern.name)
    elif isinstance(pattern, ast.MatchMapping):
        for sub in pattern.patterns:
            names.update(_pattern_bindings(sub))
        if pattern.rest:
            names.add(pattern.rest)
    elif isinstance(pattern, (ast.MatchSequence, ast.MatchOr)):
        for sub in pattern.patterns:
            names.update(_pattern_bindings(sub))
    elif isinstance(pattern, ast.MatchClass):
        for sub in list(pattern.patterns) + list(pattern.kwd_patterns):
            names.update(_pattern_bindings(sub))
    return names


def _unstable_names(node: ast.AST) -> set[str]:
    """한 번 대입이 아닌 바인딩 이름을 모아 재대입으로 취급한다."""
    names = set()
    targets = []
    if isinstance(node, ast.Assign) and not (len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)):
        targets.extend(node.targets)
    elif isinstance(node, ast.AnnAssign) and node.value is None:
        targets.append(node.target)
    elif isinstance(node, (ast.AugAssign, ast.NamedExpr, ast.For, ast.AsyncFor)):
        targets.append(node.target)
    elif isinstance(node, (ast.With, ast.AsyncWith)):
        for item in node.items:
            if item.optional_vars is not None:
                targets.append(item.optional_vars)
    elif isinstance(node, (ast.Global, ast.Nonlocal)):
        names.update(node.names)
    elif isinstance(node, ast.Delete):
        targets.extend(node.targets)
    elif isinstance(node, ast.ExceptHandler) and node.name:
        names.add(node.name)
    elif isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
        for generator in node.generators:
            names.update(_store_names(generator.target))
    elif isinstance(node, ast.Import):
        for alias in node.names:
            names.add(alias.asname or alias.name.split(".")[0])
    elif isinstance(node, ast.ImportFrom):
        for alias in node.names:
            if alias.name == "*":
                names.add("*")
            else:
                names.add(alias.asname or alias.name)
    elif isinstance(node, ast.Match):
        for case in node.cases:
            names.update(_pattern_bindings(case.pattern))
    for target in targets:
        names.update(_store_names(target))
    return names


def _proper_prefix(keys: list[str], pointers: list[list[str]]) -> bool:
    """포인터보다 짧은 앞부분이면 True다. 전체 체인과 다른 키는 접두가 아니다."""
    for pointer in pointers:
        if 0 < len(keys) < len(pointer) and pointer[: len(keys)] == keys:
            return True
    return False


def _chain_root(node: ast.AST):
    """상수 키 체인의 맨 앞 Name 노드를 돌려준다. 없으면 None이다."""
    current = node
    while True:
        if isinstance(current, ast.Subscript):
            current = current.value
            continue
        if isinstance(current, ast.Call) and isinstance(current.func, ast.Attribute) and current.func.attr == "get":
            current = current.func.value
            continue
        if isinstance(current, ast.Name):
            return current
        return None


def _root_name(node: ast.AST) -> str | None:
    """첨자와 .get을 걷어 낸 맨 앞 이름이 있으면 돌려준다."""
    current = node
    while True:
        if isinstance(current, ast.Subscript):
            current = current.value
            continue
        if isinstance(current, ast.Call) and isinstance(current.func, ast.Attribute) and current.func.attr == "get":
            current = current.func.value
            continue
        if isinstance(current, ast.Name):
            return current.id
        return None


def _dynamic_on(node: ast.AST, names: set[str]) -> bool:
    """응답 변수에서 상수 문자열이 아닌 첨자나 .get이 나오면 True다."""
    if isinstance(node, ast.Subscript):
        if _root_name(node) in names and not (
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
        if not simple and _root_name(node) in names:
            return True
    return False


def _metaprogramming(node: ast.AST) -> bool:
    """eval, exec, getattr, setattr 호출이면 True다."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name) and func.id in _META_NAMES:
        return True
    return isinstance(func, ast.Attribute) and func.attr in _META_NAMES


def _collect_defaults(args: ast.arguments, collect) -> None:
    """기본값은 그 함수 안이 아니라 바깥 범위의 식으로 모은다."""
    for value in list(args.defaults) + list(args.kw_defaults):
        if value is not None:
            collect(value)


def _walk(nodes: list[ast.AST], params: set[str], sites: list[Site], problems: list[str], path: str, pointers, operation) -> None:
    """한 범위의 직접 대입만 응답 변수로 보고, 중첩 함수는 따로 본다."""
    local = []
    nested = []

    def collect(node: ast.AST) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            nested.append((node.body, _parameters(node)))
            for deco in node.decorator_list:
                collect(deco)
            _collect_defaults(node.args, collect)
            return
        if isinstance(node, ast.ClassDef):
            nested.append((node.body, set()))
            for deco in node.decorator_list:
                collect(deco)
            return
        if isinstance(node, ast.Lambda):
            nested.append(([node.body], _parameters(node)))
            _collect_defaults(node.args, collect)
            return
        local.append(node)
        for child in ast.iter_child_nodes(node):
            collect(child)

    for node in nodes:
        collect(node)
    method, op_path = operation
    simple: dict[str, list[ast.AST]] = {}
    unstable = set(params)
    for node in local:
        if _metaprogramming(node):
            problems.append("metaprogramming")
        pair = _simple_assign(node)
        if pair is not None:
            simple.setdefault(pair[0], []).append(pair[1])
        unstable.update(_unstable_names(node))
    if "*" in unstable:
        problems.append("alias")
        unstable.discard("*")
    fixed_names = set()
    for name, exprs in simple.items():
        if name in unstable or len(exprs) != 1:
            continue
        if _is_fixed_call(exprs[0], method, op_path):
            fixed_names.add(name)
    response_vars = set()
    for name, exprs in simple.items():
        if name in unstable or len(exprs) != 1:
            continue
        if _is_direct_json(exprs[0], fixed_names, method, op_path):
            response_vars.add(name)
    for name, exprs in simple.items():
        if len(exprs) == 1 and isinstance(exprs[0], ast.Name) and exprs[0].id in response_vars:
            problems.append("alias")
    chain_roots = set()
    continued = set()
    for node in local:
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
            continued.add(id(node.value))
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and len(node.args) == 1
            and not node.keywords
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            continued.add(id(node.func.value))
        parsed = as_chain(node)
        if parsed is None:
            continue
        root = _chain_root(node)
        if root is not None:
            chain_roots.add(id(root))
        base, keys, _const = parsed
        if base in response_vars and _proper_prefix(keys, pointers) and id(node) not in continued:
            problems.append("alias")
    for node in local:
        if (
            isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Load)
            and node.id in response_vars
            and id(node) not in chain_roots
        ):
            problems.append("alias")
    for node in local:
        if _dynamic_on(node, response_vars):
            problems.append("dynamic")
        parsed = as_chain(node)
        if parsed is None or parsed[1] not in pointers:
            continue
        base, keys, const = parsed
        if base not in response_vars:
            problems.append("not_direct")
            continue
        sites.append(Site(path=path, line=const.lineno, base=base, keys=list(keys)))
    for body, nested_params in nested:
        _walk(body, nested_params, sites, problems, path, pointers, operation)


def scan_source(path: str, source: str, pointers: list[list[str]], operation: tuple[str, str]) -> ScanResult:
    """한 파일의 소스 문자열만 파싱해 직접 접근 위치 또는 unresolved를 돌려준다."""
    if not _operation_ok(operation):
        return ScanResult(unresolved=True)
    needles = {part for pointer in pointers for part in pointer}
    if not needles or not any(part in source for part in needles):
        return ScanResult()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ScanResult(unresolved=True)
    sites: list[Site] = []
    problems: list[str] = []
    _walk(tree.body, set(), sites, problems, path, [list(item) for item in pointers], operation)
    if problems or not sites:
        return ScanResult(unresolved=True)
    return ScanResult(sites=sites, unresolved=False)


def scan_files(files: list[tuple[str, str]], pointers: list[list[str]], operation: tuple[str, str]) -> ScanResult:
    """여러 파일을 보고, 하나라도 unresolved면 사이트를 모두 버린다."""
    if not pointers or not _operation_ok(operation):
        return ScanResult(unresolved=True)
    found = []
    for path, source in files:
        result = scan_source(path, source, pointers, operation)
        if result.unresolved:
            return ScanResult(unresolved=True)
        found.extend(result.sites)
    if not found:
        return ScanResult(unresolved=True)
    return ScanResult(sites=found, unresolved=False)
