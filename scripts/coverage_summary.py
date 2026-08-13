from __future__ import annotations

import argparse
import json
from pathlib import Path


def percentage(covered: int, total: int) -> float:
    return 100.0 if total == 0 else covered / total * 100


def main() -> None:
    parser = argparse.ArgumentParser(description="Print separate line and branch coverage totals.")
    parser.add_argument("label")
    parser.add_argument("report", type=Path)
    args = parser.parse_args()

    totals = json.loads(args.report.read_text(encoding="utf-8"))["totals"]
    line_coverage = percentage(totals["covered_lines"], totals["num_statements"])
    branch_coverage = percentage(totals["covered_branches"], totals["num_branches"])
    print(f"{args.label}: line coverage {line_coverage:.2f}%, branch coverage {branch_coverage:.2f}%")


if __name__ == "__main__":
    main()
