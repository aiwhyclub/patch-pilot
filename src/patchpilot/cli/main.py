# 난이도: Mid
# 학습 키워드: argparse, CLI, Exit Code
"""patchpilot 명령행. 인자가 부족하면 manifest 없이 exit 2를 돌려준다."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from patchpilot.core.orchestrator import RunConfig, execute


def main(argv: list[str] | None = None) -> int:
    """run 하위 명령을 해석하고, 사용법 오류와 실제 run의 exit를 구분한다."""
    parser = argparse.ArgumentParser(prog="patchpilot", exit_on_error=False)
    sub = parser.add_subparsers(dest="command")
    run = sub.add_parser("run", exit_on_error=False)
    run.add_argument("--mode", default="A")
    run.add_argument("--specs-root", required=True)
    run.add_argument("--spec-old", required=True)
    run.add_argument("--spec-new", required=True)
    run.add_argument("--change-mapping", required=True)
    run.add_argument("--customer-repo", required=True)
    run.add_argument("--customer-base-ref", required=True)
    run.add_argument("--customer-checkout", required=True)
    run.add_argument("--lock-root", required=True)
    run.add_argument("--test-lock", required=True)
    run.add_argument("--allowlist", action="append", required=True)
    run.add_argument("--pr-target-repo", required=True)
    run.add_argument("--pr-target-base-branch", required=True)
    run.add_argument("--open-pr", default="false")
    run.add_argument("--model-send-consent", required=True)
    run.add_argument("--approval-ref", default=None)
    run.add_argument("--out-dir", default="patchpilot-run")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    except argparse.ArgumentError:
        return 2
    if args.command != "run":
        parser.print_usage(sys.stderr)
        return 2
    if args.mode not in ("A", "B", "C"):
        print("usage: mode must be A, B, or C", file=sys.stderr)
        return 2
    try:
        open_pr = _bool_text(args.open_pr)
        consent = _bool_text(args.model_send_consent)
    except ValueError:
        print("usage: booleans must be true or false", file=sys.stderr)
        return 2
    config = RunConfig(
        mode=args.mode,
        spec_old=args.spec_old,
        spec_new=args.spec_new,
        change_mapping=args.change_mapping,
        specs_root=args.specs_root,
        customer_repo=args.customer_repo,
        customer_base_ref=args.customer_base_ref,
        customer_checkout=args.customer_checkout,
        test_lock=args.test_lock,
        lock_root=args.lock_root,
        allowlist=list(args.allowlist),
        pr_repo=args.pr_target_repo,
        pr_base_branch=args.pr_target_base_branch,
        open_pr=open_pr,
        approval_ref=args.approval_ref,
        model_send_consent=consent,
        out_dir=args.out_dir,
        cwd=Path.cwd(),
    )
    return execute(config)


def _bool_text(value: str) -> bool:
    """true와 false만 bool로 바꾸고 다른 글자는 사용법 오류로 올린다."""
    if value == "true":
        return True
    if value == "false":
        return False
    raise ValueError(value)


if __name__ == "__main__":
    sys.exit(main())
