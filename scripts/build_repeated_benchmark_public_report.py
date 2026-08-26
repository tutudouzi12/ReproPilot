from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any


MATRIX_VERSION = "repropilot.repeated-repository-benchmark-matrix/v1"
PUBLIC_REPORT_VERSION = "repropilot.repeated-repository-benchmark-public-report/v1"
SHA256 = re.compile(r"^[0-9a-f]{64}$")
REVISION = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:/-]{1,128}$")
SAFE_RELATIVE_PATH = re.compile(r"^[A-Za-z0-9_.:/-]{1,512}$")
WINDOWS_ABSOLUTE_PATH = re.compile(r"(?<![A-Za-z0-9_])[A-Za-z]:[\\/]")
POSIX_ABSOLUTE_PATH = re.compile(r"(?<![A-Za-z0-9_])/(?:home|Users|tmp|var/tmp|workspace|app)/")
SECRET_PATTERNS = (
    re.compile(r"(?<![A-Za-z0-9])sk-(?:proj-)?[A-Za-z0-9_-]{8,}"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"(?i)\b(?:api[_-]?key|access[_-]?token|password|secret)\s*[:=]\s*\S+"),
)
FORBIDDEN_FIELDS = {
    "api_key",
    "access_token",
    "password",
    "prompt",
    "raw_content",
    "request_error",
    "response",
    "safe_diagnostic",
    "secret",
    "stderr",
    "stdout",
}
TOP_LEVEL_FIELDS = {
    "version",
    "campaign_id",
    "campaign_sha256",
    "run_manifest_sha256",
    "benchmark_id",
    "benchmark_sha256",
    "harness_revision",
    "model",
    "execution_order",
    "preflight_sha256",
    "planned",
    "completion",
    "automated_cell_pass_rate",
    "first_repetition_pass_rate",
    "task_all_repetitions_pass_rate",
    "task_at_least_one_pass_rate",
    "outcome_distribution",
    "incomplete_distribution",
    "usage",
    "cells",
    "tasks",
    "boundaries",
}
CELL_FIELDS = {
    "ordinal",
    "task_id",
    "repetition",
    "status",
    "result",
    "result_sha256",
    "classification",
    "failure",
    "failure_sha256",
}
TASK_FIELDS = {
    "task_id",
    "planned_repetitions",
    "completed_repetitions",
    "automated_passes",
    "automated_pass_rate",
    "all_repetitions_passed",
    "at_least_one_passed",
    "first_repetition_passed",
    "hidden_score",
    "outcomes",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("public repeated benchmark matrix must contain a JSON object")
    return payload


def write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}-{os.getpid()}.tmp"
    try:
        temporary.write_text(content, encoding="utf-8", newline="\n")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def require_sha256(value: Any, label: str) -> str:
    normalized = str(value).lower()
    if not SHA256.fullmatch(normalized):
        raise ValueError(f"{label} must contain a lowercase SHA-256 value")
    return normalized


def require_nonnegative_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return value


def require_identifier(value: Any, label: str) -> str:
    selected = str(value)
    if not SAFE_IDENTIFIER.fullmatch(selected):
        raise ValueError(f"{label} must be a safe identifier")
    return selected


def require_fields(payload: dict[str, Any], expected: set[str], label: str) -> None:
    if set(payload) != expected:
        raise ValueError(f"{label} fields do not match the reviewed public schema")


def iter_items(value: Any):
    if isinstance(value, dict):
        for key, selected in value.items():
            yield str(key), selected
            yield from iter_items(selected)
    elif isinstance(value, list):
        for selected in value:
            yield "", selected
            yield from iter_items(selected)


def validate_public_safety(matrix: dict[str, Any]) -> None:
    for key, value in iter_items(matrix):
        if key.lower() in FORBIDDEN_FIELDS:
            raise ValueError(f"public repeated benchmark matrix contains forbidden field: {key}")
        if not isinstance(value, str):
            continue
        if WINDOWS_ABSOLUTE_PATH.search(value) or POSIX_ABSOLUTE_PATH.search(value):
            raise ValueError("public repeated benchmark matrix contains an absolute local path")
        if any(pattern.search(value) for pattern in SECRET_PATTERNS):
            raise ValueError("public repeated benchmark matrix contains credential-like text")


