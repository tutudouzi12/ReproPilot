from __future__ import annotations

import argparse
import asyncio
import difflib
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
from urllib.parse import urlparse


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


TASK_VERSION = "repropilot.repository-evaluation-task/v1"
RESULT_VERSION = "repropilot.repository-evaluation-result/v1"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def sanitize_workspace_paths(value: Any, workspace: Path) -> Any:
    if isinstance(value, dict):
        return {key: sanitize_workspace_paths(item, workspace) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize_workspace_paths(item, workspace) for item in value]
    if isinstance(value, str):
        windows_path = str(workspace)
        portable_path = workspace.as_posix()
        return value.replace(windows_path, "{workspace}").replace(portable_path, "{workspace}")
    return value


def editable_sources(workspace: Path, relative_paths: list[str]) -> dict[str, str]:
    root = workspace.resolve(strict=True)
    sources: dict[str, str] = {}
    for relative in relative_paths:
        candidate = (root / relative).resolve(strict=True)
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"editable file escaped workspace: {relative}") from exc
        if not candidate.is_file():
            raise ValueError(f"editable path is not a file: {relative}")
        sources[Path(relative).as_posix()] = candidate.read_text(encoding="utf-8")
    return sources


def candidate_patch(initial: dict[str, str], final: dict[str, str]) -> str:
    if initial.keys() != final.keys():
        raise ValueError("initial and final editable file sets differ")
    chunks: list[str] = []
    for relative in sorted(initial):
        chunks.extend(
            difflib.unified_diff(
                initial[relative].splitlines(keepends=True),
                final[relative].splitlines(keepends=True),
                fromfile=f"a/{relative}",
                tofile=f"b/{relative}",
            )
        )
    return "".join(chunks)


def write_editable_sources(output: Path, directory: str, sources: dict[str, str]) -> None:
    root = (output / directory).resolve()
    root.mkdir(parents=True, exist_ok=True)
    for relative, source in sources.items():
        destination = (root / relative).resolve()
        try:
            destination.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"editable artifact escaped output directory: {relative}") from exc
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(source, encoding="utf-8", newline="\n")


def load_env_file(path: Path | None) -> None:
    if path is None:
        return
    source = path.resolve(strict=True)
    for raw_line in source.read_text(encoding="utf-8-sig").splitlines():
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


def git(path: Path, *arguments: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(path), *arguments],
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    ).strip()


def git_bytes(path: Path, *arguments: str) -> bytes:
    return subprocess.check_output(
        ["git", "-C", str(path), *arguments],
        timeout=30,
    )


def normalize_repository_url(value: str) -> str:
    normalized = value.strip().replace("git@github.com:", "https://github.com/")
    if normalized.endswith(".git"):
        normalized = normalized[:-4]
    return normalized.rstrip("/").lower()


