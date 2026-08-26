from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from statistics import fmean, pstdev
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .trajectory import verify_trajectory


CAMPAIGN_VERSION = "repropilot.repeated-repository-benchmark/v1"
RUN_VERSION = "repropilot.repeated-repository-benchmark-run/v1"
MATRIX_VERSION = "repropilot.repeated-repository-benchmark-matrix/v1"
BENCHMARK_VERSION = "repropilot.repository-benchmark/v1"
TASK_VERSION = "repropilot.repository-evaluation-task/v1"
RESULT_VERSION = "repropilot.repository-evaluation-result/v1"
FOLLOWUP_ELIGIBILITY = "followup_only_not_independent_repository_sample"
SHA256_PATTERN = r"^[0-9a-f]{64}$"
REVISION_PATTERN = r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON artifact must contain an object: {path.name}")
    return payload


def resolve_inside(root: Path, relative: str, label: str) -> Path:
    selected = Path(relative)
    if selected.is_absolute() or ".." in selected.parts:
        raise ValueError(f"{label} must remain inside its artifact root")
    resolved = (root / selected).resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{label} escaped its artifact root") from exc
    return resolved


def finite_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label} must be a finite number")
    return float(value)


def optional_finite_number(value: Any, label: str) -> float | None:
    return None if value is None else finite_number(value, label)


def normalize_repository_url(value: str) -> str:
    normalized = value.strip().replace("git@github.com:", "https://github.com/")
    if normalized.endswith(".git"):
        normalized = normalized[:-4]
    return normalized.rstrip("/").lower()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CampaignModel(StrictModel):
    provider: str = Field(min_length=1, max_length=255)
    name: str = Field(min_length=1, max_length=255)


