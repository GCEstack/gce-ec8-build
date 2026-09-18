"""WS5 binding CLI entry point (P20 §6).

    python -m ecai.binding verify --root <freeze_root> [--expect-slate YYYY-MM-DD]

Exit codes: 0 = bound (record printed), 2 = rejected (reason printed).
This is the WS5 deliverable command; the full `ecai` CLI is Phase 6.
"""

from __future__ import annotations

import argparse
import json
import sys

from .adapter import bind
from .models import BindingRejected


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ecai.binding")
    sub = parser.add_subparsers(dest="command", required=True)
    verify = sub.add_parser("verify", help="bind and verify a frozen dataset")
    verify.add_argument("--root", required=True, help="frozen dataset root")
    verify.add_argument(
        "--expect-slate",
        default=None,
        help="pin the expected slate date (YYYY-MM-DD)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "verify":
        try:
            record = bind(args.root, expect_slate=args.expect_slate)
        except BindingRejected as rejected:
            print(json.dumps(rejected.to_dict(), indent=2))
            return 2
        print(json.dumps(record.to_dict(), indent=2))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
