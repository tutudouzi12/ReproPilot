from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from statistics import fmean
from typing import Any


BENCHMARK_VERSION = "repropilot.repository-benchmark/v1"
TASK_VERSION = "repropilot.repository-evaluation-task/v1"
SELECTION_VERSION = "repropilot.repository-benchmark-run-selection/v1"
RESULT_VERSION = "repropilot.repository-evaluation-result/v1"
REVIEW_VERSION = "repropilot.repository-evaluation-review/v1"
REPORT_VERSION = "repropilot.repository-benchmark-report/v1"
FOLLOWUP_ELIGIBILITY = "followup_only_not_independent_repository_sample"
ROLES = {"primary", "development_history", "adversarial_followup"}
DECISIONS = {"accept", "accept_with_boundary", "reject"}
ACCEPTED_DECISIONS = {"accept", "accept_with_boundary"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON artifact must contain an object: {path}")
    return value


def resolve_inside(root: Path, relative: str, label: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"{label} must remain inside the benchmark directory: {relative}")
    resolved = (root / candidate).resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{label} escaped the benchmark directory: {relative}") from exc
    return resolved


def require_sha256(actual: str, expected: Any, label: str) -> None:
    normalized = str(expected).lower()
    if len(normalized) != 64 or any(character not in "0123456789abcdef" for character in normalized):
        raise ValueError(f"{label} does not contain a valid SHA-256 value")
    if actual != normalized:
        raise ValueError(f"SHA-256 mismatch for {label}")


def normalize_repository_url(value: str) -> str:
    normalized = value.strip().replace("git@github.com:", "https://github.com/")
    if normalized.endswith(".git"):
        normalized = normalized[:-4]
    return normalized.rstrip("/").lower()


def ratio(numerator: int, denominator: int) -> dict[str, Any]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate": numerator / denominator if denominator else None,
    }


def finite_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label} must be a finite number")
    return float(value)


def optional_finite_number(value: Any, label: str) -> float | None:
    return None if value is None else finite_number(value, label)


def validate_result_artifacts(result_dir: Path, result: dict[str, Any]) -> None:
    hashes = result.get("artifact_sha256")
    if not isinstance(hashes, dict) or not hashes:
        raise ValueError(f"result artifact hashes are missing: {result_dir / 'result.json'}")
    for relative, expected in hashes.items():
        artifact = resolve_inside(result_dir, str(relative), "result artifact")
        require_sha256(sha256_file(artifact), expected, f"result artifact {relative}")


def validate_benchmark(path: Path) -> tuple[dict[str, Any], Path, dict[str, dict[str, Any]]]:
    benchmark_path = path.resolve(strict=True)
    root = benchmark_path.parent
    benchmark = read_object(benchmark_path)
    if benchmark.get("version") != BENCHMARK_VERSION:
        raise ValueError(f"unsupported benchmark version: {benchmark.get('version')!r}")
    raw_tasks = benchmark.get("tasks")
    if not isinstance(raw_tasks, list) or not raw_tasks:
        raise ValueError("benchmark must contain tasks")

    tasks: dict[str, dict[str, Any]] = {}
    for entry in raw_tasks:
        if not isinstance(entry, dict):
            raise ValueError("benchmark task entries must be objects")
        task_id = str(entry.get("id", ""))
        if not task_id or task_id in tasks:
            raise ValueError(f"missing or duplicate benchmark task id: {task_id!r}")
        task_dir = resolve_inside(root, str(entry.get("path", "")), f"task {task_id}")
        task = read_object(task_dir / "task.json")
        if task.get("version") != TASK_VERSION or task.get("id") != task_id:
            raise ValueError(f"task identity mismatch for {task_id}")
        contract_hashes = entry.get("contract_sha256")
        if not isinstance(contract_hashes, dict) or not contract_hashes:
            raise ValueError(f"contract hashes are missing for {task_id}")
        for relative, expected in contract_hashes.items():
            artifact = resolve_inside(task_dir, str(relative), f"contract artifact for {task_id}")
            require_sha256(sha256_file(artifact), expected, f"{task_id}/{relative}")
        tasks[task_id] = {**entry, "task": task, "task_dir": task_dir}
    return benchmark, root, tasks