class RepeatedCampaign(StrictModel):
    version: Literal[CAMPAIGN_VERSION] = CAMPAIGN_VERSION
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,95}$")
    benchmark: str
    benchmark_id: str = Field(min_length=1, max_length=128)
    benchmark_sha256: str = Field(pattern=SHA256_PATTERN)
    repetitions_per_task: int = Field(ge=2, le=10)
    execution_order: Literal["round_robin"] = "round_robin"
    execution_mode: Literal["live_model"] = "live_model"
    model: CampaignModel
    max_live_requests_per_run: int = Field(ge=1, le=8)
    require_clean_harness: Literal[True] = True
    require_exact_harness_revision: Literal[True] = True
    require_hash_linked_trajectory: Literal[True] = True
    task_ids: list[str] = Field(min_length=1, max_length=20)
    boundaries: list[str] = Field(default_factory=list, max_length=32)

    @field_validator("task_ids")
    @classmethod
    def validate_task_ids(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("repeated benchmark task ids must be unique")
        if any(not value or len(value) > 128 for value in values):
            raise ValueError("repeated benchmark contains an invalid task id")
        return values


class RepeatedCell(StrictModel):
    ordinal: int = Field(ge=1)
    task_id: str = Field(min_length=1, max_length=128)
    repetition: int = Field(ge=1)
    status: Literal["completed", "incomplete"]
    result: str | None = None
    result_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    classification: str = Field(min_length=1, max_length=128)
    failure: str | None = None
    failure_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_completion_evidence(self) -> "RepeatedCell":
        if self.status == "completed" and (not self.result or not self.result_sha256 or self.failure is not None or self.failure_sha256 is not None):
            raise ValueError("completed repeated benchmark cell requires only a result and SHA-256")
        if self.status == "incomplete" and (self.result is not None or self.result_sha256 is not None):
            raise ValueError("incomplete repeated benchmark cell cannot claim a completed result")
        if self.status == "incomplete" and (not self.failure or self.failure_sha256 is None):
            raise ValueError("incomplete repeated benchmark cell requires a failure artifact and hash")
        return self


class RepeatedRun(StrictModel):
    version: Literal[RUN_VERSION] = RUN_VERSION
    campaign_id: str
    campaign_sha256: str = Field(pattern=SHA256_PATTERN)
    benchmark_sha256: str = Field(pattern=SHA256_PATTERN)
    harness_revision: str = Field(pattern=REVISION_PATTERN)
    source_tree_dirty: Literal[False] = False
    model: CampaignModel
    max_live_requests_per_run: int = Field(ge=1, le=8)
    planned_cell_count: int = Field(ge=1)
    preflight: str | None = None
    preflight_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    cells: list[RepeatedCell] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_preflight_binding(self) -> "RepeatedRun":
        if (self.preflight is None) != (self.preflight_sha256 is None):
            raise ValueError("repeated run preflight path and hash must be provided together")
        if self.cells and self.preflight is None:
            raise ValueError("repeated run cells require a bound preflight artifact")
        return self


def load_campaign(path: Path) -> tuple[RepeatedCampaign, Path, dict[str, dict[str, Any]]]:
    campaign_path = path.resolve(strict=True)
    root = campaign_path.parent
    campaign = RepeatedCampaign.model_validate(read_object(campaign_path))
    benchmark_path = resolve_inside(root, campaign.benchmark, "campaign benchmark")
    if sha256_file(benchmark_path) != campaign.benchmark_sha256:
        raise ValueError("campaign benchmark SHA-256 mismatch")
    benchmark = read_object(benchmark_path)
    if benchmark.get("version") != BENCHMARK_VERSION or benchmark.get("id") != campaign.benchmark_id:
        raise ValueError("campaign benchmark identity mismatch")
    raw_tasks = benchmark.get("tasks")
    if not isinstance(raw_tasks, list):
        raise ValueError("campaign benchmark tasks are missing")
    tasks: dict[str, dict[str, Any]] = {}
    for entry in raw_tasks:
        if not isinstance(entry, dict):
            raise ValueError("campaign benchmark task entry must be an object")
        task_id = str(entry.get("id", ""))
        if task_id:
            tasks[task_id] = entry
    for task_id in campaign.task_ids:
        if task_id not in tasks:
            raise ValueError(f"campaign references unknown benchmark task: {task_id}")
        if tasks[task_id].get("aggregate_eligibility") == FOLLOWUP_ELIGIBILITY:
            raise ValueError(f"campaign cannot count an adversarial follow-up as independent: {task_id}")
        task_dir = resolve_inside(root, str(tasks[task_id].get("path", "")), f"campaign task {task_id}")
        task_contract = read_object(resolve_inside(task_dir, "task.json", f"campaign task contract {task_id}"))
        if task_contract.get("version") != TASK_VERSION or task_contract.get("id") != task_id:
            raise ValueError(f"campaign task contract identity mismatch: {task_id}")
        repository = task_contract.get("repository")
        if not isinstance(repository, dict):
            raise ValueError(f"campaign task repository binding is missing: {task_id}")
        if normalize_repository_url(str(repository.get("url", ""))) != normalize_repository_url(str(tasks[task_id].get("repository_url", ""))):
            raise ValueError(f"campaign task repository URL mismatch: {task_id}")
        if str(repository.get("revision", "")).lower() != str(tasks[task_id].get("revision", "")).lower():
            raise ValueError(f"campaign task repository revision mismatch: {task_id}")
        contract_hashes = tasks[task_id].get("contract_sha256")
        if not isinstance(contract_hashes, dict) or not contract_hashes:
            raise ValueError(f"campaign task contract hashes are missing: {task_id}")
        for relative, expected in contract_hashes.items():
            artifact = resolve_inside(task_dir, str(relative), f"campaign task contract {task_id}")
            if sha256_file(artifact) != str(expected).lower():
                raise ValueError(f"campaign task contract SHA-256 mismatch: {task_id}/{relative}")
        tasks[task_id] = {**tasks[task_id], "task_dir": task_dir, "task": task_contract}
    return campaign, campaign_path, tasks


def planned_cells(campaign: RepeatedCampaign) -> list[tuple[int, str, int]]:
    return [
        (ordinal, task_id, repetition)
        for ordinal, (repetition, task_id) in enumerate(
            (
                (repetition, task_id)
                for repetition in range(1, campaign.repetitions_per_task + 1)
                for task_id in campaign.task_ids
            ),
            start=1,
        )
    ]


def validate_run_plan(campaign: RepeatedCampaign, campaign_path: Path, run: RepeatedRun) -> None:
    if run.campaign_id != campaign.id:
        raise ValueError("repeated run campaign id mismatch")
    if run.campaign_sha256 != sha256_file(campaign_path):
        raise ValueError("repeated run campaign SHA-256 mismatch")
    if run.benchmark_sha256 != campaign.benchmark_sha256:
        raise ValueError("repeated run benchmark SHA-256 mismatch")
    if run.model != campaign.model:
        raise ValueError("repeated run model identity mismatch")
    if run.max_live_requests_per_run != campaign.max_live_requests_per_run:
        raise ValueError("repeated run request budget mismatch")
    expected = planned_cells(campaign)
    if run.planned_cell_count != len(expected):
        raise ValueError("repeated run planned cell count mismatch")
    if len(run.cells) > len(expected):
        raise ValueError("repeated run contains more cells than the frozen plan")
    for cell, (ordinal, task_id, repetition) in zip(run.cells, expected):
        if (cell.ordinal, cell.task_id, cell.repetition) != (ordinal, task_id, repetition):
            raise ValueError("repeated run cells do not match the frozen round-robin order")


def validate_result_artifacts(result_dir: Path, result: dict[str, Any]) -> None:
    hashes = result.get("artifact_sha256")
    if not isinstance(hashes, dict) or not hashes:
        raise ValueError("repeated benchmark result artifact hashes are missing")
    for relative, expected in hashes.items():
        artifact = resolve_inside(result_dir, str(relative), "result artifact")
        if sha256_file(artifact) != str(expected).lower():
            raise ValueError(f"repeated benchmark result artifact hash mismatch: {relative}")


def validate_cell_result(
    campaign: RepeatedCampaign,
    run: RepeatedRun,
    run_root: Path,
    cell: RepeatedCell,
    task: dict[str, Any],
) -> dict[str, Any]:
    assert cell.result is not None and cell.result_sha256 is not None
    result_path = resolve_inside(run_root, cell.result, "repeated benchmark result")
    if sha256_file(result_path) != cell.result_sha256:
        raise ValueError(f"repeated benchmark result SHA-256 mismatch at cell {cell.ordinal}")
    result = read_object(result_path)
    if result.get("version") != RESULT_VERSION or result.get("task_id") != cell.task_id:
        raise ValueError(f"repeated benchmark result identity mismatch at cell {cell.ordinal}")
    harness = result.get("harness")
    if not isinstance(harness, dict) or harness.get("source_tree_dirty") is not False:
        raise ValueError(f"repeated benchmark result used a dirty harness at cell {cell.ordinal}")
    if str(harness.get("revision", "")).lower() != run.harness_revision:
        raise ValueError(f"repeated benchmark harness revision mismatch at cell {cell.ordinal}")
    repository = result.get("repository")
    if not isinstance(repository, dict):
        raise ValueError(f"repeated benchmark repository binding is missing at cell {cell.ordinal}")
    if normalize_repository_url(str(repository.get("url", ""))) != normalize_repository_url(str(task.get("repository_url", ""))):
        raise ValueError(f"repeated benchmark repository URL mismatch at cell {cell.ordinal}")
    if str(repository.get("revision", "")).lower() != str(task.get("revision", "")).lower():
        raise ValueError(f"repeated benchmark repository revision mismatch at cell {cell.ordinal}")
    expected_baseline = str(task.get("contract_sha256", {}).get("baseline.json", "")).lower()
    if not expected_baseline or str(result.get("baseline_artifact_sha256", "")).lower() != expected_baseline:
        raise ValueError(f"repeated benchmark baseline contract mismatch at cell {cell.ordinal}")
    model = result.get("model")
    if not isinstance(model, dict) or model.get("mode") != campaign.execution_mode:
        raise ValueError(f"repeated benchmark result mode mismatch at cell {cell.ordinal}")
    if str(model.get("provider", "")) != campaign.model.provider or str(model.get("model", "")) != campaign.model.name:
        raise ValueError(f"repeated benchmark model identity mismatch at cell {cell.ordinal}")
    if int(result.get("search", {}).get("request_cap", 0)) != campaign.max_live_requests_per_run:
        raise ValueError(f"repeated benchmark request cap mismatch at cell {cell.ordinal}")
    validate_result_artifacts(result_path.parent, result)
    spec = read_object(result_path.parent / "frozen-spec.json")
    ledger_path = result_path.parent / "trial-ledger.json"
    validation_path = result_path.parent / "validation-report.json"
    ledger = read_object(ledger_path) if ledger_path.is_file() else None
    validation = read_object(validation_path) if validation_path.is_file() else None
    failure = result.get("failure")
    if failure is not None and not isinstance(failure, dict):
        raise ValueError(f"repeated benchmark failure binding is invalid at cell {cell.ordinal}")
    verify_trajectory(
        (result_path.parent / "trajectory.jsonl").read_text(encoding="utf-8"),
        (result_path.parent / "trajectory-manifest.json").read_text(encoding="utf-8"),
        spec_sha256=str(spec.get("spec_sha256") or ""),
        ledger=ledger,
        validation=validation,
        failure=failure,
    )
    if cell.classification != str(result.get("outcome", "unknown")):
        raise ValueError(f"repeated benchmark cell classification mismatch at cell {cell.ordinal}")
    return result


def ratio(numerator: int, denominator: int) -> dict[str, Any]:
    return {"numerator": numerator, "denominator": denominator, "rate": numerator / denominator if denominator else None}


def score_summary(values: list[float]) -> dict[str, Any]:
    return {
        "count": len(values),
        "mean": fmean(values) if values else None,
        "stddev": pstdev(values) if len(values) > 1 else 0.0 if values else None,
        "minimum": min(values) if values else None,
        "maximum": max(values) if values else None,
    }


def incomplete_usage_evidence(payload: dict[str, Any], request_cap: int, ordinal: int) -> dict[str, int | bool]:
    usage = payload.get("usage")
    if usage is None:
        return {
            "attempted_requests": 0,
            "completed_responses": 0,
            "usage_reports": 0,
            "reported_tokens": 0,
            "maximum_unobserved_attempts": request_cap,
            "usage_unknown": True,
        }
    if not isinstance(usage, dict) or usage.get("status") not in {"partial", "unknown"}:
        raise ValueError(f"repeated benchmark incomplete usage metadata is invalid at cell {ordinal}")
    if usage["status"] == "unknown":
        nullable = (
            "attempted_requests",
            "completed_responses",
            "usage_reports",
            "prompt_tokens",
            "completion_tokens",
            "reported_tokens",
        )
        if any(usage.get(key) is not None for key in nullable) or usage.get("maximum_unobserved_attempts") != request_cap:
            raise ValueError(f"repeated benchmark unknown usage bounds are invalid at cell {ordinal}")
        return {
            "attempted_requests": 0,
            "completed_responses": 0,
            "usage_reports": 0,
            "reported_tokens": 0,
            "maximum_unobserved_attempts": request_cap,
            "usage_unknown": True,
        }
    try:
        counters = {
            key: int(usage[key])
            for key in (
                "attempted_requests",
                "completed_responses",
                "usage_reports",
                "prompt_tokens",
                "completion_tokens",
                "reported_tokens",
            )
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"repeated benchmark partial usage counters are invalid at cell {ordinal}") from exc
    if (
        any(value < 0 for value in counters.values())
        or counters["attempted_requests"] > request_cap
        or counters["completed_responses"] > counters["attempted_requests"]
        or counters["usage_reports"] > counters["completed_responses"]
        or counters["reported_tokens"] != counters["prompt_tokens"] + counters["completion_tokens"]
        or usage.get("maximum_unobserved_attempts") != 0
    ):
        raise ValueError(f"repeated benchmark partial usage bounds are invalid at cell {ordinal}")
    return {
        **{key: counters[key] for key in ("attempted_requests", "completed_responses", "usage_reports", "reported_tokens")},
        "maximum_unobserved_attempts": 0,
        "usage_unknown": False,
    }


def build_repeated_matrix(campaign_path: Path, run_path: Path) -> dict[str, Any]:
    campaign, resolved_campaign, tasks = load_campaign(campaign_path)
    resolved_run = run_path.resolve(strict=True)
    run_root = resolved_run.parent
    run = RepeatedRun.model_validate(read_object(resolved_run))
    validate_run_plan(campaign, resolved_campaign, run)
    assert run.preflight is not None and run.preflight_sha256 is not None
    preflight_path = resolve_inside(run_root, run.preflight, "repeated benchmark preflight")
    if sha256_file(preflight_path) != run.preflight_sha256:
        raise ValueError("repeated benchmark preflight SHA-256 mismatch")
    planned_count = len(planned_cells(campaign))
    results: dict[tuple[str, int], dict[str, Any]] = {}
    outcome_distribution: Counter[str] = Counter()
    incomplete_distribution: Counter[str] = Counter()
    attempted_requests = 0
    completed_responses_total = 0
    usage_reports_total = 0
    reported_tokens = 0
    maximum_unobserved_attempts = 0
    incomplete_cells_with_unknown_usage = 0
    cost_amounts: list[float] = []
    cost_currency = ""
    for cell in run.cells:
        if cell.status == "incomplete":
            assert cell.failure is not None and cell.failure_sha256 is not None
            failure_path = resolve_inside(run_root, cell.failure, "repeated benchmark failure")
            if sha256_file(failure_path) != cell.failure_sha256:
                raise ValueError(f"repeated benchmark failure SHA-256 mismatch at cell {cell.ordinal}")
            failure_payload = read_object(failure_path)
            if failure_payload.get("classification") != cell.classification:
                raise ValueError(f"repeated benchmark failure classification mismatch at cell {cell.ordinal}")
            incomplete_distribution[cell.classification] += 1
            incomplete_usage = incomplete_usage_evidence(failure_payload, campaign.max_live_requests_per_run, cell.ordinal)
            attempted_requests += int(incomplete_usage["attempted_requests"])
            completed_responses_total += int(incomplete_usage["completed_responses"])
            usage_reports_total += int(incomplete_usage["usage_reports"])
            reported_tokens += int(incomplete_usage["reported_tokens"])
            maximum_unobserved_attempts += int(incomplete_usage["maximum_unobserved_attempts"])
            incomplete_cells_with_unknown_usage += int(bool(incomplete_usage["usage_unknown"]))
            continue
        result = validate_cell_result(campaign, run, run_root, cell, tasks[cell.task_id])
        results[(cell.task_id, cell.repetition)] = result
        outcome_distribution[str(result.get("outcome", "unknown"))] += 1
        model = result.get("model", {})
        cell_attempts = int(model.get("attempted_request_count", 0))
        completed_responses = int(model.get("request_count", 0))
        usage_reports = int(model.get("reported_request_count", 0))
        cell_tokens = int(model.get("total_tokens", 0))
        if (
            cell_attempts < 0
            or cell_attempts > campaign.max_live_requests_per_run
            or usage_reports < 0
            or completed_responses < usage_reports
            or cell_attempts < completed_responses
            or cell_tokens < 0
        ):
            raise ValueError(f"repeated benchmark model counters are invalid at cell {cell.ordinal}")
        attempted_requests += cell_attempts
        completed_responses_total += completed_responses
        usage_reports_total += usage_reports
        reported_tokens += cell_tokens
        cost = result.get("cost", {})
        amount = optional_finite_number(cost.get("amount"), f"cell {cell.ordinal} cost")
        if amount is not None:
            currency = str(cost.get("currency", ""))
            if amount < 0 or not currency:
                raise ValueError(f"repeated benchmark cost metadata is invalid at cell {cell.ordinal}")
            if cost_currency and currency != cost_currency:
                raise ValueError("repeated benchmark contains mixed cost currencies")
            cost_currency = currency
            cost_amounts.append(amount)

    task_rows: list[dict[str, Any]] = []
    all_repeat_passes = 0
    at_least_one_passes = 0
    first_run_passes = 0
    total_passes = 0
    for task_id in campaign.task_ids:
        task_results = [results[(task_id, repetition)] for repetition in range(1, campaign.repetitions_per_task + 1) if (task_id, repetition) in results]
        pass_flags = [result.get("outcome") == "validation_passed" for result in task_results]
        pass_count = sum(pass_flags)
        total_passes += pass_count
        complete = len(task_results) == campaign.repetitions_per_task
        all_passed = complete and pass_count == campaign.repetitions_per_task
        at_least_one = pass_count > 0
        first_passed = results.get((task_id, 1), {}).get("outcome") == "validation_passed"
        all_repeat_passes += int(all_passed)
        at_least_one_passes += int(at_least_one)
        first_run_passes += int(first_passed)
        hidden_scores = [
            value
            for result in task_results
            if (value := optional_finite_number(result.get("validation", {}).get("observed_score"), f"{task_id} hidden score")) is not None
        ]
        task_rows.append(
            {
                "task_id": task_id,
                "planned_repetitions": campaign.repetitions_per_task,
                "completed_repetitions": len(task_results),
                "automated_passes": pass_count,
                "automated_pass_rate": ratio(pass_count, campaign.repetitions_per_task),
                "all_repetitions_passed": all_passed if complete else None,
                "at_least_one_passed": at_least_one,
                "first_repetition_passed": first_passed,
                "hidden_score": score_summary(hidden_scores),
                "outcomes": [results.get((task_id, repetition), {}).get("outcome", "incomplete") for repetition in range(1, campaign.repetitions_per_task + 1)],
            }
        )

    completed_count = len(results)
    task_count = len(campaign.task_ids)
    return {
        "version": MATRIX_VERSION,
        "campaign_id": campaign.id,
        "campaign_sha256": sha256_file(resolved_campaign),
        "run_manifest_sha256": sha256_file(resolved_run),
        "benchmark_id": campaign.benchmark_id,
        "benchmark_sha256": campaign.benchmark_sha256,
        "harness_revision": run.harness_revision,
        "model": campaign.model.model_dump(mode="json"),
        "execution_order": campaign.execution_order,
        "preflight_sha256": run.preflight_sha256,
        "planned": {"task_count": task_count, "repetitions_per_task": campaign.repetitions_per_task, "cell_count": planned_count},
        "completion": {"status": "complete" if len(run.cells) == planned_count and completed_count == planned_count else "incomplete", **ratio(completed_count, planned_count), "recorded_cell_count": len(run.cells)},
        "automated_cell_pass_rate": ratio(total_passes, planned_count),
        "first_repetition_pass_rate": ratio(first_run_passes, task_count),
        "task_all_repetitions_pass_rate": ratio(all_repeat_passes, task_count),
        "task_at_least_one_pass_rate": ratio(at_least_one_passes, task_count),
        "outcome_distribution": dict(sorted(outcome_distribution.items())),
        "incomplete_distribution": dict(sorted(incomplete_distribution.items())),
        "usage": {
            "attempted_requests": attempted_requests,
            "known_attempted_requests": attempted_requests,
            "completed_responses": completed_responses_total,
            "usage_reports": usage_reports_total,
            "reported_tokens": reported_tokens,
            "maximum_unobserved_attempts": maximum_unobserved_attempts,
            "attempted_request_bounds": {
                "minimum": attempted_requests,
                "maximum": attempted_requests + maximum_unobserved_attempts,
            },
            "incomplete_cells_with_unknown_usage": incomplete_cells_with_unknown_usage,
            "known_token_derived_cost": {
                "currency": cost_currency or None,
                "amount": sum(cost_amounts) if cost_amounts else None,
                "cells_with_calculated_cost": len(cost_amounts),
            },
        },
        "cells": [cell.model_dump(mode="json") for cell in run.cells],
        "tasks": task_rows,
        "boundaries": [
            "All rates use the frozen planned denominator; incomplete cells are not silently dropped.",
            "Automated contract pass is not a manual acceptance or upstream-readiness claim.",
            "Known cost is token-derived from retained run metadata and is not a billing receipt.",
            "Usage from incomplete cells is counted when checkpointed; otherwise request bounds retain the frozen per-cell cap instead of treating unknown usage as zero.",
        ],
    }
