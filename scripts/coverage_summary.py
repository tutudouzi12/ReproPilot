from __future__ import annotations

import argparse
import json
from pathlib import Path


def percentage(covered: int, total: int) -> float:
    return 100.0 if total == 0 else covered / total * 100


def coverage_threshold(value: str) -> float:
    threshold = float(value)
    if not 0 <= threshold <= 100:
        raise argparse.ArgumentTypeError("coverage threshold must be between 0 and 100")
    return threshold


def main() -> None:
    parser = argparse.ArgumentParser(description="Print separate line and branch coverage totals.")
    parser.add_argument("label")
    parser.add_argument("report", type=Path)
    parser.add_argument("--min-line", type=coverage_threshold)
    parser.add_argument("--min-branch", type=coverage_threshold)
    args = parser.parse_args()

    totals = json.loads(args.report.read_text(encoding="utf-8"))["totals"]
    line_coverage = percentage(totals["covered_lines"], totals["num_statements"])
    branch_coverage = percentage(totals["covered_branches"], totals["num_branches"])
    print(f"{args.label}: line coverage {line_coverage:.2f}%, branch coverage {branch_coverage:.2f}%")

    failures = []
    if args.min_line is not None and line_coverage < args.min_line:
        failures.append(f"line coverage {line_coverage:.2f}% is below {args.min_line:.2f}%")
    if args.min_branch is not None and branch_coverage < args.min_branch:
        failures.append(f"branch coverage {branch_coverage:.2f}% is below {args.min_branch:.2f}%")
    if failures:
        raise SystemExit(f"{args.label} coverage gate failed: {'; '.join(failures)}")


if __name__ == "__main__":
    main()
