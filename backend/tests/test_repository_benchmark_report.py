from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "build_repository_benchmark_report.py"
SPEC = importlib.util.spec_from_file_location("repository_benchmark_report", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
repository_benchmark_report = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(repository_benchmark_report)


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    root = tmp_path / "repository-scale"
    task_dir = root / "sample-task"
    result_dir = task_dir / "results" / "run-1"
    task_path = task_dir / "task.json"
    baseline_path = task_dir / "baseline.json"
    candidate_path = result_dir / "candidate.patch"
    result_path = result_dir / "result.json"
    review_path = result_dir / "review.json"

    write_json(
        task_path,
        {
            "version": "repropilot.repository-evaluation-task/v1",
            "id": "sample-task",
            "repository": {
                "url": "https://github.com/example/project.git",
                "revision": "a" * 40,
            },
        },
    )
    write_json(baseline_path, {"baseline": {"public_score": 0.0, "hidden_score": 0.0}})
    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    candidate_path.write_text("patch evidence\n", encoding="utf-8")
    write_json(
        result_path,
        {
            "version": "repropilot.repository-evaluation-result/v1",
            "task_id": "sample-task",
            "recorded_at": "2026-01-01T00:00:00Z",
            "outcome": "validation_passed",
            "harness": {"revision": "b" * 40, "source_tree_dirty": False},
            "repository": {
                "url": "https://github.com/example/project.git",
                "revision": "a" * 40,
            },
            "baseline_artifact_sha256": sha256(baseline_path),
            "search": {"baseline_score": 0.0, "best_score": 1.0},
            "validation": {"baseline_score": 0.0, "observed_score": 1.0},
            "model": {
                "attempted_request_count": 1,
                "request_count": 1,
                "reported_request_count": 1,
                "total_tokens": 10,
            },
            "cost": {
                "status": "calculated_from_supplied_rates",
                "amount": 0.01,
                "currency": "CNY",
            },
            "artifact_sha256": {"candidate.patch": sha256(candidate_path)},
        },
    )
    write_json(
        review_path,
        {
            "version": "repropilot.repository-evaluation-review/v1",
            "status": "contract_pass",
            "decision": "accept_with_boundary",
            "classification": "contract_pass_review_accepted",
        },
    )
    benchmark_path = root / "benchmark.json"
    write_json(
        benchmark_path,
        {
            "version": "repropilot.repository-benchmark/v1",
            "id": "sample-benchmark",
            "title": "Sample benchmark",
            "run_selection": "run-selection.json",
            "tasks": [
                {
                    "id": "sample-task",
                    "path": "sample-task",
                    "repository_url": "https://github.com/example/project.git",
                    "revision": "a" * 40,
                    "contract_sha256": {
                        "task.json": sha256(task_path),
                        "baseline.json": sha256(baseline_path),
                    },
                }
            ],
            "boundaries": [],
        },
    )
    selection_path = root / "run-selection.json"
    write_json(
        selection_path,
        {
            "version": "repropilot.repository-benchmark-run-selection/v1",
            "benchmark_id": "sample-benchmark",
            "recorded_at": "2026-01-01T00:00:00Z",
            "runs": [
                {
                    "task_id": "sample-task",
                    "role": "primary",
                    "result": "sample-task/results/run-1/result.json",
                    "result_sha256": sha256(result_path),
                    "review": "sample-task/results/run-1/review.json",
                    "review_sha256": sha256(review_path),
                }
            ],
            "boundaries": [],
        },
    )
    return benchmark_path, selection_path, result_path, review_path


def load_fixture(benchmark_path: Path, selection_path: Path, *, strict: bool = True):
    benchmark, root, tasks = repository_benchmark_report.validate_benchmark(benchmark_path)
    selection, runs, warnings = repository_benchmark_report.load_runs(
        benchmark,
        root,
        tasks,
        selection_path,
        strict=strict,
    )
    return benchmark, tasks, selection, runs, warnings


def test_builds_checked_in_strict_report_deterministically(tmp_path: Path) -> None:
    benchmark = ROOT / "examples" / "autoresearch" / "repository-scale" / "benchmark.json"
    selection = ROOT / "examples" / "autoresearch" / "repository-scale" / "run-selection.json"
    checked_json = ROOT / "examples" / "autoresearch" / "repository-scale" / "benchmark-results.json"
    checked_markdown = ROOT / "examples" / "autoresearch" / "repository-scale" / "BENCHMARK_REPORT.md"
    output_json = tmp_path / "benchmark-results.json"
    output_markdown = tmp_path / "BENCHMARK_REPORT.md"

    report = repository_benchmark_report.build(
        argparse.Namespace(
            benchmark=benchmark,
            selection=selection,
            json_output=output_json,
            markdown_output=output_markdown,
            strict=True,
        )
    )

    assert report["inventory"] == {
        "task_count": 4,
        "independent_task_count": 3,
        "unique_repository_count": 3,
        "adversarial_followup_task_count": 1,
        "retained_run_count": 7,
        "selected_primary_run_count": 3,
    }
    assert report["selected_primary_metrics"]["manual_acceptance_rate"]["numerator"] == 2
    assert report["chronological_first_run_metrics"]["manual_pass_at_1"]["numerator"] == 1
    assert report["warnings"] == []
    assert output_json.read_bytes() == checked_json.read_bytes()
    assert output_markdown.read_bytes() == checked_markdown.read_bytes()


def test_strict_mode_rejects_missing_normalized_review(tmp_path: Path) -> None:
    benchmark_path, selection_path, _, review_path = build_fixture(tmp_path)
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review.pop("decision")
    write_json(review_path, review)
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    selection["runs"][0]["review_sha256"] = sha256(review_path)
    write_json(selection_path, selection)

    with pytest.raises(ValueError, match="normalized review decision"):
        load_fixture(benchmark_path, selection_path)

    _, _, _, runs, warnings = load_fixture(benchmark_path, selection_path, strict=False)
    assert runs[0]["manual_decision"] == "unreviewed"
    assert warnings


def test_strict_mode_rejects_unselected_evidence(tmp_path: Path) -> None:
    benchmark_path, selection_path, result_path, _ = build_fixture(tmp_path)
    extra = result_path.parent.parent / "run-2" / "result.json"
    write_json(extra, {"unselected": True})

    with pytest.raises(ValueError, match="missing from run selection"):
        load_fixture(benchmark_path, selection_path)


def test_strict_mode_rejects_tampered_evidence(tmp_path: Path) -> None:
    benchmark_path, selection_path, result_path, _ = build_fixture(tmp_path)
    candidate = result_path.parent / "candidate.patch"
    candidate.write_text("tampered\n", encoding="utf-8")
    with pytest.raises(ValueError, match="result artifact candidate.patch"):
        load_fixture(benchmark_path, selection_path)
