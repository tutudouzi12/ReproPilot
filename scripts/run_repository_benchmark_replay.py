from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


REPLAY_VERSION = "repropilot.repository-benchmark-replay/v1"
RESULT_VERSION = "repropilot.repository-benchmark-replay-result/v1"
ROOT = Path(__file__).resolve().parents[1]
PREFLIGHT_SCRIPT = ROOT / "scripts" / "run_repository_benchmark_preflight.py"

SPEC = importlib.util.spec_from_file_location("repository_benchmark_preflight", PREFLIGHT_SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load repository benchmark preflight runner")
preflight = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preflight)

PYTHON_REQUIREMENT = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]*(?:\[[A-Za-z0-9,._-]+\])?==[A-Za-z0-9][A-Za-z0-9.+_-]*$"
)
NPM_REQUIREMENT = re.compile(r"^(?:@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*@[0-9][A-Za-z0-9.+_-]*$")


class StageFailure(RuntimeError):
    def __init__(self, stage: str, result: dict[str, Any]) -> None:
        super().__init__(f"{stage} failed with exit code {result['exit_code']}")
        self.stage = stage
        self.result = result


def _inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def _validate_packages(values: Any, pattern: re.Pattern[str], label: str) -> list[str]:
    if not isinstance(values, list) or not values:
        raise ValueError(f"{label} must contain at least one exact package version")
    packages = [str(value) for value in values]
    invalid = [value for value in packages if not pattern.fullmatch(value)]
    if invalid:
        raise ValueError(f"{label} contains a non-exact or unsafe package requirement: {invalid[0]!r}")
    if len(set(packages)) != len(packages):
        raise ValueError(f"{label} contains duplicate package requirements")
    return packages


def validate_setup(task_id: str, value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"replay setup must be an object for {task_id}")
    kind = str(value.get("kind", ""))
    if kind == "python_venv":
        if value.get("python_version") != "3.11" or value.get("editable_checkout") is not True:
            raise ValueError(f"python replay setup must pin Python 3.11 and editable_checkout for {task_id}")
        return {
            "kind": kind,
            "python_version": "3.11",
            "editable_checkout": True,
            "packages": _validate_packages(value.get("packages"), PYTHON_REQUIREMENT, f"{task_id} Python packages"),
        }
    if kind == "npm":
        node_major = value.get("node_major")
        if not isinstance(node_major, int) or not 20 <= node_major <= 24 or value.get("package_lock") is not False:
            raise ValueError(f"npm replay setup must pin a supported Node major and disable package-lock for {task_id}")
        return {
            "kind": kind,
            "node_major": node_major,
            "package_lock": False,
            "packages": _validate_packages(value.get("packages"), NPM_REQUIREMENT, f"{task_id} npm packages"),
        }
    raise ValueError(f"unsupported replay setup kind for {task_id}: {kind!r}")


def load_replay(path: Path) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    manifest_path = path.resolve(strict=True)
    manifest_root = manifest_path.parent
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if payload.get("version") != REPLAY_VERSION:
        raise ValueError(f"unsupported replay version: {payload.get('version')!r}")
    benchmark_relative = Path(str(payload.get("benchmark", "")))
    if not benchmark_relative.parts or benchmark_relative.is_absolute() or ".." in benchmark_relative.parts:
        raise ValueError("replay benchmark path must remain inside the manifest directory")
    benchmark_path = (manifest_root / benchmark_relative).resolve(strict=True)
    if not _inside(manifest_root, benchmark_path):
        raise ValueError("replay benchmark path escaped the manifest directory")
    benchmark, benchmark_tasks = preflight.load_benchmark(benchmark_path)
    known = {str(task["id"]): task for task in benchmark_tasks}
    raw_tasks = payload.get("tasks")
    if not isinstance(raw_tasks, list) or not raw_tasks:
        raise ValueError("replay must contain at least one task")
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in raw_tasks:
        if not isinstance(entry, dict):
            raise ValueError("replay task entries must be objects")
        task_id = str(entry.get("id", "")).strip()
        if not task_id or task_id in seen:
            raise ValueError(f"missing or duplicate replay task id: {task_id!r}")
        if task_id not in known:
            raise ValueError(f"replay references unknown benchmark task: {task_id}")
        selected.append({**known[task_id], "setup": validate_setup(task_id, entry.get("setup"))})
        seen.add(task_id)
    return payload, benchmark, selected


