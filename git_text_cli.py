#!/usr/bin/env python3
"""Generate a deterministic commit-message draft from a local Git diff."""

import argparse
import sys
from gittxt.core import collect_changes, generate_draft
from gittxt.logger import log_error
from gittxt.autonomous import generate_autonomous


def main():
    parser = argparse.ArgumentParser(
        description="Draft a commit message from changes in the current Git repository."
    )
    parser.add_argument(
        "--staged",
        action="store_true",
        help="Analyze only staged changes (default: all tracked changes vs HEAD).",
    )
    parser.add_argument(
        "--stat-only",
        action="store_true",
        help="Print only the change summary, not a commit-message draft.",
    )
    parser.add_argument(
        "--analyze",
        action="store_true",
        help="Analyze diff for functions, conditions, validations, imports, and config changes.",
    )
    parser.add_argument(
        "--autonomous",
        action="store_true",
        help="Use autonomous AST-based fact extraction and compositional generation (no templates).",
    )
    args = parser.parse_args()

    try:
        data = collect_changes(staged=args.staged)
        if not data["changed_files"] and not data["untracked"]:
            print("No changes found.")
            return 0

        if args.autonomous:
            result = generate_autonomous(data["diff"], staged=args.staged, untracked=data["untracked"])
            print(result["text"])
            if result["confidence"] < 1.0:
                print(f"[confidence: {result['confidence']:.2f} · {result.get('band', 'unlabeled')}]")
            return 0

        draft = generate_draft(data, analyze=args.analyze)

        if args.stat_only:
            print(draft["summary"])
            return 0

        print(draft["subject"])
        print()
        print(draft["summary"])
        print()
        print("Files:")
        for path in draft["files"]:
            marker = " (untracked)" if path in draft["untracked"] else ""
            print(f"- {path}{marker}")

        if args.analyze and "analysis" in draft:
            print()
            print("Analysis:")
            for category in ["functions", "conditions", "validations", "imports", "config"]:
                items = draft["analysis"][category]
                if items:
                    print(f"  {category.capitalize()}:")
                    for item in items[:10]:
                        print(f"    - {item}")
                    if len(items) > 10:
                        print(f"    ... and {len(items) - 10} more")
        return 0
    except Exception as exc:
        log_error("main", exc)
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
