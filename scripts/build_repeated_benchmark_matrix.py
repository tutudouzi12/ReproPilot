from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.repeated_benchmark import build_repeated_matrix, load_campaign, planned_cells  # noqa: E402


def write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}-{os.getpid()}.tmp"
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate or build a controlled repeated repository benchmark matrix.")
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--run", type=Path, help="campaign-run.json produced by the repeated benchmark runner")
    parser.add_argument("--output", type=Path, help="matrix JSON output; required with --run")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        campaign, _, _ = load_campaign(args.campaign)
        cells = planned_cells(campaign)
        if args.run is None:
            print(
                json.dumps(
                    {
                        "status": "validated",
                        "campaign_id": campaign.id,
                        "task_count": len(campaign.task_ids),
                        "repetitions_per_task": campaign.repetitions_per_task,
                        "planned_cell_count": len(cells),
                        "maximum_live_requests": len(cells) * campaign.max_live_requests_per_run,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return 0
        if args.output is None:
            raise ValueError("--output is required when --run is provided")
        matrix = build_repeated_matrix(args.campaign, args.run)
        write_json_atomic(args.output, matrix)
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 1
    print(
        json.dumps(
            {
                "status": "built",
                "campaign_id": matrix["campaign_id"],
                "completion": matrix["completion"]["status"],
                "planned_cell_count": matrix["planned"]["cell_count"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