def command_result(command: list[str], cwd: Path, timeout_seconds: float) -> dict[str, Any]:
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
        return {
            "exit_code": completed.returncode,
            "duration_ms": int((time.monotonic() - started) * 1000),
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "exit_code": 124,
            "duration_ms": int((time.monotonic() - started) * 1000),
            "stdout": preflight.decoded_output(exc.stdout),
            "stderr": f"{preflight.decoded_output(exc.stderr)}\ncommand timed out after {timeout_seconds:g}s".strip(),
        }


def sanitize_text(value: str, workspace: Path) -> str:
    replacements = [(workspace, "{replay_workspace}"), (ROOT, "{harness}")]
    return preflight.sanitize_paths(value, replacements)


def sanitize_command(command: list[str], workspace: Path) -> list[str]:
    sanitized = [sanitize_text(str(value), workspace) for value in command]
    if not command:
        return sanitized
    executable_name = Path(command[0]).name.lower()
    if executable_name in {"python", "python3", "python.exe", "python3.exe"}:
        sanitized[0] = "{python}"
    elif executable_name in {"node", "node.exe"}:
        sanitized[0] = "{node}"
    elif executable_name in {"npm", "npm.cmd", "npm.exe"}:
        sanitized[0] = "{npm}"
    return sanitized


def retained_command(command: list[str], cwd: Path, result: dict[str, Any], workspace: Path) -> dict[str, Any]:
    record = {
        "command": sanitize_command(command, workspace),
        "working_directory": sanitize_text(str(cwd), workspace),
        "exit_code": result["exit_code"],
        "duration_ms": result["duration_ms"],
    }
    if result["exit_code"] != 0:
        record["stdout_tail"] = sanitize_text(result["stdout"][-4000:], workspace)
        record["stderr_tail"] = sanitize_text(result["stderr"][-4000:], workspace)
    return record


def run_stage(
    stage: str,
    command: list[str],
    cwd: Path,
    workspace: Path,
    records: list[dict[str, Any]],
    timeout_seconds: float,
) -> dict[str, Any]:
    result = command_result(command, cwd, timeout_seconds)
    records.append({"stage": stage, **retained_command(command, cwd, result, workspace)})
    if result["exit_code"] != 0:
        raise StageFailure(stage, result)
    return result


def venv_python(directory: Path) -> Path:
    relative = Path("Scripts/python.exe") if os.name == "nt" else Path("bin/python")
    return directory / relative


def prepare_checkout(task: dict[str, Any], workspace: Path, records: list[dict[str, Any]]) -> Path:
    task_id = str(task["id"])
    checkout_root = workspace / "checkouts"
    checkout_root.mkdir(parents=True, exist_ok=True)
    repository = task["task"]["repository"]
    checkout: Path | None = None
    last_result: dict[str, Any] | None = None
    for attempt in range(1, 4):
        candidate = checkout_root / (task_id if attempt == 1 else f"{task_id}-clone-attempt-{attempt}")
        command = [
            "git",
            "clone",
            "--filter=blob:none",
            "--no-checkout",
            "--quiet",
            repository["url"],
            str(candidate),
        ]
        last_result = command_result(command, workspace, 300)
        records.append(
            {
                "stage": "clone",
                "attempt": attempt,
                "max_attempts": 3,
                **retained_command(command, workspace, last_result, workspace),
            }
        )
        if last_result["exit_code"] == 0:
            checkout = candidate
            break
        if attempt < 3:
            time.sleep(0.5 * (2 ** (attempt - 1)))
    if checkout is None:
        assert last_result is not None
        raise StageFailure("clone", last_result)
    run_stage(
        "checkout",
        ["git", "-C", str(checkout), "checkout", "--detach", "--quiet", repository["revision"]],
        workspace,
        workspace,
        records,
        300,
    )
    return checkout


