from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TASK_VERSION = "repropilot.repository-evaluation-task/v1"
BASELINE_VERSION = "repropilot.repository-baseline/v1"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git(checkout: Path, *arguments: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(checkout), *arguments],
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    ).strip()


def git_bytes(checkout: Path, *arguments: str) -> bytes:
    return subprocess.check_output(
        ["git", "-C", str(checkout), *arguments],
        timeout=30,
    )


def normalize_repository_url(value: str) -> str:
    normalized = value.strip().replace("git@github.com:", "https://github.com/")
    if normalized.endswith(".git"):
        normalized = normalized[:-4]
    return normalized.rstrip("/").lower()


def resolve_command(command: list[str], python: Path, task_dir: Path, *, task_relative: bool) -> list[str]:
    if not command:
        raise ValueError("baseline command must not be empty")
    resolved = [str(python) if command[0] in {"python", "python3"} else command[0], *command[1:]]
    if task_relative:
        for index, argument in enumerate(resolved[1:], 1):
            candidate = task_dir / argument
            if argument.endswith(".py") and candidate.is_file():
                resolved[index] = str(candidate.resolve())
    return resolved


def portable_command(command: list[str], python: Path, task_dir: Path) -> list[str]:
    portable: list[str] = []
    for argument in command:
        if Path(argument) == python:
            portable.append("{python}")
            continue
        try:
            relative = Path(argument).relative_to(task_dir)
        except ValueError:
            portable.append(argument)
        else:
            portable.append(f"{{task_dir}}/{relative.as_posix()}")
    return portable


def sanitize_paths(value: str, replacements: list[tuple[Path, str]]) -> str:
    sanitized = value
    for path, placeholder in replacements:
        sanitized = sanitized.replace(str(path), placeholder).replace(path.as_posix(), placeholder)
    return sanitized


def sanitize_command_result(result: dict[str, Any], replacements: list[tuple[Path, str]]) -> None:
    for field in ("stdout", "stderr", "error"):
        value = result.get(field)
        if isinstance(value, str):
            result[field] = sanitize_paths(value, replacements)


def run_command(command: list[str], checkout: Path, timeout_seconds: float) -> dict[str, Any]:
    started = time.perf_counter()
    environment = os.environ.copy()
    source_root = checkout / "src"
    if source_root.is_dir():
        existing = environment.get("PYTHONPATH", "")
        environment["PYTHONPATH"] = str(source_root) + (os.pathsep + existing if existing else "")
    try:
        completed = subprocess.run(
            command,
            cwd=checkout,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
        return {
            "command": command,
            "working_directory": "{target_checkout}",
            "exit_code": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "duration_ms": round((time.perf_counter() - started) * 1000),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "command": command,
            "working_directory": "{target_checkout}",
            "exit_code": None,
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
            "duration_ms": round((time.perf_counter() - started) * 1000),
            "error": f"command timed out after {timeout_seconds:g}s",
        }


def parse_metric(stdout: str, metric_key: str) -> float:
    payload: dict[str, Any] | None = None
    for line in reversed(stdout.splitlines()):
        try:
            candidate = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            payload = candidate
            break
    if payload is None:
        raise ValueError("evaluator did not emit a JSON object")
    value: Any = payload
    for part in metric_key.split("."):
        if not isinstance(value, dict) or part not in value:
            raise ValueError(f"metric {metric_key!r} missing from evaluator output")
        value = value[part]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"metric {metric_key!r} is not numeric")
    return float(value)


