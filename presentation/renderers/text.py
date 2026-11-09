# 난이도: Mid
# 학습 키워드: Read-only View, Plain Text, Accessibility
"""manifest를 읽어 stdout 요약과 report 문자열만 만든다. 파일을 쓰지 않는다."""

from __future__ import annotations

from patchpilot.schema.codes import (
    DATA_NOTICE,
    PR_ABSENT,
    PR_ABSENT_TEXT,
    PR_EXISTS,
    PR_NOT_ATTEMPTED,
    PR_NOT_ATTEMPTED_TEXT,
    PR_UNKNOWN,
    PR_UNKNOWN_TEXT,
    UNKNOWN_CODE_TEXT,
    reason_text,
)
from patchpilot.schema.redact import mask_text


def render_stdout(manifest: dict) -> str:
    """outcome, reason, 계약 안내, PR 존재 문장을 한 화면 문자열로 만든다."""
    outcome = _show(manifest.get("outcome"))
    code = manifest.get("reason_code")
    lines = [
        f"outcome: {outcome}",
        f"reason_code: {_show(code)}",
        f"message: {escape_text(reason_text(code) if isinstance(code, str) or code is None else str(code))}",
        f"pr: {escape_text(pr_sentence(manifest.get('pr') or {}))}",
        f"mode: {_show(manifest.get('mode'))}",
    ]
    return "\n".join(lines) + "\n"


def render_report(manifest: dict) -> str:
    """단계, 테스트 기대/실제, PR, 고지를 사람이 읽는 Markdown 문자열로 만든다."""
    lines = [
        "# PatchPilot run report",
        "",
        f"outcome: {_show(manifest.get('outcome'))}",
        f"reason_code: {_show(manifest.get('reason_code'))}",
        f"message: {escape_text(reason_text(manifest.get('reason_code')))}",
        "",
        "## Mode",
        f"requested mode: {_show(manifest.get('mode'))}",
        "",
        "## Stages",
    ]
    for stage in manifest.get("stages") or []:
        lines.append(
            "- {name}: status={status} attempts={attempts} reason={reason}".format(
                name=escape_text(stage.get("name")),
                status=escape_text(stage.get("status")),
                attempts=escape_text(stage.get("attempts")),
                reason=escape_text(stage.get("reason_code")),
            )
        )
    lines.extend(["", "## Tests"])
    tests = manifest.get("tests") or {}
    for name in ("baseline_v1", "unpatched_v2", "patched_v2"):
        item = tests.get(name) or {}
        lines.append(
            "- {name}: result={result} expected={expected}".format(
                name=name,
                result=escape_text(item.get("result")),
                expected=escape_text(item.get("expected")),
            )
        )
    lines.append("expected fail on unpatched_v2 is the reproduction target, not a passed stage.")
    lines.append("not_run is not pass or fail.")
    lines.extend(["", "## Changes"])
    changes = manifest.get("changes") or []
    if not changes:
        lines.append("- none recorded")
    for change in changes:
        lines.append(
            "- {kind} supported={supported} reason={reason} old={old} new={new}".format(
                kind=escape_text(change.get("kind")),
                supported=escape_text(change.get("supported")),
                reason=escape_text(change.get("reason")),
                old=escape_text(change.get("old_pointer")),
                new=escape_text(change.get("new_pointer")),
            )
        )
    lines.extend(["", "## Pull request", escape_text(pr_sentence(manifest.get("pr") or {})), "", "## Next action"])
    lines.append(escape_text(next_action(manifest)))
    lines.extend(["", "## Data notice", notice_text(manifest.get("data_notice")), ""])
    return "\n".join(lines)


def pr_sentence(pr: dict) -> str:
    """PR existence 네 가지를 계약 문장으로 바꾸고, URL이 없으면 URL을 만들지 않는다."""
    existence = pr.get("existence") if isinstance(pr, dict) else None
    if existence == PR_EXISTS:
        url = pr.get("url")
        if isinstance(url, str) and url:
            return url
        return "PR existence is exists but no verified URL was provided."
    if existence == PR_ABSENT:
        return PR_ABSENT_TEXT
    if existence == PR_UNKNOWN:
        return PR_UNKNOWN_TEXT
    if existence == PR_NOT_ATTEMPTED:
        return PR_NOT_ATTEMPTED_TEXT
    return f"{existence} {UNKNOWN_CODE_TEXT}"


def next_action(manifest: dict) -> str:
    """outcome과 blocked stage를 문장으로 잇는다. outcome 값은 다시 계산하지 않는다."""
    message = reason_text(manifest.get("reason_code"))
    blocked = [
        stage.get("name")
        for stage in manifest.get("stages") or []
        if isinstance(stage, dict) and stage.get("status") == "blocked"
    ]
    extra = ""
    if blocked:
        names = ", ".join(str(name) for name in blocked)
        extra += f" Blocked stages were not executed: {names}. not_run is not pass or fail."
    if manifest.get("outcome") == "patch_only":
        extra += " patch_only is not full success."
    if manifest.get("outcome") == "draft_pr_opened":
        extra += " Full success still requires the verified draft URL recorded in the manifest."
    return (message + extra).strip()


def notice_text(value) -> str:
    """계약 고지 원문이면 그대로 두고, 다른 값이면 가리고 escape한다."""
    if value == DATA_NOTICE:
        return DATA_NOTICE
    return escape_text(mask_text("" if value is None else str(value)))


def escape_text(value) -> str:
    """제어 문자와 backtick을 읽기 가능한 문자로 바꿔 색 코드가 실행되지 않게 한다."""
    if value is None:
        return "null"
    text = value if isinstance(value, str) else str(value)
    chars = []
    for char in text:
        code = ord(char)
        if char in ("\n", "\t"):
            chars.append(char)
        elif code < 32 or code == 127:
            chars.append("\\u%04x" % code)
        elif char == "`":
            chars.append("'")
        else:
            chars.append(char)
    return "".join(chars)


def _show(value) -> str:
    """None은 null로, 그 외는 escape한 한 줄 문자로 만든다."""
    if value is None:
        return "null"
    return escape_text(value).replace("\n", " ")
