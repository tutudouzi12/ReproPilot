from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BENCHMARK_VERSION = "repropilot.repository-benchmark/v1"
TASK_VERSION = "repropilot.repository-evaluation-task/v1"
RESULT_VERSION = "repropilot.repository-benchmark-preflight/v1"
ROOT = Path(__file__).resolve().parents[1]
TASK_RUNNER = ROOT / "scripts" / "run_repository_evaluation.py"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_bindings(values: list[str], label: str) -> dict[str, Path]:
    bindings: dict[str, Path] = {}
    for value in values:
        task_id, separator, raw_path = value.partition("=")
        task_id = task_id.strip()
        raw_path = raw_path.strip()
        if not separator or not task_id or not raw_path:
            raise ValueError(f"{label} must use TASK_ID=PATH: {value!r}")
        if task_id in bindings:
            raise ValueError(f"duplicate {label} binding for {task_id}")
        bindings[task_id] = Path(raw_path).resolve(strict=True)
    return bindings


def _inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def load_benchmark(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    benchmark_path = path.resolve(strict=True)
    benchmark_root = benchmark_path.parent
    payload = json.loads(benchmark_path.read_text(encoding="utf-8"))
    if payload.get("version") != BENCHMARK_VERSION:
        raise ValueError(f"unsupported benchmark version: {payload.get('version')!r}")
    raw_tasks = payload.get("tasks")
    if not isinstance(raw_tasks, list) or not raw_tasks:
        raise ValueError("benchmark must contain at least one task")

    task_ids: set[str] = set()
    tasks: list[dict[str, Any]] = []
    for entry in raw_tasks:
        if not isinstance(entry, dict):
            raise ValueError("benchmark task entries must be JSON objects")
        task_id = str(entry.get("id", "")).strip()
        relative = Path(str(entry.get("path", "")))
        if not task_id or task_id in task_ids:
            raise ValueError(f"missing or duplicate benchmark task id: {task_id!r}")
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"task path must remain inside the benchmark directory: {relative}")
        task_dir = (benchmark_root / relative).resolve(strict=True)
        if not _inside(benchmark_root, task_dir):
            raise ValueError(f"task path escaped the benchmark directory: {relative}")
        task = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
        if task.get("version") != TASK_VERSION or task.get("id") != task_id:
            raise ValueError(f"task contract identity mismatch for {task_id}")
        repository = task.get("repository", {})
        if repository.get("url") != entry.get("repository_url"):
            raise ValueError(f"repository URL mismatch for {task_id}")
        if repository.get("revision") != entry.get("revision"):
            raise ValueError(f"repository revision mismatch for {task_id}")
        artifact_hashes = entry.get("contract_sha256")
        if not isinstance(artifact_hashes, dict) or not artifact_hashes:
            raise ValueError(f"contract_sha256 is required for {task_id}")
        for relative_artifact, expected_hash in artifact_hashes.items():
            artifact = (task_dir / str(relative_artifact)).resolve(strict=True)
            if not _inside(task_dir, artifact) or not artifact.is_file():
                raise ValueError(f"invalid contract artifact for {task_id}: {relative_artifact}")
            actual_hash = sha256_file(artifact)
            if actual_hash != str(expected_hash).lower():
                raise ValueError(f"contract artifact hash mismatch for {task_id}: {relative_artifact}")
        task_ids.add(task_id)
        tasks.append({**entry, "task_dir": task_dir, "task": task})
    return payload, tasks


def sanitize_paths(value: str, replacements: list[tuple[Path, str]]) -> str:
    sanitized = value
    for path, placeholder in replacements:
        sanitized = sanitized.replace(str(path), placeholder).replace(path.as_posix(), placeholder)
    return sanitized