def require_ratio(
    payload: Any,
    numerator: int,
    denominator: int,
    label: str,
    *,
    extra_fields: set[str] | None = None,
) -> None:
    expected_fields = {"numerator", "denominator", "rate"} | (extra_fields or set())
    if not isinstance(payload, dict) or set(payload) != expected_fields:
        raise ValueError(f"{label} must contain numerator, denominator and rate")
    if payload.get("numerator") != numerator or payload.get("denominator") != denominator:
        raise ValueError(f"{label} numerator or denominator is inconsistent")
    expected_rate = numerator / denominator if denominator else None
    actual_rate = payload.get("rate")
    if expected_rate is None:
        if actual_rate is not None:
            raise ValueError(f"{label} rate is inconsistent")
    elif isinstance(actual_rate, bool) or not isinstance(actual_rate, (int, float)) or not math.isclose(actual_rate, expected_rate):
        raise ValueError(f"{label} rate is inconsistent")


def require_relative_evidence_path(value: Any, label: str) -> None:
    if value is None:
        return
    if not isinstance(value, str) or "\\" in value or not SAFE_RELATIVE_PATH.fullmatch(value):
        raise ValueError(f"{label} must use a relative portable path")
    selected = PurePosixPath(value)
    if selected.is_absolute() or ".." in selected.parts:
        raise ValueError(f"{label} must remain relative")


