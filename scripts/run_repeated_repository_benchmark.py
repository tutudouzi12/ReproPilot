from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.agents import LLMClient  # noqa: E402
from app.repeated_benchmark import (  # noqa: E402
    RepeatedCell,
    RepeatedRun,
    build_repeated_matrix,
    load_campaign,
    planned_cells,
    read_object,
    sha256_file,
    validate_cell_result,
    validate_run_plan,
)


SINGLE_RUNNER = ROOT / "scripts" / "run_repository_evaluation.py"
PREFLIGHT_RUNNER = ROOT / "scripts" / "run_repository_benchmark_preflight.py"


def git(*arguments: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(ROOT), *arguments],
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    ).strip()


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}-{os.getpid()}.tmp"
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def parse_bindings(values: list[str], label: str) -> dict[str, Path]:
    bindings: dict[str, Path] = {}
    for value in values:
        task_id, separator, raw_path = value.partition("=")
        task_id = task_id.strip()
        raw_path = raw_path.strip()
        if not separator or not task_id or not raw_path:
            raise ValueError(f"{label} must use TASK_ID=PATH")
        if task_id in bindings:
            raise ValueError(f"duplicate {label} binding for {task_id}")
        path = Path(raw_path).absolute()
        if not path.exists():
            raise ValueError(f"{label} binding does not exist for {task_id}")
        bindings[task_id] = path
    return bindings


def load_env_file(path: Path | None) -> None:
    if path is None:
        return
    for raw_line in path.resolve(strict=True).read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


def stream_fingerprint(stdout: str, stderr: str, exit_code: int) -> dict[str, Any]:
    return {
        "exit_code": exit_code,
        "stdout_bytes": len(stdout.encode("utf-8", errors="replace")),
        "stdout_sha256": hashlib.sha256(stdout.encode("utf-8", errors="replace")).hexdigest(),
        "stderr_bytes": len(stderr.encode("utf-8", errors="replace")),
        "stderr_sha256": hashlib.sha256(stderr.encode("utf-8", errors="replace")).hexdigest(),
    }


def run_preflight(
    campaign_path: Path,
    task_ids: list[str],
    checkouts: dict[str, Path],
    pythons: dict[str, Path],
    output: Path,
) -> None:
    campaign, _, _ = load_campaign(campaign_path)
    benchmark = campaign_path.parent / campaign.benchmark
    command = [sys.executable, str(PREFLIGHT_RUNNER), "--benchmark", str(benchmark), "--output", str(output)]
    for task_id in task_ids:
        command.extend(["--task", task_id, "--checkout", f"{task_id}={checkouts[task_id]}", "--python", f"{task_id}={pythons[task_id]}"])
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    if completed.returncode != 0:
        raise RuntimeError("repeated benchmark preflight failed before live execution")


