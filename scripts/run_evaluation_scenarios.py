from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.agents import LLMClient  # noqa: E402
from app.autoresearch import (  # noqa: E402
    CandidateProposal,
    CommandResult,
    ModelUsage,
    TrialLedger,
    ValidationReport,
    freeze_research_spec,
    parse_metric,
    run_autoresearch,
    validate_autoresearch,
)


SCENARIO_ROOT = ROOT / "examples" / "autoresearch" / "evaluation-suite" / "scenarios"
SHARED_EVALUATOR = SCENARIO_ROOT / "_shared" / "evaluator.py"
RESULT_VERSION = "repropilot.evaluation-result/v1"
SUITE_VERSION = "repropilot.evaluation-suite/v1"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
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


def git_metadata() -> tuple[str, bool]:
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip())
    return revision, dirty


def extract_json_object(value: str) -> dict[str, Any]:
    cleaned = value.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        cleaned = "\n".join(lines[1:-1] if len(lines) > 2 and lines[-1].strip() == "```" else lines[1:])
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end < start:
        raise ValueError("candidate model did not return a JSON object")
    payload = json.loads(cleaned[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("candidate model response must be a JSON object")
    return payload


class LocalSubprocessEvaluator:
    def __init__(self, workspace: Path, timeout_seconds: float) -> None:
        self.workspace = workspace
        self.timeout_seconds = timeout_seconds

    async def __call__(self, command: list[str]) -> CommandResult:
        executable = sys.executable if Path(command[0]).name.lower() in {"python", "python3"} else command[0]
        resolved = [executable, *command[1:]]
        started = time.monotonic()
        process = await asyncio.create_subprocess_exec(
            *resolved,
            cwd=self.workspace,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "PYTHONHASHSEED": "0"},
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=self.timeout_seconds)
            exit_code = int(process.returncode or 0)
        except TimeoutError:
            process.kill()
            stdout, stderr = await process.communicate()
            exit_code = 124
            stderr += f"command timed out after {self.timeout_seconds:.2f}s".encode()
        return CommandResult(
            command=command,
            exit_code=exit_code,
            stdout=stdout.decode("utf-8", errors="replace"),
            stderr=stderr.decode("utf-8", errors="replace"),
            duration_ms=int((time.monotonic() - started) * 1000),
        )


def scenario_files(path: Path) -> tuple[dict[str, Any], Path]:
    definition = json.loads(path.joinpath("scenario.json").read_text(encoding="utf-8"))
    if definition.get("schema_version") != "repropilot.evaluation-scenario/v1":
        raise ValueError(f"unsupported scenario schema: {path}")
    candidate = path / "candidate.py"
    if not candidate.is_file():
        raise ValueError(f"candidate fixture is missing: {candidate}")
    return definition, candidate


def materialize_scenario(path: Path, workspace: Path, revision: str) -> tuple[dict[str, Any], Any, dict[str, str]]:
    definition, candidate = scenario_files(path)
    shutil.copyfile(candidate, workspace / "candidate.py")
    shutil.copyfile(SHARED_EVALUATOR, workspace / "evaluator.py")
    shutil.copyfile(SHARED_EVALUATOR, workspace / "holdout_evaluator.py")

    function_name = str(definition["function"])
    public_contract = {"function": function_name, **definition["public_evaluation"]}
    hidden_contract = {"function": function_name, **definition["hidden_evaluation"]}
    write_json(workspace / "public_cases.json", public_contract)
    write_json(workspace / "hidden_cases.json", hidden_contract)

    payload = {
        "version": "autoresearch.spec/v1",
        "name": definition["id"],
        "objective": definition["objective"],
        "repository_revision": revision,
        "editable_files": ["candidate.py"],
        "protected_files": ["evaluator.py", "holdout_evaluator.py", "public_cases.json", "hidden_cases.json"],
        "eval_command": ["python", "evaluator.py"],
        "holdout_command": ["python", "holdout_evaluator.py"],
        "guard_commands": [["python", "-m", "py_compile", "candidate.py"]],
        "metric_key": "metrics.accuracy",
        "direction": "maximize",
        "min_delta": 0.01,
        "holdout_min_delta": 0.01,
        "target_score": 1.0,
        "max_trials": 1,
        "max_wall_seconds": 60,
        "search_runs": 1,
        "search_aggregation": "worst",
        "validation_runs": 3,
        "dependencies": [],
    }
    payload.update(definition.get("spec", {}))
    write_json(workspace / "autoresearch.json", payload)
    spec = freeze_research_spec(
        workspace,
        payload,
        {"requested_revision": revision, "repository_commit": revision},
        source_path="autoresearch.json",
    )
    input_hashes = {
        "scenario.json": sha256_file(path / "scenario.json"),
        "candidate.py": sha256_file(candidate),
        "shared_evaluator.py": sha256_file(SHARED_EVALUATOR),
    }
    return definition, spec, input_hashes


def scripted_proposer(definition: dict[str, Any]):
    proposals = iter(definition.get("scripted_proposals", []))

    async def propose(_context: dict[str, Any]) -> CandidateProposal:
        try:
            return CandidateProposal.model_validate(next(proposals))
        except StopIteration:
            return CandidateProposal(status="stop", reason="scripted proposal sequence exhausted")

    return propose


def live_proposer(client: LLMClient, usage: ModelUsage, request_cap: int):
    async def propose(context: dict[str, Any]) -> CandidateProposal:
        if usage.request_count >= request_cap:
            return CandidateProposal(status="stop", reason=f"live request cap reached ({request_cap})")
        completion = await client.complete_with_usage(
            "You are a bounded AutoResearch candidate proposer. Return strict JSON only with status, diagnosis, hypothesis, reason and patches. Patch only listed editable files. Never modify evaluators, tests, metrics, commands, dependencies or budgets; never add network access, subprocesses, fake metrics or fake predictions.",
            json.dumps(context, ensure_ascii=False)[:120000],
        )
        usage.record(completion.usage)
        return CandidateProposal.model_validate(extract_json_object(completion.content))

    return propose


def classify_outcome(ledger: TrialLedger | None, report: ValidationReport | None, error: str) -> str:
    if error:
        return "integrity_abort" if "protected evaluator or data changed" in error or "non-editable workspace changed" in error else "run_failed"
    if ledger is None:
        return "run_failed"
    if ledger.accepted_trials:
        return "validation_passed" if report is not None and report.status == "passed" else "hidden_validation_failed"
    reasons = " ".join(trial.reason for trial in ledger.trials).lower()
    if "timed out" in reasons:
        return "candidate_rejected_timeout"
    if "guard command failed" in reasons:
        return "candidate_rejected_guard"
    if "not authorized" in reasons:
        return "candidate_rejected_contract"
    return "candidate_rejected"


def cost_record(usage: ModelUsage, args: argparse.Namespace) -> dict[str, Any]:
    if usage.request_count == 0:
        return {"status": "exact_zero", "currency": args.currency, "amount": 0.0, "basis": "no provider request was made"}
    if args.input_cost_per_million is None or args.output_cost_per_million is None:
        return {
            "status": "not_calculated",
            "currency": args.currency,
            "amount": None,
            "basis": "provider billing rates were not supplied; token counts are retained",
        }
    if usage.reported_request_count != usage.request_count:
        return {
            "status": "not_calculated",
            "currency": args.currency,
            "amount": None,
            "basis": "one or more provider responses omitted token usage",
        }
    amount = (
        usage.prompt_tokens * args.input_cost_per_million
        + usage.completion_tokens * args.output_cost_per_million
    ) / 1_000_000
    return {
        "status": "calculated_from_supplied_rates",
        "currency": args.currency,
        "amount": round(amount, 8),
        "input_cost_per_million": args.input_cost_per_million,
        "output_cost_per_million": args.output_cost_per_million,
        "basis": "provider-reported tokens multiplied by caller-supplied rates",
    }


async def run_scenario(path: Path, run_root: Path, revision: str, source_dirty: bool, args: argparse.Namespace) -> dict[str, Any]:
    scenario_id = path.name
    scenario_output = run_root / scenario_id
    scenario_output.mkdir(parents=True, exist_ok=False)
    usage = ModelUsage()
    ledger: TrialLedger | None = None
    report: ValidationReport | None = None
    run_error = ""
    baseline_preflight: dict[str, Any] = {}

    with tempfile.TemporaryDirectory(prefix=f"repropilot-{scenario_id}-") as temporary:
        workspace = Path(temporary)
        definition, spec, input_hashes = materialize_scenario(path, workspace, revision)
        initial_candidate = workspace.joinpath("candidate.py").read_text(encoding="utf-8")
        live = args.mode == "live" and bool(definition.get("allow_live_model"))
        if live:
            client = LLMClient(offline_demo_mode=False)
            if not client.configured:
                raise RuntimeError("live mode requires OPENAI_API_KEY or --env-file with a configured key")
            proposer = live_proposer(client, usage, args.max_live_requests_per_scenario)
            proposer_mode = "live_model"
        else:
            proposer = scripted_proposer(definition)
            proposer_mode = "scripted_fault_injection"
        evaluator = LocalSubprocessEvaluator(workspace, float(definition.get("command_timeout_seconds", 3.0)))

        public_baseline = await evaluator(spec.eval_command)
        hidden_baseline = await evaluator(spec.holdout_command)
        if public_baseline.exit_code != 0 or hidden_baseline.exit_code != 0:
            raise RuntimeError("scenario baseline preflight failed")
        baseline_preflight = {
            "public_score": parse_metric(public_baseline.stdout, spec.metric_key),
            "hidden_score": parse_metric(hidden_baseline.stdout, spec.metric_key),
            "command_results": [public_baseline.model_dump(mode="json"), hidden_baseline.model_dump(mode="json")],
        }

        try:
            ledger = await run_autoresearch(workspace, spec, evaluator, proposer)
            ledger.model_usage = usage
            report = await validate_autoresearch(workspace, spec, ledger, evaluator)
        except Exception as exc:
            run_error = f"{type(exc).__name__}: {exc}"

        observed = classify_outcome(ledger, report, run_error)
        expected = str(definition["expected_outcome"])
        final_candidate = workspace.joinpath("candidate.py").read_text(encoding="utf-8")
        final_hashes = {
            "candidate.py": sha256_file(workspace / "candidate.py"),
            "evaluator.py": sha256_file(workspace / "evaluator.py"),
            "holdout_evaluator.py": sha256_file(workspace / "holdout_evaluator.py"),
        }

        write_json(scenario_output / "scenario-input.json", definition)
        (scenario_output / "initial-candidate.py").write_text(initial_candidate, encoding="utf-8", newline="\n")
        (scenario_output / "final-candidate.py").write_text(final_candidate, encoding="utf-8", newline="\n")
        write_json(scenario_output / "frozen-spec.json", spec.model_dump(mode="json"))
        write_json(scenario_output / "baseline-preflight.json", baseline_preflight)
        if ledger is not None:
            write_json(scenario_output / "trial-ledger.json", ledger.model_dump(mode="json"))
        if report is not None:
            write_json(scenario_output / "validation-report.json", report.model_dump(mode="json"))

        result = {
            "version": RESULT_VERSION,
            "recorded_at": utc_now(),
            "scenario_id": scenario_id,
            "title": definition["title"],
            "description": definition["description"],
            "repository_revision": revision,
            "source_tree_dirty": source_dirty,
            "fixture_sha256": sha256_bytes(json.dumps(input_hashes, sort_keys=True).encode()),
            "input_hashes": input_hashes,
            "expected_outcome": expected,
            "observed_outcome": observed,
            "expectation_met": observed == expected,
            "execution": {
                "engine": "local_subprocess",
                "command_timeout_seconds": evaluator.timeout_seconds,
                "proposer_mode": proposer_mode,
                "live_request_cap": args.max_live_requests_per_scenario if live else 0,
            },
            "commands": {
                "guard": spec.guard_commands,
                "public_evaluation": spec.eval_command,
                "hidden_evaluation": spec.holdout_command,
                "search_runs": spec.search_runs,
                "validation_runs": spec.validation_runs,
            },
            "baseline": {
                "public_score": ledger.baseline_score if ledger else baseline_preflight["public_score"],
                "hidden_score": ledger.holdout_baseline_score if ledger else baseline_preflight["hidden_score"],
                "preflight_artifact": f"{scenario_id}/baseline-preflight.json",
            },
            "search": {
                "best_score": ledger.best_score if ledger else None,
                "completed_trials": ledger.completed_trials if ledger else 0,
                "accepted_trials": ledger.accepted_trials if ledger else 0,
                "stop_reason": ledger.stop_reason if ledger else "run_aborted",
                "decisions": [
                    {"number": trial.number, "status": trial.status, "decision": trial.decision, "metric": trial.metric, "reason": trial.reason}
                    for trial in ledger.trials
                ] if ledger else [],
            },
            "model": usage.model_dump(mode="json") | {"mode": proposer_mode},
            "cost": cost_record(usage, args),
            "validation": report.model_dump(mode="json") if report else None,
            "failure": {"error": run_error} if run_error else None,
            "final_hashes": final_hashes,
            "boundaries": definition.get("boundaries", []),
            "artifacts": {
                "scenario_input": f"{scenario_id}/scenario-input.json",
                "baseline_preflight": f"{scenario_id}/baseline-preflight.json",
                "frozen_spec": f"{scenario_id}/frozen-spec.json",
                "trial_ledger": f"{scenario_id}/trial-ledger.json" if ledger else None,
                "validation_report": f"{scenario_id}/validation-report.json" if report else None,
                "initial_candidate": f"{scenario_id}/initial-candidate.py",
                "final_candidate": f"{scenario_id}/final-candidate.py",
            },
        }
        write_json(scenario_output / "result.json", result)
        return result


def markdown_summary(summary: dict[str, Any]) -> str:
    lines = [
        "# ReproPilot evaluation scenario run",
        "",
        f"- Recorded at: `{summary['recorded_at']}`",
        f"- Repository revision: `{summary['repository_revision']}`",
        f"- Source tree dirty before run: `{str(summary['source_tree_dirty']).lower()}`",
        f"- Requested mode: `{summary['requested_mode']}`",
        f"- Result: `{'passed' if summary['passed'] else 'failed'}`",
        "",
        "| Scenario | Proposer | Baseline | Best | Observed outcome | Expected | Requests | Tokens | Cost |",
        "| --- | --- | ---: | ---: | --- | --- | ---: | ---: | --- |",
    ]
    for result in summary["scenarios"]:
        cost = result["cost"]
        cost_text = f"{cost['amount']} {cost['currency']}" if cost["amount"] is not None else cost["status"]
        lines.append(
            f"| `{result['scenario_id']}` | {result['execution']['proposer_mode']} | "
            f"{result['baseline']['public_score']} | {result['search']['best_score']} | "
            f"{result['observed_outcome']} | {result['expected_outcome']} | "
            f"{result['model']['request_count']} | {result['model']['total_tokens']} | {cost_text} |"
        )
    lines.extend([
        "",
        "Scripted fault-injection scenarios validate deterministic governance and failure handling; they are not model-quality claims. Live-model scenarios record provider-reported token usage and calculate monetary cost only when explicit rates are supplied.",
        "",
    ])
    return "\n".join(lines)


async def run_suite(args: argparse.Namespace) -> dict[str, Any]:
    if args.env_file:
        load_env_file(args.env_file.resolve())
    revision, dirty = git_metadata()
    if args.repository_revision:
        revision = args.repository_revision.lower()
    if args.mode == "live" and dirty and not args.allow_dirty:
        raise RuntimeError("live evidence requires a clean source tree; commit fixtures first or pass --allow-dirty for a non-release run")

    scenario_paths = sorted(path.parent for path in SCENARIO_ROOT.glob("*/scenario.json"))
    if args.scenario:
        selected = set(args.scenario)
        scenario_paths = [path for path in scenario_paths if path.name in selected]
        missing = selected - {path.name for path in scenario_paths}
        if missing:
            raise ValueError(f"unknown scenarios: {sorted(missing)}")
    if not scenario_paths:
        raise ValueError("no evaluation scenarios selected")

    run_root = args.output.resolve()
    run_root.mkdir(parents=True, exist_ok=False)
    results = [await run_scenario(path, run_root, revision, dirty, args) for path in scenario_paths]
    summary = {
        "version": SUITE_VERSION,
        "recorded_at": utc_now(),
        "repository_revision": revision,
        "source_tree_dirty": dirty,
        "requested_mode": args.mode,
        "scenario_count": len(results),
        "passed": all(result["expectation_met"] for result in results),
        "scenarios": results,
    }
    write_json(run_root / "suite-summary.json", summary)
    (run_root / "README.md").write_text(markdown_summary(summary), encoding="utf-8", newline="\n")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run fixed AutoResearch evaluation scenarios and retain auditable artifacts.")
    parser.add_argument("--mode", choices=("scripted", "live"), default="scripted")
    parser.add_argument("--scenario", action="append", help="Scenario id to run; repeat to select multiple.")
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "evaluation-results" / datetime.now().strftime("%Y%m%d-%H%M%S"))
    parser.add_argument("--env-file", type=Path, default=None, help="Optional env file loaded without printing secrets.")
    parser.add_argument("--repository-revision", help="Override the recorded revision; defaults to git HEAD.")
    parser.add_argument("--max-live-requests-per-scenario", type=int, default=2)
    parser.add_argument("--input-cost-per-million", type=float)
    parser.add_argument("--output-cost-per-million", type=float)
    parser.add_argument("--currency", default="USD")
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument("--fail-on-mismatch", action=argparse.BooleanOptionalAction, default=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.max_live_requests_per_scenario < 1:
        raise SystemExit("--max-live-requests-per-scenario must be positive")
    rates = (args.input_cost_per_million, args.output_cost_per_million)
    if any(rate is not None and rate < 0 for rate in rates):
        raise SystemExit("cost rates must be non-negative")
    summary = asyncio.run(run_suite(args))
    print(f"Evaluation suite: {summary['scenario_count']} scenarios, passed={summary['passed']}")
    print(f"Artifacts: {args.output.resolve()}")
    if args.fail_on_mismatch and not summary["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