def python_environment(python: Path, distributions: list[str]) -> dict[str, Any]:
    script = (
        "import importlib.metadata as m,json,platform,sys;"
        f"names={json.dumps(distributions)};"
        "print(json.dumps({'implementation':platform.python_implementation(),'version':platform.python_version(),"
        "'platform':platform.platform(),'distributions':{name:m.version(name) for name in names}},sort_keys=True))"
    )
    value = subprocess.check_output(
        [str(python), "-c", script],
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    return json.loads(value)


def run_runtime_commands(
    runtime: dict[str, Any],
    python: Path,
    task_dir: Path,
    checkout: Path,
    timeout_seconds: float,
) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    for name, command in runtime.get("environment_commands", {}).items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError("runtime environment command names must be non-empty strings")
        if not isinstance(command, list) or not command or not all(isinstance(argument, str) for argument in command):
            raise ValueError(f"runtime environment command {name!r} must be a non-empty string list")
        results[name] = run_command(
            resolve_command(command, python, task_dir, task_relative=False),
            checkout,
            timeout_seconds,
        )
    return results


def run(args: argparse.Namespace) -> dict[str, Any]:
    task_dir = args.task_dir.resolve(strict=True)
    checkout = args.checkout.resolve(strict=True)
    python = args.python.resolve(strict=True)
    task_path = task_dir / "task.json"
    task = json.loads(task_path.read_text(encoding="utf-8"))
    if task.get("version") != TASK_VERSION:
        raise ValueError(f"unsupported repository task version: {task.get('version')!r}")

    repository = task["repository"]
    expected_revision = str(repository["revision"]).lower()
    actual_revision = git(checkout, "rev-parse", "HEAD").lower()
    if actual_revision != expected_revision:
        raise ValueError(f"checkout revision {actual_revision} does not match {expected_revision}")
    remote = git(checkout, "remote", "get-url", "origin")
    if normalize_repository_url(remote) != normalize_repository_url(str(repository["url"])):
        raise ValueError("checkout origin does not match the frozen repository URL")
    dirty = bool(git(checkout, "status", "--porcelain"))
    if dirty:
        raise ValueError("repository baseline requires a clean target checkout")

    git_blob_hashes: dict[str, str] = {}
    for relative, expected_hash in repository["git_blob_sha256"].items():
        relative_path = Path(relative)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ValueError(f"invalid frozen repository path: {relative}")
        blob = git_bytes(checkout, "show", f"{expected_revision}:{relative}")
        actual_hash = hashlib.sha256(blob).hexdigest()
        if actual_hash != str(expected_hash).lower():
            raise ValueError(f"Git blob hash mismatch for {relative}")
        expected_oid = git(checkout, "rev-parse", f"{expected_revision}:{relative}")
        working_oid = git(checkout, "hash-object", f"--path={relative}", relative)
        if working_oid != expected_oid:
            raise ValueError(f"working tree content does not match the frozen Git blob for {relative}")
        git_blob_hashes[relative] = actual_hash

    timeout_seconds = float(task.get("command_timeout_seconds", 30))
    commands = task["commands"]
    upstream = run_command(
        resolve_command(commands["upstream_tests"], python, task_dir, task_relative=True),
        checkout,
        timeout_seconds,
    )
    public = run_command(
        resolve_command(commands["public_evaluator"], python, task_dir, task_relative=True),
        checkout,
        timeout_seconds,
    )
    hidden = run_command(
        resolve_command(commands["hidden_evaluator"], python, task_dir, task_relative=True),
        checkout,
        timeout_seconds,
    )
    runtime_commands = run_runtime_commands(task["runtime"], python, task_dir, checkout, timeout_seconds)

    replacements = [
        (checkout, "{target_checkout}"),
        (python, "{python}"),
        (task_dir, "{task_dir}"),
    ]
    for result in (upstream, public, hidden, *runtime_commands.values()):
        result["command"] = portable_command(result["command"], python, task_dir)
        sanitize_command_result(result, replacements)
    for label, result in (("upstream tests", upstream), ("public evaluator", public), ("hidden evaluator", hidden)):
        if result["exit_code"] != 0:
            raise RuntimeError(f"{label} failed: {result.get('error') or result['stderr']}")
    for name, result in runtime_commands.items():
        if result["exit_code"] != 0:
            raise RuntimeError(f"runtime environment command {name!r} failed: {result.get('error') or result['stderr']}")

    metric_key = str(task["metric_key"])
    public_score = parse_metric(public["stdout"], metric_key)
    hidden_score = parse_metric(hidden["stdout"], metric_key)
    expected = task.get("expected_baseline", {})
    if public_score != float(expected["public_score"]) or hidden_score != float(expected["hidden_score"]):
        raise RuntimeError(
            f"baseline drifted: public={public_score:g}, hidden={hidden_score:g}, expected={expected}"
        )

    artifact_hashes = {
        path.name: sha256_file(path)
        for path in sorted(task_dir.iterdir())
        if path.is_file() and path.name != args.output.name
    }
    environment = python_environment(python, list(task["runtime"]["distributions"]))
    if runtime_commands:
        environment["runtime_commands"] = runtime_commands

    return {
        "version": BASELINE_VERSION,
        "recorded_at": utc_now(),
        "task_id": task["id"],
        "repository": {
            "url": repository["url"],
            "requested_revision": expected_revision,
            "actual_revision": actual_revision,
            "source_tree_dirty": False,
            "git_blob_sha256": git_blob_hashes,
            "working_tree_matches_git_blobs": True,
        },
        "environment": environment,
        "commands": {
            "upstream_tests": upstream,
            "public_evaluator": public,
            "hidden_evaluator": hidden,
        },
        "baseline": {
            "upstream_tests_passed": True,
            "public_score": public_score,
            "hidden_score": hidden_score,
            "metric_key": metric_key,
        },
        "task_artifact_sha256": artifact_hashes,
        "boundaries": task["boundaries"],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run and retain a baseline for a pinned real-repository task.")
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = run(args)
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(
        f"Repository baseline: {result['task_id']} "
        f"public={result['baseline']['public_score']:.4f} hidden={result['baseline']['hidden_score']:.4f}"
    )
    print(f"Artifact: {output}")


if __name__ == "__main__":
    main()