def validate_matrix(matrix: dict[str, Any]) -> dict[str, Any]:
    validate_public_safety(matrix)
    require_fields(matrix, TOP_LEVEL_FIELDS, "public repeated benchmark matrix")
    if matrix.get("version") != MATRIX_VERSION:
        raise ValueError("unsupported repeated benchmark matrix version")
    require_identifier(matrix.get("campaign_id"), "campaign id")
    require_identifier(matrix.get("benchmark_id"), "benchmark id")
    require_identifier(matrix.get("execution_order"), "execution order")
    for field in ("campaign_sha256", "run_manifest_sha256", "benchmark_sha256", "preflight_sha256"):
        require_sha256(matrix.get(field), field)
    if not REVISION.fullmatch(str(matrix.get("harness_revision", ""))):
        raise ValueError("harness_revision is invalid")

    model = matrix.get("model")
    if not isinstance(model, dict) or set(model) != {"provider", "name"} or not all(
        isinstance(model.get(field), str) and model[field] for field in ("provider", "name")
    ):
        raise ValueError("public repeated benchmark model identity is invalid")
    require_identifier(model["provider"], "model provider")
    require_identifier(model["name"], "model name")

    planned = matrix.get("planned")
    if not isinstance(planned, dict) or set(planned) != {"task_count", "repetitions_per_task", "cell_count"}:
        raise ValueError("public repeated benchmark plan is invalid")
    task_count = require_nonnegative_int(planned["task_count"], "planned task count")
    repetitions = require_nonnegative_int(planned["repetitions_per_task"], "planned repetitions")
    cell_count = require_nonnegative_int(planned["cell_count"], "planned cell count")
    if not task_count or not repetitions or cell_count != task_count * repetitions:
        raise ValueError("public repeated benchmark planned denominator is inconsistent")

    cells = matrix.get("cells")
    if not isinstance(cells, list) or len(cells) > cell_count:
        raise ValueError("public repeated benchmark cells are invalid")
    completed_cells: list[dict[str, Any]] = []
    incomplete_cells: list[dict[str, Any]] = []
    seen_coordinates: set[tuple[str, int]] = set()
    task_ids: set[str] = set()
    for expected_ordinal, cell in enumerate(cells, start=1):
        if not isinstance(cell, dict):
            raise ValueError("public repeated benchmark cell must be an object")
        require_fields(cell, CELL_FIELDS, f"cell {expected_ordinal}")
        if cell.get("ordinal") != expected_ordinal:
            raise ValueError("public repeated benchmark cell ordinals are not contiguous")
        task_id = require_identifier(cell.get("task_id"), f"cell {expected_ordinal} task id")
        repetition = require_nonnegative_int(cell.get("repetition"), f"cell {expected_ordinal} repetition")
        coordinate = (task_id, repetition)
        if not task_id or repetition < 1 or repetition > repetitions or coordinate in seen_coordinates:
            raise ValueError(f"public repeated benchmark coordinate is invalid at cell {expected_ordinal}")
        seen_coordinates.add(coordinate)
        task_ids.add(task_id)
        require_identifier(cell.get("classification"), f"cell {expected_ordinal} classification")
        require_relative_evidence_path(cell.get("result"), f"cell {expected_ordinal} result")
        require_relative_evidence_path(cell.get("failure"), f"cell {expected_ordinal} failure")
        if cell.get("status") == "completed":
            if cell.get("result") is None or cell.get("failure") is not None or cell.get("failure_sha256") is not None:
                raise ValueError(f"completed public cell evidence is invalid at cell {expected_ordinal}")
            require_sha256(cell.get("result_sha256"), f"cell {expected_ordinal} result")
            completed_cells.append(cell)
        elif cell.get("status") == "incomplete":
            if cell.get("failure") is None or cell.get("result") is not None or cell.get("result_sha256") is not None:
                raise ValueError(f"incomplete public cell evidence is invalid at cell {expected_ordinal}")
            require_sha256(cell.get("failure_sha256"), f"cell {expected_ordinal} failure")
            incomplete_cells.append(cell)
        else:
            raise ValueError(f"unsupported public cell status at cell {expected_ordinal}")

    if len(task_ids) != task_count:
        raise ValueError("public repeated benchmark task count is inconsistent")
    completed_count = len(completed_cells)
    pass_count = sum(cell["classification"] == "validation_passed" for cell in completed_cells)
    completion = matrix.get("completion")
    if not isinstance(completion, dict) or set(completion) != {
        "status",
        "numerator",
        "denominator",
        "rate",
        "recorded_cell_count",
    }:
        raise ValueError("public repeated benchmark completion metadata is invalid")
    require_ratio(
        completion,
        completed_count,
        cell_count,
        "completion",
        extra_fields={"status", "recorded_cell_count"},
    )
    if completion["recorded_cell_count"] != len(cells):
        raise ValueError("public repeated benchmark recorded cell count is inconsistent")
    expected_status = "complete" if completed_count == cell_count and len(cells) == cell_count else "incomplete"
    if completion["status"] != expected_status:
        raise ValueError("public repeated benchmark completion status is inconsistent")
    require_ratio(matrix.get("automated_cell_pass_rate"), pass_count, cell_count, "automated cell pass rate")

    first_passes = sum(
        cell["repetition"] == 1 and cell["classification"] == "validation_passed" for cell in completed_cells
    )
    require_ratio(matrix.get("first_repetition_pass_rate"), first_passes, task_count, "first repetition pass rate")
    outcomes = Counter(cell["classification"] for cell in completed_cells)
    incomplete = Counter(cell["classification"] for cell in incomplete_cells)
    if matrix.get("outcome_distribution") != dict(sorted(outcomes.items())):
        raise ValueError("public repeated benchmark outcome distribution is inconsistent")
    if matrix.get("incomplete_distribution") != dict(sorted(incomplete.items())):
        raise ValueError("public repeated benchmark incomplete distribution is inconsistent")

    tasks = matrix.get("tasks")
    if not isinstance(tasks, list) or len(tasks) != task_count:
        raise ValueError("public repeated benchmark task rows are invalid")
    if {str(task.get("task_id", "")) for task in tasks if isinstance(task, dict)} != task_ids:
        raise ValueError("public repeated benchmark task rows do not match cells")
    all_repetition_passes = 0
    at_least_one_passes = 0
    for task in tasks:
        if not isinstance(task, dict):
            raise ValueError("public repeated benchmark task row must be an object")
        task_id = str(task.get("task_id", ""))
        require_fields(task, TASK_FIELDS, f"task {task_id}")
        selected = [cell for cell in completed_cells if cell["task_id"] == task_id]
        selected_passes = sum(cell["classification"] == "validation_passed" for cell in selected)
        if (
            task.get("planned_repetitions") != repetitions
            or task.get("completed_repetitions") != len(selected)
            or task.get("automated_passes") != selected_passes
        ):
            raise ValueError(f"public repeated benchmark task counts are inconsistent for {task_id}")
        require_ratio(task.get("automated_pass_rate"), selected_passes, repetitions, f"task {task_id} pass rate")
        expected_outcomes = []
        for repetition in range(1, repetitions + 1):
            match = next((cell for cell in selected if cell["repetition"] == repetition), None)
            expected_outcomes.append(match["classification"] if match is not None else "incomplete")
        if task.get("outcomes") != expected_outcomes:
            raise ValueError(f"public repeated benchmark task outcomes are inconsistent for {task_id}")
        hidden_score = task.get("hidden_score")
        if not isinstance(hidden_score, dict) or set(hidden_score) != {
            "count",
            "mean",
            "minimum",
            "maximum",
            "stddev",
        }:
            raise ValueError(f"public repeated benchmark hidden-score fields are invalid for {task_id}")
        hidden_count = require_nonnegative_int(hidden_score["count"], f"task {task_id} hidden-score count")
        if hidden_count != len(selected):
            raise ValueError(f"public repeated benchmark hidden-score count is inconsistent for {task_id}")
        for field in ("mean", "minimum", "maximum", "stddev"):
            value = hidden_score[field]
            if hidden_count:
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                    raise ValueError(f"public repeated benchmark hidden-score {field} is invalid for {task_id}")
            elif value is not None:
                raise ValueError(f"public repeated benchmark empty hidden-score {field} is invalid for {task_id}")
        complete = len(selected) == repetitions
        all_passed = complete and selected_passes == repetitions
        at_least_one = selected_passes > 0
        first_passed = expected_outcomes[0] == "validation_passed"
        if task.get("all_repetitions_passed") != (all_passed if complete else None):
            raise ValueError(f"public repeated benchmark all-repeat status is inconsistent for {task_id}")
        if task.get("at_least_one_passed") != at_least_one or task.get("first_repetition_passed") != first_passed:
            raise ValueError(f"public repeated benchmark task pass flags are inconsistent for {task_id}")
        all_repetition_passes += int(all_passed)
        at_least_one_passes += int(at_least_one)
    require_ratio(
        matrix.get("task_all_repetitions_pass_rate"),
        all_repetition_passes,
        task_count,
        "task all-repetitions pass rate",
    )
    require_ratio(
        matrix.get("task_at_least_one_pass_rate"),
        at_least_one_passes,
        task_count,
        "task at-least-one pass rate",
    )

    usage = matrix.get("usage")
    expected_usage_fields = {
        "attempted_requests",
        "known_attempted_requests",
        "completed_responses",
        "usage_reports",
        "reported_tokens",
        "maximum_unobserved_attempts",
        "attempted_request_bounds",
        "incomplete_cells_with_unknown_usage",
        "known_token_derived_cost",
    }
    if not isinstance(usage, dict) or set(usage) != expected_usage_fields:
        raise ValueError("public repeated benchmark usage fields are invalid")
    for field in (
        "attempted_requests",
        "known_attempted_requests",
        "completed_responses",
        "usage_reports",
        "reported_tokens",
        "maximum_unobserved_attempts",
        "incomplete_cells_with_unknown_usage",
    ):
        require_nonnegative_int(usage.get(field), f"usage {field}")
    if usage["attempted_requests"] != usage["known_attempted_requests"]:
        raise ValueError("public repeated benchmark known request count is inconsistent")
    if usage["usage_reports"] > usage["completed_responses"] or usage["completed_responses"] > usage["attempted_requests"]:
        raise ValueError("public repeated benchmark response counters are inconsistent")
    bounds = usage.get("attempted_request_bounds")
    if not isinstance(bounds, dict) or set(bounds) != {"minimum", "maximum"}:
        raise ValueError("public repeated benchmark request bounds are invalid")
    require_nonnegative_int(bounds["minimum"], "usage request-bound minimum")
    require_nonnegative_int(bounds["maximum"], "usage request-bound maximum")
    if bounds["minimum"] != usage["known_attempted_requests"] or bounds["maximum"] != (
        bounds["minimum"] + usage["maximum_unobserved_attempts"]
    ):
        raise ValueError("public repeated benchmark request bounds are inconsistent")
    if usage["incomplete_cells_with_unknown_usage"] > len(incomplete_cells):
        raise ValueError("public repeated benchmark unknown-usage cell count is inconsistent")
    cost = usage.get("known_token_derived_cost")
    if not isinstance(cost, dict) or set(cost) != {"currency", "amount", "cells_with_calculated_cost"}:
        raise ValueError("public repeated benchmark cost fields are invalid")
    cost_cells = require_nonnegative_int(cost["cells_with_calculated_cost"], "cost cell count")
    if cost_cells > completed_count:
        raise ValueError("public repeated benchmark cost cell count is inconsistent")
    if cost_cells:
        if not isinstance(cost["currency"], str) or not cost["currency"]:
            raise ValueError("public repeated benchmark cost currency is invalid")
        if isinstance(cost["amount"], bool) or not isinstance(cost["amount"], (int, float)) or not math.isfinite(cost["amount"]) or cost["amount"] < 0:
            raise ValueError("public repeated benchmark cost amount is invalid")
    elif cost["currency"] is not None or cost["amount"] is not None:
        raise ValueError("public repeated benchmark empty cost metadata is inconsistent")
    if not isinstance(matrix.get("boundaries"), list) or not matrix["boundaries"]:
        raise ValueError("public repeated benchmark boundaries are missing")

    return {
        "planned_cells": cell_count,
        "recorded_cells": len(cells),
        "completed_cells": completed_count,
        "automated_passes": pass_count,
        "incomplete_cells": len(incomplete_cells),
        "known_attempted_requests": usage["known_attempted_requests"],
        "maximum_attempted_requests": bounds["maximum"],
    }