def prepare_runtime(
    task: dict[str, Any], checkout: Path, workspace: Path, records: list[dict[str, Any]]
) -> tuple[Path, dict[str, str]]:
    setup = task["setup"]
    if setup["kind"] == "python_venv":
        actual_python = f"{sys.version_info.major}.{sys.version_info.minor}"
        if actual_python != setup["python_version"]:
            raise ValueError(f"Python {setup['python_version']} is required, found {actual_python}")
        environment = workspace / "venvs" / str(task["id"])
        run_stage("python_venv", [sys.executable, "-m", "venv", str(environment)], workspace, workspace, records, 300)
        python = venv_python(environment)
        command = [
            str(python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-input",
            "--editable",
            str(checkout),
            *setup["packages"],
        ]
        run_stage("python_dependencies", command, workspace, workspace, records, 900)
        return python, {"python": setup["python_version"], "node": ""}

    node = shutil.which("node")
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if node is None or npm is None:
        raise ValueError("Node and npm are required for npm replay setup")
    version_result = run_stage("node_version", [node, "--version"], workspace, workspace, records, 60)
    node_version = version_result["stdout"].strip().removeprefix("v")
    if node_version.split(".", 1)[0] != str(setup["node_major"]):
        raise ValueError(f"Node {setup['node_major']} is required, found {node_version}")
    command = [
        npm,
        "install",
        "--ignore-scripts",
        "--no-audit",
        "--no-fund",
        "--no-save",
        "--package-lock=false",
        *setup["packages"],
    ]
    run_stage("npm_dependencies", command, checkout, workspace, records, 900)
    return Path(sys.executable), {"python": f"{sys.version_info.major}.{sys.version_info.minor}", "node": node_version}


def replay_task(task: dict[str, Any], workspace: Path) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    task_id = str(task["id"])
    try:
        checkout = prepare_checkout(task, workspace, records)
        python, runtime = prepare_runtime(task, checkout, workspace, records)
        result = preflight.run_preflight(task, checkout, python)
        status = "passed" if result["status"] == "passed" else "preflight_failed"
        return {
            "task_id": task_id,
            "status": status,
            "repository": {
                "url": task["task"]["repository"]["url"],
                "revision": task["task"]["repository"]["revision"],
            },
            "runtime": runtime,
            "setup": records,
            "preflight": result,
        }
    except StageFailure as exc:
        return {
            "task_id": task_id,
            "status": "setup_failed",
            "failed_stage": exc.stage,
            "repository": {
                "url": task["task"]["repository"]["url"],
                "revision": task["task"]["repository"]["revision"],
            },
            "setup": records,
            "preflight": None,
        }
    except Exception as exc:
        return {
            "task_id": task_id,
            "status": "setup_failed",
            "failed_stage": "runtime_validation",
            "error_type": type(exc).__name__,
            "error": sanitize_text(str(exc), workspace),
            "repository": {
                "url": task["task"]["repository"]["url"],
                "revision": task["task"]["repository"]["revision"],
            },
            "setup": records,
            "preflight": None,
        }


def prepare_workspace(path: Path) -> Path:
    workspace = path.resolve()
    if workspace.exists() and any(workspace.iterdir()):
        raise ValueError(f"replay workspace must be absent or empty: {workspace}")
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


def run_replay(manifest: Path, workspace_path: Path) -> dict[str, Any]:
    payload, benchmark, tasks = load_replay(manifest)
    workspace = prepare_workspace(workspace_path)
    results = [replay_task(task, workspace) for task in tasks]
    passed = sum(item["status"] == "passed" for item in results)
    return {
        "version": RESULT_VERSION,
        "recorded_at": preflight.utc_now(),
        "replay_id": payload["id"],
        "benchmark_id": benchmark["id"],
        "selected_task_count": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "model_requests": 0,
        "results": results,
        "boundaries": payload.get("boundaries", []),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Replay selected pinned repository benchmark tasks on a clean runner.")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        result = run_replay(args.manifest, args.workspace)
    except Exception as exc:
        replacements = [(args.workspace.resolve(), "{replay_workspace}"), (ROOT, "{harness}")]
        result = {
            "version": RESULT_VERSION,
            "recorded_at": preflight.utc_now(),
            "status": "manifest_or_workspace_failed",
            "failed": 1,
            "model_requests": 0,
            "error_type": type(exc).__name__,
            "error": preflight.sanitize_paths(str(exc), replacements),
            "results": [],
        }
    preflight.write_json(args.output, result)
    print(
        f"Repository benchmark replay: {result.get('passed', 0)}/{result.get('selected_task_count', 0)} passed"
    )
    print(f"Artifact: {args.output.resolve()}")
    if result.get("failed"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