def single_run_command(
    task_dir: Path,
    checkout: Path,
    python: Path,
    output: Path,
    args: argparse.Namespace,
    request_cap: int,
) -> list[str]:
    command = [
        sys.executable,
        str(SINGLE_RUNNER),
        "--task-dir",
        str(task_dir),
        "--checkout",
        str(checkout),
        "--python",
        str(python),
        "--output",
        str(output),
        "--max-live-requests",
        str(request_cap),
    ]
    if args.env_file is not None:
        command.extend(["--env-file", str(args.env_file)])
    for option, value in (
        ("--input-cost-per-million", args.input_cost_per_million),
        ("--output-cost-per-million", args.output_cost_per_million),
        ("--currency", args.currency),
        ("--pricing-source", args.pricing_source),
        ("--pricing-tier", args.pricing_tier),
        ("--pricing-verified-at", args.pricing_verified_at),
    ):
        if value is not None and value != "":
            command.extend([option, str(value)])
    return command


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a fixed round-robin repeated live repository benchmark campaign.")
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--checkout", action="append", default=[], metavar="TASK_ID=PATH")
    parser.add_argument("--python", action="append", default=[], metavar="TASK_ID=PATH")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--execute", action="store_true", help="Explicitly authorize live model execution")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--max-total-live-requests", type=int)
    parser.add_argument("--input-cost-per-million", type=float)
    parser.add_argument("--output-cost-per-million", type=float)
    parser.add_argument("--currency", default="USD")
    parser.add_argument("--pricing-source", default="")
    parser.add_argument("--pricing-tier", default="")
    parser.add_argument("--pricing-verified-at", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        campaign, campaign_path, tasks = load_campaign(args.campaign)
        plan = planned_cells(campaign)
        maximum_requests = len(plan) * campaign.max_live_requests_per_run
        if not args.execute:
            print(
                json.dumps(
                    {
                        "status": "execution_not_authorized",
                        "campaign_id": campaign.id,
                        "planned_cell_count": len(plan),
                        "maximum_live_requests": maximum_requests,
                        "hint": "pass --execute with checkout, python, output, and max-total-live-requests bindings",
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return 0
        if args.output is None or args.max_total_live_requests is None:
            raise ValueError("live execution requires --output and --max-total-live-requests")
        output = args.output.absolute()
        try:
            output.resolve().relative_to(ROOT.resolve())
        except ValueError:
            pass
        else:
            raise ValueError("repeated benchmark output must remain outside the harness checkout")
        revision = git("rev-parse", "HEAD").lower()
        if git("status", "--porcelain"):
            raise ValueError("repeated benchmark requires a clean harness checkout")
        checkouts = parse_bindings(args.checkout, "checkout")
        pythons = parse_bindings(args.python, "python")
        missing = [task_id for task_id in campaign.task_ids if task_id not in checkouts or task_id not in pythons]
        if missing:
            raise ValueError(f"checkout and python bindings are required for: {', '.join(missing)}")
        load_env_file(args.env_file)
        client = LLMClient(offline_demo_mode=False)
        if not client.configured:
            raise ValueError("live repeated benchmark requires a configured model credential")
        provider = urlparse(client.base_url).hostname or client.base_url
        if provider != campaign.model.provider or client.model != campaign.model.name:
            raise ValueError("configured provider/model does not match the frozen campaign")

        run_path = output / "campaign-run.json"
        if args.resume:
            run = RepeatedRun.model_validate(read_object(run_path))
            validate_run_plan(campaign, campaign_path, run)
            if run.harness_revision != revision:
                raise ValueError("resume requires the exact original harness revision")
        else:
            if output.exists():
                raise ValueError("repeated benchmark output already exists; use --resume only for the same campaign")
            output.mkdir(parents=True)
            run = RepeatedRun(
                campaign_id=campaign.id,
                campaign_sha256=sha256_file(campaign_path),
                benchmark_sha256=campaign.benchmark_sha256,
                harness_revision=revision,
                model=campaign.model,
                max_live_requests_per_run=campaign.max_live_requests_per_run,
                planned_cell_count=len(plan),
            )
            write_json_atomic(run_path, run.model_dump(mode="json"))

        remaining = len(plan) - len(run.cells)
        required_remaining_cap = remaining * campaign.max_live_requests_per_run
        if args.max_total_live_requests < required_remaining_cap:
            raise ValueError(f"remaining campaign requires an explicit cap of at least {required_remaining_cap} live requests")
        preflight_path = output / "preflight.json"
        run_preflight(campaign_path, campaign.task_ids, checkouts, pythons, preflight_path)
        run.preflight = preflight_path.relative_to(output).as_posix()
        run.preflight_sha256 = sha256_file(preflight_path)
        write_json_atomic(run_path, run.model_dump(mode="json"))

        for ordinal, task_id, repetition in plan[len(run.cells) :]:
            cell_dir = output / "cells" / f"{ordinal:03d}-{task_id}-r{repetition}"
            if cell_dir.exists():
                recovered_result = cell_dir / "artifact" / "result.json"
                if recovered_result.is_file():
                    result = read_object(recovered_result)
                    recovered_cell = RepeatedCell(
                        ordinal=ordinal,
                        task_id=task_id,
                        repetition=repetition,
                        status="completed",
                        result=recovered_result.relative_to(output).as_posix(),
                        result_sha256=sha256_file(recovered_result),
                        classification=str(result.get("outcome", "unknown"))[:128],
                    )
                    validate_cell_result(campaign, run, output, recovered_cell, tasks[task_id])
                    run.cells.append(recovered_cell)
                    write_json_atomic(run_path, run.model_dump(mode="json"))
                    continue
                failure = {"classification": "interrupted_or_uncommitted_cell", "ordinal": ordinal, "task_id": task_id, "repetition": repetition}
                failure_path = cell_dir / "failure.json"
                write_json_atomic(failure_path, failure)
                run.cells.append(RepeatedCell(ordinal=ordinal, task_id=task_id, repetition=repetition, status="incomplete", classification="interrupted_or_uncommitted_cell", failure=failure_path.relative_to(output).as_posix(), failure_sha256=sha256_file(failure_path)))
                write_json_atomic(run_path, run.model_dump(mode="json"))
                continue
            cell_dir.parent.mkdir(parents=True, exist_ok=True)
            write_json_atomic(cell_dir / "cell-started.json", {"ordinal": ordinal, "task_id": task_id, "repetition": repetition})
            artifact_dir = cell_dir / "artifact"
            task_dir = Path(tasks[task_id]["task_dir"])
            command = single_run_command(task_dir, checkouts[task_id], pythons[task_id], artifact_dir, args, campaign.max_live_requests_per_run)
            completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False, timeout=7200)
            result_path = artifact_dir / "result.json"
            if result_path.is_file():
                result = read_object(result_path)
                classification = str(result.get("outcome", "unknown"))[:128]
                relative = result_path.relative_to(output).as_posix()
                cell = RepeatedCell(ordinal=ordinal, task_id=task_id, repetition=repetition, status="completed", result=relative, result_sha256=sha256_file(result_path), classification=classification)
                validate_cell_result(campaign, run, output, cell, tasks[task_id])
            else:
                failure = {"classification": "runner_failed_without_result", **stream_fingerprint(completed.stdout, completed.stderr, completed.returncode)}
                failure_path = cell_dir / "failure.json"
                write_json_atomic(failure_path, failure)
                cell = RepeatedCell(ordinal=ordinal, task_id=task_id, repetition=repetition, status="incomplete", classification="runner_failed_without_result", failure=failure_path.relative_to(output).as_posix(), failure_sha256=sha256_file(failure_path))
            run.cells.append(cell)
            write_json_atomic(run_path, run.model_dump(mode="json"))

        matrix = build_repeated_matrix(campaign_path, run_path)
        write_json_atomic(output / "matrix.json", matrix)
    except subprocess.TimeoutExpired as exc:
        print(json.dumps({"status": "failed", "error": f"cell process timed out after {exc.timeout} seconds"}, ensure_ascii=False))
        return 1
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 1
    print(json.dumps({"status": "completed", "campaign_id": campaign.id, "matrix": str(output / 'matrix.json')}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