def validate_target(task_dir: Path, checkout: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    task = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
    baseline = json.loads((task_dir / "baseline.json").read_text(encoding="utf-8"))
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
    if git(checkout, "status", "--porcelain"):
        raise ValueError("repository evaluation requires a clean target checkout")
    for relative, expected_hash in repository["git_blob_sha256"].items():
        relative_path = Path(relative)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ValueError(f"invalid frozen repository path: {relative}")
        actual_hash = sha256_bytes(git_bytes(checkout, "show", f"{expected_revision}:{relative}"))
        if actual_hash != str(expected_hash).lower():
            raise ValueError(f"Git blob hash mismatch for {relative}")
        expected_oid = git(checkout, "rev-parse", f"{expected_revision}:{relative}")
        working_oid = git(checkout, "hash-object", f"--path={relative}", relative)
        if working_oid != expected_oid:
            raise ValueError(f"working tree content does not match the frozen Git blob for {relative}")
    retained = baseline.get("baseline", {})
    expected = task["expected_baseline"]
    if float(retained.get("public_score")) != float(expected["public_score"]):
        raise ValueError("retained public baseline does not match task.json")
    if float(retained.get("hidden_score")) != float(expected["hidden_score"]):
        raise ValueError("retained hidden baseline does not match task.json")
    if baseline.get("repository", {}).get("actual_revision") != expected_revision:
        raise ValueError("retained baseline repository revision does not match task.json")
    return task, baseline


def safe_evaluator_environment(workspace: Path | None = None) -> dict[str, str]:
    allowed = {
        "COMSPEC",
        "NUMBER_OF_PROCESSORS",
        "OS",
        "PATH",
        "PATHEXT",
        "PROCESSOR_ARCHITECTURE",
        "SYSTEMDRIVE",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "WINDIR",
    }
    environment = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    environment.update({"PYTHONHASHSEED": "0", "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
    if workspace is not None and (workspace / "src").is_dir():
        environment["PYTHONPATH"] = str((workspace / "src").resolve())
    return environment


class LocalRepositoryEvaluator:
    def __init__(self, workspace: Path, python: Path, timeout_seconds: float) -> None:
        self.workspace = workspace
        self.python = python
        self.timeout_seconds = timeout_seconds
        self.environment = safe_evaluator_environment(workspace)

    async def __call__(self, command: list[str]) -> CommandResult:
        executable = str(self.python) if Path(command[0]).name.lower() in {"python", "python3"} else command[0]
        resolved = [executable, *command[1:]]
        started = time.monotonic()
        process = await asyncio.create_subprocess_exec(
            *resolved,
            cwd=self.workspace,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self.environment,
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


def live_proposer(
    client: LLMClient,
    usage: ModelUsage,
    request_cap: int,
    responses: list[dict[str, Any]],
):
    async def propose(context: dict[str, Any]) -> CandidateProposal:
        if len(responses) >= request_cap:
            return CandidateProposal(status="stop", reason=f"live request cap reached ({request_cap})")
        context_json = json.dumps(context, ensure_ascii=False)
        sent_context = context_json[:120000]
        record: dict[str, Any] = {
            "request_number": len(responses) + 1,
            "context_sha256": sha256_bytes(sent_context.encode()),
            "context_characters": len(sent_context),
            "usage": None,
            "raw_content": "",
            "parsed_proposal": None,
            "parse_error": "",
            "request_error": "",
        }
        responses.append(record)
        try:
            completion = await client.complete_with_usage(
                "You are a bounded AutoResearch candidate proposer. Return strict JSON only with status, diagnosis, hypothesis, reason and patches. The status value MUST be exactly 'candidate' when proposing patches or 'stop' when no safe patch should be attempted. Each patch must contain path and either complete replacement content or an exact search and replace pair. When editable file context mode is excerpts, you MUST use search/replace so unseen source is preserved; search must match exactly once. Patch only listed editable files. Never modify evaluators, tests, metrics, commands, dependencies or budgets; never add network access, subprocesses, fake metrics or fake predictions. Preserve ordinary upstream behavior while fixing the stated task.",
                sent_context,
            )
        except Exception as exc:
            record["request_error"] = f"{type(exc).__name__}: {exc}"
            raise
        usage.record(completion.usage)
        record["usage"] = completion.usage.model_dump(mode="json")
        record["raw_content"] = completion.content
        try:
            proposal = CandidateProposal.model_validate(extract_json_object(completion.content))
        except Exception as exc:
            record["parse_error"] = f"{type(exc).__name__}: {exc}"
            raise
        record["parsed_proposal"] = proposal.model_dump(mode="json")
        return proposal

    return propose


def materialize_workspace(checkout: Path, task_dir: Path, workspace: Path) -> tuple[dict[str, Any], Any]:
    shutil.copytree(
        checkout,
        workspace,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", "node_modules", "*.pyc"),
    )
    dependency_directory = checkout / "node_modules"
    if dependency_directory.is_dir():
        copy_dependency_directory(dependency_directory, workspace / "node_modules")
    upload_root = workspace / ".repropilot" / "uploads"
    upload_root.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(task_dir / "autoresearch.json", upload_root / "01-autoresearch.json")
    shutil.copyfile(task_dir / "evaluator.py", upload_root / "02-evaluator.py")
    shutil.copyfile(task_dir / "holdout_evaluator.py", upload_root / "03-holdout_evaluator.py")
    payload = json.loads((task_dir / "autoresearch.json").read_text(encoding="utf-8"))
    revision = str(payload["repository_revision"])
    spec = freeze_research_spec(
        workspace,
        payload,
        {"requested_revision": revision, "repository_commit": revision},
        source_path=".repropilot/uploads/01-autoresearch.json",
    )
    return payload, spec


def copy_dependency_directory(source: Path, destination: Path) -> None:
    resolved_source = source.resolve(strict=True)
    if destination.exists():
        raise ValueError(f"dependency destination already exists: {destination}")
    if os.name != "nt":
        shutil.copytree(resolved_source, destination, symlinks=True)
        return
    completed = subprocess.run(
        [
            "robocopy",
            str(resolved_source),
            str(destination),
            "/E",
            "/XJ",
            "/NFL",
            "/NDL",
            "/NJH",
            "/NJS",
            "/NP",
            "/R:1",
            "/W:1",
            "/MT:16",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode >= 8 or not destination.is_dir():
        detail = completed.stderr.strip() or completed.stdout.strip() or "dependency copy failed"
        raise RuntimeError(f"could not copy dependency directory: {detail}")


def cost_record(usage: ModelUsage, attempted_requests: int, args: argparse.Namespace) -> dict[str, Any]:
    if attempted_requests == 0:
        return {"status": "exact_zero", "currency": args.currency, "amount": 0.0, "basis": "no provider request was made"}
    if usage.request_count != attempted_requests:
        return {
            "status": "not_calculated",
            "currency": args.currency,
            "amount": None,
            "basis": "one or more provider request attempts failed before token usage was returned",
        }
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
        "basis": "provider-reported tokens multiplied by caller-supplied public list rates; not a billing receipt",
        "pricing_source": args.pricing_source,
        "pricing_tier": args.pricing_tier,
        "pricing_verified_at": args.pricing_verified_at,
    }


def classify_outcome(ledger: TrialLedger | None, report: ValidationReport | None, error: str) -> str:
    if error:
        return "run_failed"
    if ledger is None:
        return "run_failed"
    if ledger.accepted_trials == 0:
        return "candidate_stopped" if ledger.stop_reason == "candidate_stopped" else "candidate_rejected"
    if report is not None and report.status == "passed":
        return "validation_passed"
    return "hidden_validation_failed"


def render_report(result: dict[str, Any], ledger: TrialLedger | None, task: dict[str, Any]) -> str:
    cost = result["cost"]
    amount = "not calculated" if cost.get("amount") is None else f"{cost['amount']} {cost['currency']}"
    lines = [
        f"# {task['title']} live repository evaluation",
        "",
        f"- Recorded at: `{result['recorded_at']}`",
        f"- Harness revision: `{result['harness']['revision']}`",
        f"- Target revision: `{result['repository']['revision']}`",
        f"- Outcome: `{result['outcome']}`",
        f"- Public baseline -> best: `{result['search']['baseline_score']}` -> `{result['search']['best_score']}`",
        f"- Hidden baseline -> observed: `{result['validation']['baseline_score']}` -> `{result['validation']['observed_score']}`",
        f"- Validation acceptance: `{result['validation']['acceptance_rule']}`, "
        f"target `{result['validation']['acceptance_target_score']}`, "
        f"delta `{result['validation']['acceptance_delta']}`",
        f"- Model: `{result['model']['provider']}/{result['model']['model']}`",
        f"- Request attempts/usage reports/tokens: `{result['model']['attempted_request_count']}` / "
        f"`{result['model']['reported_request_count']}` / `{result['model']['total_tokens']}`",
        f"- Token-derived cost: `{amount}`",
        f"- Editable files: `{', '.join(result['repository']['editable_files'])}`",
        "",
        "## Keep/Reject ledger",
        "",
        "| Trial | Status | Decision | Public metric | Reason |",
        "| ---: | --- | --- | ---: | --- |",
    ]
    if ledger is None:
        lines.append("| - | failed | - | - | No ledger was produced |")
    else:
        for trial in ledger.trials:
            metric = "" if trial.metric is None else f"{trial.metric:.8g}"
            reason = trial.reason.replace("|", "\\|").replace("\n", " ")
            lines.append(f"| {trial.number} | {trial.status} | {trial.decision} | {metric} | {reason} |")
    lines.extend(
        [
            "",
            "## Evidence boundary",
            "",
            "This is one bounded module repair in a pinned external repository, not a full-project benchmark. The evaluator subprocess receives a stripped environment but runs locally rather than in a network-isolated container. Hidden validation is withheld from the proposer context. Cost is derived from provider-reported tokens and the cited public rate, not from a billing-console receipt.",
            "",
        ]
    )
    return "\n".join(lines)


async def preflight(task_dir: Path, checkout: Path, python: Path) -> None:
    task, _ = validate_target(task_dir, checkout)
    with tempfile.TemporaryDirectory(prefix="repropilot-repository-preflight-") as temporary:
        workspace = Path(temporary)
        _, spec = materialize_workspace(checkout, task_dir, workspace)
        evaluator = LocalRepositoryEvaluator(workspace, python, float(task.get("command_timeout_seconds", 60)))
        for command in spec.guard_commands:
            result = await evaluator(command)
            if result.exit_code != 0:
                raise RuntimeError(result.stderr or result.stdout)
        public = await evaluator(spec.eval_command)
        hidden = await evaluator(spec.holdout_command)
        if public.exit_code != 0 or hidden.exit_code != 0:
            raise RuntimeError(public.stderr or hidden.stderr or public.stdout or hidden.stdout)
        print(
            f"Repository preflight: {task['id']} "
            f"public={parse_metric(public.stdout, spec.metric_key):.4f} "
            f"hidden={parse_metric(hidden.stdout, spec.metric_key):.4f}"
        )


async def run(args: argparse.Namespace) -> dict[str, Any]:
    task_dir = args.task_dir.resolve(strict=True)
    checkout = args.checkout.resolve(strict=True)
    python = args.python.resolve(strict=True)
    if args.preflight_only:
        await preflight(task_dir, checkout, python)
        return {}
    if args.output is None:
        raise ValueError("--output is required unless --preflight-only is used")
    output = args.output.resolve()
    if output.exists():
        raise ValueError(f"refusing to overwrite existing evidence directory: {output}")
    if (args.input_cost_per_million is None) != (args.output_cost_per_million is None):
        raise ValueError("input and output rates must be supplied together")
    if args.input_cost_per_million is not None and not all(
        (args.pricing_source, args.pricing_tier, args.pricing_verified_at)
    ):
        raise ValueError("pricing source, tier, and verification date are required with rates")

    task, baseline = validate_target(task_dir, checkout)
    harness_revision = git(ROOT, "rev-parse", "HEAD").lower()
    harness_dirty = bool(git(ROOT, "status", "--porcelain"))
    if harness_dirty and not args.allow_dirty:
        raise ValueError("live repository evaluation requires a clean harness checkout")
    load_env_file(args.env_file)
    client = LLMClient(offline_demo_mode=False)
    if not client.configured:
        raise RuntimeError("live repository evaluation requires OPENAI_API_KEY or --env-file")

    usage = ModelUsage()
    responses: list[dict[str, Any]] = []
    ledger: TrialLedger | None = None
    report: ValidationReport | None = None
    run_error = ""
    initial_sources: dict[str, str] = {}
    final_sources: dict[str, str] = {}
    frozen_spec: Any = None
    workspace_path: Path | None = None
    with tempfile.TemporaryDirectory(prefix=f"repropilot-{task['id']}-") as temporary:
        workspace = Path(temporary)
        workspace_path = workspace
        _, frozen_spec = materialize_workspace(checkout, task_dir, workspace)
        initial_sources = editable_sources(workspace, frozen_spec.editable_files)
        evaluator = LocalRepositoryEvaluator(workspace, python, float(task.get("command_timeout_seconds", 60)))
        proposer = live_proposer(client, usage, args.max_live_requests, responses)
        try:
            ledger = await run_autoresearch(workspace, frozen_spec, evaluator, proposer)
            ledger.model_usage = usage
            report = await validate_autoresearch(workspace, frozen_spec, ledger, evaluator)
        except Exception as exc:
            run_error = f"{type(exc).__name__}: {exc}"
        final_sources = editable_sources(workspace, frozen_spec.editable_files)

    outcome = classify_outcome(ledger, report, run_error)
    cost = cost_record(usage, len(responses), args)
    validation_observed = report.observed_score if report is not None else None
    model_record = usage.model_dump(mode="json")
    if not model_record["provider"]:
        model_record["provider"] = urlparse(client.base_url).hostname or client.base_url
    if not model_record["model"]:
        model_record["model"] = client.model

    result = {
        "version": RESULT_VERSION,
        "recorded_at": utc_now(),
        "task_id": task["id"],
        "outcome": outcome,
        "harness": {"revision": harness_revision, "source_tree_dirty": harness_dirty},
        "sanitization": {"workspace_paths_replaced_with": "{workspace}"},
        "repository": {
            "url": task["repository"]["url"],
            "revision": task["repository"]["revision"],
            "git_blob_sha256": task["repository"]["git_blob_sha256"],
            "editable_files": frozen_spec.editable_files,
            "working_tree_matches_git_blobs": True,
        },
        "baseline_artifact_sha256": sha256_file(task_dir / "baseline.json"),
        "search": {
            "baseline_score": ledger.baseline_score if ledger is not None else baseline["baseline"]["public_score"],
            "best_score": ledger.best_score if ledger is not None else None,
            "completed_trials": ledger.completed_trials if ledger is not None else 0,
            "accepted_trials": ledger.accepted_trials if ledger is not None else 0,
            "stop_reason": ledger.stop_reason if ledger is not None else "",
            "request_cap": args.max_live_requests,
        },
        "model": {
            **model_record,
            "attempted_request_count": len(responses),
            "mode": "live_model",
        },
        "cost": cost,
        "validation": {
            "status": report.status if report is not None else "not_run",
            "mode": report.validation_mode if report is not None else "hidden_holdout",
            "baseline_score": ledger.holdout_baseline_score if ledger is not None else baseline["baseline"]["hidden_score"],
            "acceptance_rule": report.acceptance_rule if report is not None else "not_run",
            "acceptance_delta": report.acceptance_delta if report is not None else None,
            "acceptance_target_score": report.acceptance_target_score if report is not None else None,
            "observed_scores": report.observed_scores if report is not None else [],
            "observed_score": validation_observed,
            "candidate_intact": report.candidate_intact if report is not None else False,
            "protected_files_intact": report.protected_files_intact if report is not None else False,
            "reason": report.reason if report is not None else run_error,
        },
        "failure": {"error": run_error},
        "boundaries": [
            *task["boundaries"],
            "The candidate was executed by local subprocess with a stripped environment, not a network-isolated container.",
            "The hidden evaluator content was excluded from proposer context but remains inspectable in this public evidence package.",
            "Any monetary amount is token-derived from the cited public rate and is not a billing-console receipt.",
        ],
    }
    if workspace_path is None:
        raise RuntimeError("repository workspace was not materialized")
    result = sanitize_workspace_paths(result, workspace_path)
    frozen_spec_payload = sanitize_workspace_paths(frozen_spec.model_dump(mode="json"), workspace_path)
    response_payload = sanitize_workspace_paths(responses, workspace_path)
    ledger_payload = sanitize_workspace_paths(ledger.model_dump(mode="json"), workspace_path) if ledger is not None else None
    report_payload = sanitize_workspace_paths(report.model_dump(mode="json"), workspace_path) if report is not None else None

    output.mkdir(parents=True, exist_ok=False)
    write_editable_sources(output, "initial-files", initial_sources)
    write_editable_sources(output, "final-files", final_sources)
    (output / "candidate.patch").write_text(candidate_patch(initial_sources, final_sources), encoding="utf-8", newline="\n")
    write_json(output / "task-input.json", task)
    write_json(output / "frozen-spec.json", frozen_spec_payload)
    write_json(output / "model-responses.json", response_payload)
    if ledger_payload is not None:
        write_json(output / "trial-ledger.json", ledger_payload)
    if report_payload is not None:
        write_json(output / "validation-report.json", report_payload)
    (output / "README.md").write_text(render_report(result, ledger, task), encoding="utf-8", newline="\n")
    result["artifact_sha256"] = {
        path.relative_to(output).as_posix(): sha256_file(path)
        for path in sorted(output.rglob("*"))
        if path.is_file()
    }
    write_json(output / "result.json", result)
    print(
        f"Repository evaluation: {task['id']} outcome={outcome} "
        f"requests={usage.request_count} tokens={usage.total_tokens}"
    )
    print(f"Artifact: {output}")
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a bounded live AutoResearch evaluation against a pinned repository checkout.")
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--max-live-requests", type=int, default=3, choices=range(1, 9))
    parser.add_argument("--input-cost-per-million", type=float)
    parser.add_argument("--output-cost-per-million", type=float)
    parser.add_argument("--currency", default="USD")
    parser.add_argument("--pricing-source", default="")
    parser.add_argument("--pricing-tier", default="")
    parser.add_argument("--pricing-verified-at", default="")
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument("--preflight-only", action="store_true")
    return parser.parse_args()


def main() -> None:
    result = asyncio.run(run(parse_args()))
    if result and result["outcome"] != "validation_passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