def format_rate(payload: dict[str, Any]) -> str:
    return f"{payload['numerator']}/{payload['denominator']} ({payload['rate']:.4f})"


def render_markdown(matrix: dict[str, Any], matrix_sha256: str, original_matrix_sha256: str) -> str:
    usage = matrix["usage"]
    bounds = usage["attempted_request_bounds"]
    lines = [
        "# ReproPilot repeated repository benchmark campaign",
        "",
        "This report is a sanitized, deterministic public view of the retained 18-cell live-model campaign. It was rebuilt read-only after incomplete-cell usage bounds were added; the original campaign and its original matrix were not rewritten.",
        "",
        "## Headline results",
        "",
        "| Fact | Result |",
        "| --- | ---: |",
        f"| Recorded cells | {matrix['completion']['recorded_cell_count']}/{matrix['planned']['cell_count']} |",
        f"| Completed cells | {matrix['completion']['numerator']}/{matrix['completion']['denominator']} |",
        f"| Automated contract passes | {matrix['automated_cell_pass_rate']['numerator']}/{matrix['automated_cell_pass_rate']['denominator']} |",
        f"| Incomplete cells | {sum(matrix['incomplete_distribution'].values())} |",
        f"| Known attempted requests | {usage['known_attempted_requests']} |",
        f"| Attempted-request bound | {bounds['minimum']}-{bounds['maximum']} |",
        f"| Completed responses | {usage['completed_responses']} |",
        f"| Provider usage reports | {usage['usage_reports']} |",
        f"| Reported tokens | {usage['reported_tokens']} |",
        "",
        "The campaign status remains `incomplete`. Incomplete cells stay in every frozen denominator and are not retried or reclassified for a better score.",
        "",
        "## Evidence identity",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| Campaign | [`{matrix['campaign_id']}`](repeated-benchmark.json) |",
        f"| Campaign contract SHA-256 | `{matrix['campaign_sha256']}` |",
        f"| Run manifest SHA-256 | `{matrix['run_manifest_sha256']}` |",
        f"| Preflight SHA-256 | `{matrix['preflight_sha256']}` |",
        f"| Benchmark | `{matrix['benchmark_id']}` |",
        f"| Benchmark contract SHA-256 | `{matrix['benchmark_sha256']}` |",
        f"| Harness revision | `{matrix['harness_revision']}` |",
        f"| Provider / model | `{matrix['model']['provider']}` / `{matrix['model']['name']}` |",
        f"| Retained original matrix SHA-256 | `{original_matrix_sha256}` |",
        f"| Published rebuilt matrix SHA-256 | `{matrix_sha256}` |",
        "",
        "The retained original matrix predates bounded unknown-usage reporting and remains hash-identical. The separately published rebuilt matrix is [`repeated-benchmark-results.json`](repeated-benchmark-results.json).",
        "",
        "## Frozen-denominator rates",
        "",
        "| Metric | Result |",
        "| --- | ---: |",
        f"| Completion | {format_rate(matrix['completion'])} |",
        f"| Automated cell pass | {format_rate(matrix['automated_cell_pass_rate'])} |",
        f"| First-repetition pass | {format_rate(matrix['first_repetition_pass_rate'])} |",
        f"| Tasks passing all repetitions | {format_rate(matrix['task_all_repetitions_pass_rate'])} |",
        f"| Tasks passing at least once | {format_rate(matrix['task_at_least_one_pass_rate'])} |",
        "",
        "## Per-task results",
        "",
        "| Task | Completed | Automated passes | Repetition outcomes |",
        "| --- | ---: | ---: | --- |",
    ]
    for task in matrix["tasks"]:
        outcomes = ", ".join(f"r{index} `{outcome}`" for index, outcome in enumerate(task["outcomes"], start=1))
        lines.append(
            f"| `{task['task_id']}` | {task['completed_repetitions']}/{task['planned_repetitions']} | "
            f"{task['automated_passes']}/{task['planned_repetitions']} | {outcomes} |"
        )
    lines.extend(
        [
            "",
            "## Cell evidence index",
            "",
            "| Cell | Task / repetition | Status | Classification | Evidence SHA-256 |",
            "| ---: | --- | --- | --- | --- |",
        ]
    )
    for cell in matrix["cells"]:
        evidence_sha = cell["result_sha256"] if cell["status"] == "completed" else cell["failure_sha256"]
        lines.append(
            f"| {cell['ordinal']} | `{cell['task_id']}` / r{cell['repetition']} | `{cell['status']}` | "
            f"`{cell['classification']}` | `{evidence_sha}` |"
        )
    lines.extend(
        [
            "",
            "## Incomplete cells and usage bounds",
            "",
            f"All {usage['incomplete_cells_with_unknown_usage']} usage-unknown cells are classified as `runner_failed_without_result`. Their retained legacy failure artifacts do not contain trustworthy request counters. The report therefore keeps {usage['known_attempted_requests']} observed attempts as the minimum and adds {usage['maximum_unobserved_attempts']} frozen possible attempts as the upper-bound allowance, producing `{bounds['minimum']}-{bounds['maximum']}` rather than treating unknown usage as zero.",
            "",
            "## Public safety boundary",
            "",
            "The public matrix and this report retain only campaign identity, hashes, bounded counters, task/cell status, classifications, aggregate scores and explicit interpretation boundaries. They exclude:",
            "",
            "- API credentials and environment-file contents;",
            "- prompts, model responses and candidate source;",
            "- raw or sanitized subprocess stdout/stderr;",
            "- local checkout, interpreter and user-profile paths;",
            "- raw failure messages.",
            "",
            "The source cell artifacts remain retained separately and hash-bound by the run manifest. This public view is an integrity-linked campaign report, not a self-contained redistribution of every model and subprocess artifact.",
            "",
            "## Interpretation boundaries",
            "",
            "- The campaign measures one frozen model, harness revision, six-task set, execution order and request cap.",
            "- `validation_passed` is an automated task-contract result, not manual acceptance, upstream readiness or production equivalence.",
            "- The 9/18 automated result is not a general coding-agent success-rate estimate.",
            "- Incomplete cells remain visible and contribute to the planned denominator.",
            "- Reported tokens come from retained provider metadata; no token-derived cost is claimed because this campaign lacks a complete frozen cost basis.",
            "- The candidate-informed adversarial follow-up is excluded from this independent six-task campaign.",
            "",
        ]
    )
    return "\n".join(lines)


def build(args: argparse.Namespace) -> dict[str, Any]:
    matrix_path = args.matrix.resolve(strict=True)
    matrix = read_object(matrix_path)
    summary = validate_matrix(matrix)
    original_matrix_sha256 = require_sha256(
        args.retained_original_matrix_sha256,
        "retained original matrix SHA-256",
    )
    matrix_sha256 = sha256_file(matrix_path)
    markdown = render_markdown(matrix, matrix_sha256, original_matrix_sha256)
    write_text_atomic(args.markdown_output, markdown)
    return {
        "version": PUBLIC_REPORT_VERSION,
        "status": "built",
        "matrix_sha256": matrix_sha256,
        "retained_original_matrix_sha256": original_matrix_sha256,
        **summary,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a sanitized public report from a repeated benchmark matrix.")
    parser.add_argument("--matrix", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    parser.add_argument("--retained-original-matrix-sha256", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = build(args)
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