def decoded_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def expected_baseline_scores(task: dict[str, Any]) -> tuple[float, float]:
    baseline_path = Path(task["task_dir"]) / "baseline.json"
    payload = json.loads(baseline_path.read_text(encoding="utf-8"))
    baseline = payload.get("baseline")
    if not isinstance(baseline, dict):
        raise ValueError(f"baseline contract is missing for {task['id']}")
    try:
        return float(baseline["public_score"]), float(baseline["hidden_score"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"baseline scores are invalid for {task['id']}") from exc


def parse_preflight_scores(stdout: str, task_id: str) -> tuple[float, float]:
    match = re.search(
        rf"^Repository preflight:\s+{re.escape(task_id)}\s+public=([-+0-9.eE]+)\s+hidden=([-+0-9.eE]+)\s*$",
        stdout,
        re.MULTILINE,
    )
    if match is None:
        raise ValueError(f"preflight output did not contain scores for {task_id}")
    public_score = float(match.group(1))
    hidden_score = float(match.group(2))
    if not math.isfinite(public_score) or not math.isfinite(hidden_score):
        raise ValueError(f"preflight scores must be finite for {task_id}")
    return public_score, hidden_score


def run_preflight(task: dict[str, Any], checkout: Path, python: Path) -> dict[str, Any]:
    task_id = str(task["id"])
    command = [
        sys.executable,
        str(TASK_RUNNER),
        "--task-dir",
        str(task["task_dir"]),
        "--checkout",
        str(checkout),
        "--python",
        str(python),
        "--preflight-only",
    ]
    timeout_seconds = max(60.0, float(task["task"].get("command_timeout_seconds", 60)) * 10)
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
        exit_code = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except subprocess.TimeoutExpired as exc:
        exit_code = 124
        stdout = decoded_output(exc.stdout)
        stderr = decoded_output(exc.stderr) + f"\npreflight process timed out after {timeout_seconds:g}s"
    expected_public, expected_hidden = expected_baseline_scores(task)
    observed_public: float | None = None
    observed_hidden: float | None = None
    scores_match = False
    if exit_code == 0:
        try:
            observed_public, observed_hidden = parse_preflight_scores(stdout, task_id)
            scores_match = math.isclose(observed_public, expected_public, rel_tol=0.0, abs_tol=0.00005) and math.isclose(
                observed_hidden,
                expected_hidden,
                rel_tol=0.0,
                abs_tol=0.00005,
            )
            if not scores_match:
                exit_code = 2
                stderr = (
                    f"{stderr}\nbaseline score mismatch: expected public={expected_public:.4f} "
                    f"hidden={expected_hidden:.4f}, observed public={observed_public:.4f} "
                    f"hidden={observed_hidden:.4f}"
                ).strip()
        except ValueError as exc:
            exit_code = 2
            stderr = f"{stderr}\n{exc}".strip()
    replacements = [
        (checkout, f"{{checkout:{task_id}}}"),
        (python, f"{{python:{task_id}}}"),
        (task["task_dir"], f"{{task_dir:{task_id}}}"),
        (ROOT, "{harness}"),
    ]
    return {
        "task_id": task_id,
        "status": "passed" if exit_code == 0 else "failed",
        "exit_code": exit_code,
        "checkout": f"{{checkout:{task_id}}}",
        "python": f"{{python:{task_id}}}",
        "expected_public_score": expected_public,
        "expected_hidden_score": expected_hidden,
        "observed_public_score": observed_public,
        "observed_hidden_score": observed_hidden,
        "scores_match_baseline": scores_match,
        "stdout": sanitize_paths(stdout, replacements),
        "stderr": sanitize_paths(stderr, replacements),
    }


def write_json(path: Path, value: Any) -> None:
    output = path.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Preflight every pinned task in a repository benchmark manifest.")
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--checkout", action="append", default=[], metavar="TASK_ID=PATH")
    parser.add_argument("--python", action="append", default=[], metavar="TASK_ID=PATH")
    parser.add_argument("--task", action="append", default=[], help="Run only the selected task id; repeatable.")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--validate-only", action="store_true", help="Validate the manifest and contract hashes without target checkouts.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    benchmark, tasks = load_benchmark(args.benchmark)
    if args.validate_only:
        print(f"Repository benchmark manifest: {benchmark['id']} {len(tasks)} task(s) validated")
        return
    checkouts = parse_bindings(args.checkout, "checkout")
    pythons = parse_bindings(args.python, "python")
    selected = set(args.task)
    known = {str(task["id"]) for task in tasks}
    unknown = selected - known
    if unknown:
        raise ValueError(f"unknown selected tasks: {', '.join(sorted(unknown))}")
    active = [task for task in tasks if not selected or task["id"] in selected]
    missing = [task["id"] for task in active if task["id"] not in checkouts or task["id"] not in pythons]
    if missing:
        raise ValueError(f"checkout and python bindings are required for: {', '.join(missing)}")
    invalid_checkouts = [task["id"] for task in active if not checkouts[task["id"]].is_dir()]
    invalid_pythons = [task["id"] for task in active if not pythons[task["id"]].is_file()]
    if invalid_checkouts:
        raise ValueError(f"checkout bindings must be directories for: {', '.join(invalid_checkouts)}")
    if invalid_pythons:
        raise ValueError(f"python bindings must be executable files for: {', '.join(invalid_pythons)}")

    results: list[dict[str, Any]] = []
    for task in active:
        task_id = str(task["id"])
        print(f"Preflight {task_id} ...")
        result = run_preflight(task, checkouts[task_id], pythons[task_id])
        results.append(result)
        stream = result["stdout"] if result["status"] == "passed" else result["stderr"] or result["stdout"]
        if stream.strip():
            print(stream.rstrip())

    summary = {
        "version": RESULT_VERSION,
        "recorded_at": utc_now(),
        "benchmark_id": benchmark["id"],
        "selected_task_count": len(active),
        "passed": sum(item["status"] == "passed" for item in results),
        "failed": sum(item["status"] == "failed" for item in results),
        "results": results,
    }
    if args.output is not None:
        write_json(args.output, summary)
        print(f"Artifact: {args.output.resolve()}")
    print(f"Repository benchmark preflight: {summary['passed']}/{len(active)} passed")
    if summary["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
