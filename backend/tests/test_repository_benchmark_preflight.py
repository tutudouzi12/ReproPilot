from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "run_repository_benchmark_preflight.py"
SPEC = importlib.util.spec_from_file_location("repository_benchmark_preflight", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
repository_benchmark_preflight = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(repository_benchmark_preflight)


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def task_contract(task_id: str = "sample-task") -> dict:
    return {
        "version": "repropilot.repository-evaluation-task/v1",
        "id": task_id,
        "repository": {"url": "https://github.com/example/project.git", "revision": "a" * 40},
    }


def test_parse_bindings_rejects_missing_and_duplicate_task_ids(tmp_path: Path) -> None:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    with pytest.raises(ValueError, match="TASK_ID=PATH"):
        repository_benchmark_preflight.parse_bindings([str(checkout)], "checkout")
    value = f"sample={checkout}"
    with pytest.raises(ValueError, match="duplicate checkout"):
        repository_benchmark_preflight.parse_bindings([value, value], "checkout")


def test_sanitize_paths_replaces_windows_and_portable_forms(tmp_path: Path) -> None:
    source = tmp_path / "checkout"
    value = f"failed under {source} and {source.as_posix()}"

    sanitized = repository_benchmark_preflight.sanitize_paths(value, [(source, "{checkout:sample}")])

    assert str(source) not in sanitized
    assert source.as_posix() not in sanitized
    assert sanitized.count("{checkout:sample}") == 2


def test_load_benchmark_verifies_task_identity_and_contract_hashes(tmp_path: Path) -> None:
    task_dir = tmp_path / "sample-task"
    task_path = task_dir / "task.json"
    write_json(task_path, task_contract())
    benchmark = {
        "version": "repropilot.repository-benchmark/v1",
        "id": "sample",
        "tasks": [
            {
                "id": "sample-task",
                "path": "sample-task",
                "repository_url": "https://github.com/example/project.git",
                "revision": "a" * 40,
                "contract_sha256": {"task.json": sha256(task_path)},
            }
        ],
    }
    benchmark_path = tmp_path / "benchmark.json"
    write_json(benchmark_path, benchmark)

    payload, tasks = repository_benchmark_preflight.load_benchmark(benchmark_path)

    assert payload["id"] == "sample"
    assert tasks[0]["id"] == "sample-task"
    task_path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="identity mismatch|hash mismatch"):
        repository_benchmark_preflight.load_benchmark(benchmark_path)


def test_load_benchmark_rejects_task_path_escape(tmp_path: Path) -> None:
    benchmark_path = tmp_path / "benchmark.json"
    write_json(
        benchmark_path,
        {
            "version": "repropilot.repository-benchmark/v1",
            "id": "sample",
            "tasks": [
                {
                    "id": "outside",
                    "path": "../outside",
                    "repository_url": "https://github.com/example/project.git",
                    "revision": "a" * 40,
                    "contract_sha256": {"task.json": "0" * 64},
                }
            ],
        },
    )

    with pytest.raises(ValueError, match="inside the benchmark directory"):
        repository_benchmark_preflight.load_benchmark(benchmark_path)


def test_checked_in_repository_benchmark_contracts_are_frozen() -> None:
    benchmark_path = ROOT / "examples" / "autoresearch" / "repository-scale" / "benchmark.json"

    payload, tasks = repository_benchmark_preflight.load_benchmark(benchmark_path)

    assert payload["id"] == "repository-scale-pilot-v1"
    assert [task["id"] for task in tasks] == [
        "rank-bm25-boundary-robustness",
        "humanize-naturalsize-rounding",
        "more-itertools-strict-counted-sample",
        "flask-ipv6-host-parsing",
        "p-queue-abort-listener-cleanup",
        "more-itertools-strict-counted-sample-adversarial",
    ]
    assert tasks[-1]["aggregate_eligibility"] == "followup_only_not_independent_repository_sample"
