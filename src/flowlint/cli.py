"""FlowLint command-line interface."""

from __future__ import annotations

import argparse
import sys

from .parser import parse_all, find_flow_files
from .report import render_json, render_table
from .rules import RULE_DESCRIPTIONS, RULES, run_all_rules


def _print_rules() -> None:
    print("FlowLint rules:\n")
    for rule_id, description in RULE_DESCRIPTIONS.items():
        print(f"  {rule_id}  {description}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="flowlint",
        description="Static analysis for Salesforce Flow metadata XML.",
    )
    parser.add_argument(
        "path",
        nargs="?",
        help="File or directory containing .flow-meta.xml files to scan.",
    )
    parser.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        help="Output format (default: table).",
    )
    parser.add_argument(
        "--rules",
        action="store_true",
        help="List available rules and exit.",
    )
    parser.add_argument(
        "--exit-zero",
        action="store_true",
        help="Always exit 0, even if findings were reported.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.rules:
        _print_rules()
        return 0

    if not args.path:
        parser.error("a path is required unless --rules is given")

    flow_files = find_flow_files(args.path)
    if not flow_files:
        print(f"No .flow-meta.xml files found under: {args.path}", file=sys.stderr)
        return 0 if args.exit_zero else 1

    try:
        flows = parse_all(args.path)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    findings = run_all_rules(flows, list(RULES.keys()))

    if args.format == "json":
        print(render_json(findings))
    else:
        print(render_table(findings))

    if findings and not args.exit_zero:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