def load_runs(
    benchmark: dict[str, Any],
    root: Path,
    tasks: dict[str, dict[str, Any]],
    selection_path: Path,
    *,
    strict: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    selection = read_object(selection_path.resolve(strict=True))
    configured_selection = benchmark.get("run_selection")
    if configured_selection:
        expected_selection = resolve_inside(root, str(configured_selection), "configured run selection")
        if expected_selection != selection_path.resolve(strict=True):
            raise ValueError("selected run-selection path does not match benchmark configuration")
    if selection.get("version") != SELECTION_VERSION:
        raise ValueError(f"unsupported run-selection version: {selection.get('version')!r}")
    if selection.get("benchmark_id") != benchmark.get("id"):
        raise ValueError("run selection does not match the benchmark id")
    raw_runs = selection.get("runs")
    if not isinstance(raw_runs, list) or not raw_runs:
        raise ValueError("run selection must contain runs")

    warnings: list[str] = []
    selected_paths: set[str] = set()
    runs: list[dict[str, Any]] = []
    for index, entry in enumerate(raw_runs):
        if not isinstance(entry, dict):
            raise ValueError(f"run selection entry {index} must be an object")
        task_id = str(entry.get("task_id", ""))
        role = str(entry.get("role", ""))
        if task_id not in tasks:
            raise ValueError(f"run selection references unknown task: {task_id}")
        if role not in ROLES:
            raise ValueError(f"unsupported run role for {task_id}: {role!r}")
        task_entry = tasks[task_id]
        is_followup = task_entry.get("aggregate_eligibility") == FOLLOWUP_ELIGIBILITY
        if is_followup != (role == "adversarial_followup"):
            raise ValueError(f"run role does not match aggregate eligibility for {task_id}")

        result_relative = str(entry.get("result", ""))
        if result_relative in selected_paths:
            raise ValueError(f"duplicate selected result path: {result_relative}")
        result_path = resolve_inside(root, result_relative, "selected result")
        try:
            result_path.relative_to(task_entry["task_dir"])
        except ValueError as exc:
            raise ValueError(f"selected result is outside task directory for {task_id}") from exc
        require_sha256(sha256_file(result_path), entry.get("result_sha256"), result_relative)
        result = read_object(result_path)
        if result.get("version") != RESULT_VERSION or result.get("task_id") != task_id:
            raise ValueError(f"result identity mismatch for {result_relative}")
        if result.get("harness", {}).get("source_tree_dirty") is not False:
            raise ValueError(f"selected result did not use a clean harness tree: {result_relative}")
        repository = result.get("repository", {})
        if normalize_repository_url(str(repository.get("url", ""))) != normalize_repository_url(
            str(task_entry.get("repository_url", ""))
        ):
            raise ValueError(f"repository URL mismatch for {result_relative}")
        if str(repository.get("revision", "")).lower() != str(task_entry.get("revision", "")).lower():
            raise ValueError(f"repository revision mismatch for {result_relative}")
        validate_result_artifacts(result_path.parent, result)

        baseline_hash = str(result.get("baseline_artifact_sha256", "")).lower()
        expected_baseline = str(task_entry["contract_sha256"].get("baseline.json", "")).lower()
        alignment = str(entry.get("contract_alignment", "current_contract"))
        aligned = baseline_hash == expected_baseline
        if not aligned and alignment != "historical_pre_portability_contract":
            raise ValueError(f"result baseline does not match current contract: {result_relative}")
        if aligned and alignment != "current_contract":
            raise ValueError(f"historical contract exception is unnecessary for {result_relative}")

        review_relative = entry.get("review")
        review: dict[str, Any] = {}
        if not review_relative:
            message = f"manual review is missing from run selection: {result_relative}"
            if strict:
                raise ValueError(message)
            warnings.append(message)
        else:
            review_path = resolve_inside(root, str(review_relative), "selected review")
            if review_path.parent != result_path.parent:
                raise ValueError(f"review is not colocated with result: {review_relative}")
            require_sha256(sha256_file(review_path), entry.get("review_sha256"), str(review_relative))
            review = read_object(review_path)
            if review.get("version") != REVIEW_VERSION:
                raise ValueError(f"unsupported review version: {review_relative}")

        decision = str(review.get("decision", "unreviewed"))
        classification = str(review.get("classification", "unreviewed"))
        if decision not in DECISIONS:
            message = f"normalized review decision is missing or invalid: {result_relative}"
            if strict:
                raise ValueError(message)
            warnings.append(message)
            decision = "unreviewed"
            classification = "unreviewed"
        if not classification.strip():
            raise ValueError(f"normalized review classification is empty: {result_relative}")

        model = result.get("model", {})
        attempted_requests = int(model.get("attempted_request_count", 0))
        completed_responses = int(model.get("request_count", 0))
        usage_reports = int(model.get("reported_request_count", 0))
        total_tokens = int(model.get("total_tokens", 0))
        if (
            min(attempted_requests, completed_responses, usage_reports, total_tokens) < 0
            or usage_reports > completed_responses
            or completed_responses > attempted_requests
        ):
            raise ValueError(f"invalid model usage counters: {result_relative}")
        if decision in ACCEPTED_DECISIONS and result.get("outcome") != "validation_passed":
            raise ValueError(f"manual acceptance cannot override failed automated validation: {result_relative}")
        cost = result.get("cost", {})
        cost_amount = optional_finite_number(cost.get("amount"), f"cost amount in {result_relative}")
        public_best = optional_finite_number(
            result.get("search", {}).get("best_score"), f"public score in {result_relative}"
        )
        hidden_observed = optional_finite_number(
            result.get("validation", {}).get("observed_score"), f"hidden score in {result_relative}"
        )
        selected_paths.add(result_relative)
        runs.append(
            {
                "task_id": task_id,
                "role": role,
                "run_id": result_path.parent.name,
                "result": result_relative,
                "review": str(review_relative) if review_relative else None,
                "recorded_at": str(result.get("recorded_at", "")),
                "harness_revision": str(result.get("harness", {}).get("revision", "")),
                "repository_url": str(task_entry.get("repository_url", "")),
                "contract_alignment": alignment,
                "outcome": str(result.get("outcome", "")),
                "automated_contract_passed": result.get("outcome") == "validation_passed",
                "manual_decision": decision,
                "manual_accepted": decision in ACCEPTED_DECISIONS,
                "classification": classification,
                "attempted_requests": attempted_requests,
                "completed_responses": completed_responses,
                "usage_reports": usage_reports,
                "reported_tokens": total_tokens,
                "cost_status": str(cost.get("status", "")),
                "cost_amount": cost_amount,
                "cost_currency": str(cost.get("currency", "")),
                "public_baseline": optional_finite_number(
                    result.get("search", {}).get("baseline_score"), f"public baseline in {result_relative}"
                ),
                "public_best": public_best,
                "hidden_baseline": optional_finite_number(
                    result.get("validation", {}).get("baseline_score"), f"hidden baseline in {result_relative}"
                ),
                "hidden_observed": hidden_observed,
                "public_to_hidden_gap": (
                    round(public_best - hidden_observed, 12)
                    if public_best is not None and hidden_observed is not None
                    else None
                ),
            }
        )

    discovered = {
        path.relative_to(root).as_posix()
        for path in root.glob("*/results/*/result.json")
        if path.is_file()
    }
    unselected = sorted(discovered - selected_paths)
    missing = sorted(selected_paths - discovered)
    if missing:
        raise ValueError(f"selected results were not discovered: {', '.join(missing)}")
    if unselected:
        message = f"retained results are missing from run selection: {', '.join(unselected)}"
        if strict:
            raise ValueError(message)
        warnings.append(message)

    independent_tasks = {
        task_id
        for task_id, entry in tasks.items()
        if entry.get("aggregate_eligibility") != FOLLOWUP_ELIGIBILITY
    }
    primary_counts = Counter(run["task_id"] for run in runs if run["role"] == "primary")
    if set(primary_counts) != independent_tasks or any(count != 1 for count in primary_counts.values()):
        raise ValueError("run selection must contain exactly one primary run per independent task")
    return selection, runs, warnings


def aggregate_report(
    benchmark: dict[str, Any],
    benchmark_path: Path,
    selection: dict[str, Any],
    selection_path: Path,
    tasks: dict[str, dict[str, Any]],
    runs: list[dict[str, Any]],
    warnings: list[str],
) -> dict[str, Any]:
    primary = [run for run in runs if run["role"] == "primary"]
    accepted = [run for run in primary if run["manual_accepted"]]
    followups = [run for run in runs if run["role"] == "adversarial_followup"]
    repository_urls = {
        normalize_repository_url(str(entry.get("repository_url", "")))
        for entry in tasks.values()
        if entry.get("aggregate_eligibility") != FOLLOWUP_ELIGIBILITY
    }

    chronological_first: list[dict[str, Any]] = []
    for task_id in sorted(run["task_id"] for run in primary):
        candidates = [run for run in runs if run["task_id"] == task_id and run["role"] != "adversarial_followup"]
        chronological_first.append(min(candidates, key=lambda run: (run["recorded_at"], run["run_id"])))

    known_costs = [run for run in runs if run["cost_amount"] is not None]
    accepted_costs = [run for run in accepted if run["cost_amount"] is not None]
    cost_currencies = {run["cost_currency"] for run in known_costs}
    if len(cost_currencies) > 1:
        raise ValueError("retained token-derived costs use multiple currencies")
    currency = next(iter(cost_currencies), "")
    accepted_cost_complete = len(accepted_costs) == len(accepted)

    primary_gaps = [run["public_to_hidden_gap"] for run in primary if run["public_to_hidden_gap"] is not None]
    classifications = Counter(run["classification"] for run in runs)
    failure_classifications = Counter(
        run["classification"] for run in runs if not run["manual_accepted"]
    )
    outcomes = Counter(run["outcome"] for run in runs)
    report = {
        "version": REPORT_VERSION,
        "recorded_at": selection.get("recorded_at"),
        "benchmark_id": benchmark.get("id"),
        "benchmark_title": benchmark.get("title"),
        "benchmark_sha256": sha256_file(benchmark_path),
        "run_selection_sha256": sha256_file(selection_path),
        "inventory": {
            "task_count": len(tasks),
            "independent_task_count": len(primary),
            "unique_repository_count": len(repository_urls),
            "adversarial_followup_task_count": len(followups),
            "retained_run_count": len(runs),
            "selected_primary_run_count": len(primary),
        },
        "selected_primary_metrics": {
            "automated_contract_pass_rate": ratio(
                sum(run["automated_contract_passed"] for run in primary), len(primary)
            ),
            "manual_acceptance_rate": ratio(sum(run["manual_accepted"] for run in primary), len(primary)),
            "pass_at_1": ratio(
                sum(run["manual_accepted"] and run["attempted_requests"] == 1 for run in primary),
                len(primary),
            ),
            "mean_public_to_hidden_gap": fmean(primary_gaps) if primary_gaps else None,
            "upstream_regression_rate": {
                "status": "not_calculated",
                "reason": "retained result schema does not expose one normalized upstream-regression field",
            },
        },
        "chronological_first_run_metrics": {
            "automated_pass_at_1": ratio(
                sum(
                    run["automated_contract_passed"] and run["attempted_requests"] == 1
                    for run in chronological_first
                ),
                len(chronological_first),
            ),
            "manual_pass_at_1": ratio(
                sum(run["manual_accepted"] and run["attempted_requests"] == 1 for run in chronological_first),
                len(chronological_first),
            ),
            "runs": [run["result"] for run in chronological_first],
        },
        "manual_pass_efficiency": {
            "accepted_run_count": len(accepted),
            "mean_requests_per_pass": fmean(run["attempted_requests"] for run in accepted) if accepted else None,
            "mean_reported_tokens_per_pass": fmean(run["reported_tokens"] for run in accepted) if accepted else None,
            "token_derived_cost_per_pass": {
                "status": "calculated" if accepted and accepted_cost_complete else "not_calculated",
                "currency": currency,
                "amount": round(fmean(run["cost_amount"] for run in accepted_costs), 6)
                if accepted and accepted_cost_complete
                else None,
                "basis": "mean of retained caller-supplied token-derived run costs; not a billing receipt",
            },
        },
        "retained_evidence_totals": {
            "attempted_requests": sum(run["attempted_requests"] for run in runs),
            "completed_responses": sum(run["completed_responses"] for run in runs),
            "usage_reports": sum(run["usage_reports"] for run in runs),
            "reported_tokens": sum(run["reported_tokens"] for run in runs),
            "known_token_derived_cost": {
                "currency": currency,
                "amount": round(sum(run["cost_amount"] for run in known_costs), 6),
                "runs_with_calculated_cost": len(known_costs),
                "runs_without_complete_cost": len(runs) - len(known_costs),
            },
        },
        "automated_outcome_distribution": dict(sorted(outcomes.items())),
        "review_classification_distribution": dict(sorted(classifications.items())),
        "failure_reason_distribution": dict(sorted(failure_classifications.items())),
        "selected_primary_runs": primary,
        "adversarial_followup_runs": followups,
        "retained_runs": runs,
        "warnings": warnings,
        "boundaries": [*selection.get("boundaries", []), *benchmark.get("boundaries", [])],
    }
    return report


def format_rate(value: dict[str, Any]) -> str:
    rate = value.get("rate")
    rendered = "n/a" if rate is None else f"{rate:.4f}"
    return f"{value.get('numerator')}/{value.get('denominator')} ({rendered})"


def format_number(value: Any, digits: int = 6) -> str:
    if value is None:
        return "not calculated"
    if isinstance(value, float):
        return f"{value:.{digits}f}".rstrip("0").rstrip(".")
    return str(value)


def render_markdown(report: dict[str, Any]) -> str:
    inventory = report["inventory"]
    metrics = report["selected_primary_metrics"]
    chronological = report["chronological_first_run_metrics"]
    efficiency = report["manual_pass_efficiency"]
    cost = efficiency["token_derived_cost_per_pass"]
    lines = [
        f"# {report['benchmark_title']} results",
        "",
        f"- Evidence snapshot: `{report['recorded_at']}`",
        f"- Benchmark: `{report['benchmark_id']}`",
        f"- Tasks / independent tasks / unique repositories: `{inventory['task_count']}` / "
        f"`{inventory['independent_task_count']}` / `{inventory['unique_repository_count']}`",
        f"- Retained runs: `{inventory['retained_run_count']}`",
        "",
        "## Selected primary metrics",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Automated contract pass rate | {format_rate(metrics['automated_contract_pass_rate'])} |",
        f"| Manual acceptance rate | {format_rate(metrics['manual_acceptance_rate'])} |",
        f"| Manual pass@1 | {format_rate(metrics['pass_at_1'])} |",
        f"| Chronological first-run automated pass@1 | {format_rate(chronological['automated_pass_at_1'])} |",
        f"| Chronological first-run manual pass@1 | {format_rate(chronological['manual_pass_at_1'])} |",
        f"| Mean public-to-hidden gap | {format_number(metrics['mean_public_to_hidden_gap'])} |",
        "",
        "> Selected primary runs are post-development release-evidence selections. Chronological first-run metrics are shown separately so earlier failures are not hidden.",
        "",
        "## Selected primary runs",
        "",
        "| Task | Run | Automated | Manual review | Public -> hidden | Attempts | Tokens | Cost |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for run in report["selected_primary_runs"]:
        run_link = str(Path(run["result"]).parent).replace("\\", "/") + "/"
        score = f"{format_number(run['public_best'])} -> {format_number(run['hidden_observed'])}"
        amount = "not calculated"
        if run["cost_amount"] is not None:
            amount = f"{format_number(run['cost_amount'])} {run['cost_currency']}"
        lines.append(
            f"| `{run['task_id']}` | [`{run['run_id']}`]({run_link}) | `{run['outcome']}` | "
            f"`{run['manual_decision']}` | {score} | {run['attempted_requests']} | "
            f"{run['reported_tokens']} | {amount} |"
        )

    lines.extend(
        [
            "",
            "## Manually accepted pass efficiency",
            "",
            f"- Accepted primary runs: `{efficiency['accepted_run_count']}`",
            f"- Mean requests per pass: `{format_number(efficiency['mean_requests_per_pass'])}`",
            f"- Mean reported tokens per pass: `{format_number(efficiency['mean_reported_tokens_per_pass'])}`",
            f"- Mean token-derived cost per pass: `{format_number(cost['amount'])} {cost['currency']}`",
            "",
            "## Adversarial follow-up",
            "",
        ]
    )
    if not report["adversarial_followup_runs"]:
        lines.append("No candidate-informed follow-up run is selected.")
    else:
        for run in report["adversarial_followup_runs"]:
            lines.append(
                f"- `{run['task_id']}/{run['run_id']}`: `{run['outcome']}`, "
                f"manual `{run['manual_decision']}`, hidden `{format_number(run['hidden_observed'])}`."
            )

    lines.extend(
        [
            "",
            "## Retained evidence distribution",
            "",
            "| Review classification | Runs |",
            "| --- | ---: |",
        ]
    )
    for classification, count in report["review_classification_distribution"].items():
        lines.append(f"| `{classification}` | {count} |")

    totals = report["retained_evidence_totals"]
    known_cost = totals["known_token_derived_cost"]
    lines.extend(
        [
            "",
            "Retained attempts / completed responses / usage reports / reported tokens: "
            f"`{totals['attempted_requests']}` / `{totals['completed_responses']}` / "
            f"`{totals['usage_reports']}` / `{totals['reported_tokens']}`.",
            "",
            f"Known token-derived cost: `{format_number(known_cost['amount'])} {known_cost['currency']}` "
            f"across `{known_cost['runs_with_calculated_cost']}` runs; "
            f"`{known_cost['runs_without_complete_cost']}` runs lack complete cost data.",
            "",
            "## Reporting boundaries",
            "",
        ]
    )
    for boundary in report["boundaries"]:
        lines.append(f"- {boundary}")
    if report["warnings"]:
        lines.extend(["", "## Validation warnings", ""])
        lines.extend(f"- {warning}" for warning in report["warnings"])
    lines.append("")
    return "\n".join(lines)


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def build(args: argparse.Namespace) -> dict[str, Any]:
    benchmark, root, tasks = validate_benchmark(args.benchmark)
    selection_path = args.selection.resolve(strict=True)
    selection, runs, warnings = load_runs(
        benchmark,
        root,
        tasks,
        selection_path,
        strict=args.strict,
    )
    report = aggregate_report(
        benchmark,
        args.benchmark.resolve(strict=True),
        selection,
        selection_path,
        tasks,
        runs,
        warnings,
    )
    if args.json_output:
        write_json(args.json_output.resolve(), report)
    if args.markdown_output:
        output = args.markdown_output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(render_markdown(report), encoding="utf-8", newline="\n")
    print(
        "Repository benchmark report: "
        f"primary={report['inventory']['selected_primary_run_count']} "
        f"manual_pass={report['selected_primary_metrics']['manual_acceptance_rate']['numerator']} "
        f"retained={report['inventory']['retained_run_count']}"
    )
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an audited aggregate report from retained repository runs.")
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    parser.add_argument("--strict", action="store_true", help="Reject missing reviews and unselected retained runs.")
    return parser.parse_args()


if __name__ == "__main__":
    build(parse_args())
