from __future__ import annotations

import hashlib
import json
import math
import os
import re
import statistics
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


SPEC_VERSION = "autoresearch.spec/v1"
LEDGER_VERSION = "autoresearch.ledger/v1"
VALIDATION_VERSION = "autoresearch.validation/v1"
REVISION_RE = re.compile(r"^[0-9a-fA-F]{40}(?:[0-9a-fA-F]{24})?$")
METRIC_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,127}$")
COMMAND_ALLOWLIST = {"python", "python3", "pytest"}
IGNORED_PARTS = {".git", ".repropilot", ".venv", ".pytest_cache", "node_modules", "__pycache__"}
DEPENDENCY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*(?:\[[A-Za-z0-9_,.-]+\])?(?:(?:===|==|~=|!=|<=|>=|<|>)[A-Za-z0-9*+!_.-]+)?$")
EDITABLE_CONTEXT_LIMIT = 32_000


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ResearchSpec(BaseModel):
    version: str = SPEC_VERSION
    name: str = Field(min_length=1, max_length=160)
    objective: str = Field(min_length=1, max_length=2000)
    repository_revision: str
    editable_files: list[str] = Field(min_length=1, max_length=8)
    protected_files: list[str] = Field(min_length=1, max_length=32)
    eval_command: list[str] = Field(min_length=2, max_length=32)
    holdout_command: list[str] = Field(default_factory=list, max_length=32)
    guard_commands: list[list[str]] = Field(default_factory=list, max_length=6)
    metric_key: str
    direction: Literal["maximize", "minimize"] = "maximize"
    min_delta: float = Field(default=0.0, ge=0)
    holdout_min_delta: float | None = Field(default=None, ge=0)
    target_score: float | None = None
    max_trials: int = Field(default=3, ge=1, le=12)
    max_wall_seconds: int = Field(default=600, ge=30, le=7200)
    search_runs: int = Field(default=1, ge=1, le=5)
    search_aggregation: Literal["mean", "median", "worst"] = "mean"
    validation_runs: int = Field(default=3, ge=1, le=5)
    dependencies: list[str] = Field(default_factory=list, max_length=32)
    frozen_files: dict[str, str] = Field(default_factory=dict)
    frozen_workspace_sha256: str = ""
    source_path: str = ""
    spec_sha256: str = ""

    @field_validator("repository_revision")
    @classmethod
    def validate_revision(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not REVISION_RE.fullmatch(normalized):
            raise ValueError("repository_revision must be a full 40- or 64-character commit SHA")
        return normalized

    @field_validator("metric_key")
    @classmethod
    def validate_metric_key(cls, value: str) -> str:
        if not METRIC_KEY_RE.fullmatch(value.strip()):
            raise ValueError("metric_key is invalid")
        return value.strip()

    @field_validator("target_score")
    @classmethod
    def validate_target(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("target_score must be finite")
        return value

    @field_validator("dependencies")
    @classmethod
    def validate_dependencies(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            dependency = value.strip()
            if not DEPENDENCY_RE.fullmatch(dependency):
                raise ValueError(f"AutoResearch dependency is not a bounded package specifier: {value}")
            if dependency not in normalized:
                normalized.append(dependency)
        return normalized

    @model_validator(mode="after")
    def validate_commands(self) -> "ResearchSpec":
        validate_command(self.eval_command)
        for command in self.guard_commands:
            validate_command(command)
        if self.holdout_command:
            validate_command(self.holdout_command)
            if self.holdout_command == self.eval_command:
                raise ValueError("holdout_command must differ from eval_command")
        elif self.holdout_min_delta is not None:
            raise ValueError("holdout_min_delta requires holdout_command")
        return self


class CommandResult(BaseModel):
    command: list[str]
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = 0


class CandidatePatch(BaseModel):
    path: str
    content: str | None = Field(default=None, max_length=256_000)
    search: str | None = Field(default=None, max_length=64_000)
    replace: str | None = Field(default=None, max_length=64_000)

    @model_validator(mode="after")
    def validate_operation(self) -> "CandidatePatch":
        uses_content = self.content is not None
        uses_text_edit = self.search is not None or self.replace is not None
        if uses_content == uses_text_edit:
            raise ValueError("patch must use exactly one of content or search/replace")
        if uses_content:
            if not self.content:
                raise ValueError("replacement content must not be empty")
            return self
        if not self.search or self.replace is None:
            raise ValueError("localized patch requires non-empty search and a replace value")
        if self.search == self.replace:
            raise ValueError("localized patch must change the matched text")
        return self


class CandidateProposal(BaseModel):
    status: Literal["candidate", "stop"] = "candidate"
    diagnosis: str = Field(default="", max_length=4000)
    hypothesis: str = Field(default="", max_length=4000)
    reason: str = Field(default="", max_length=4000)
    patches: list[CandidatePatch] = Field(default_factory=list, max_length=3)


class ResearchTrial(BaseModel):
    number: int
    status: str
    decision: str
    diagnosis: str = ""
    hypothesis: str = ""
    reason: str = ""
    patches: list[dict[str, Any]] = Field(default_factory=list)
    metric: float | None = None
    metric_samples: list[float] = Field(default_factory=list)
    metric_stddev: float = 0.0
    metric_aggregation: str = ""
    command_results: list[CommandResult] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime | None = None


class ModelUsage(BaseModel):
    provider: str = Field(default="", max_length=255)
    model: str = Field(default="", max_length=255)
    request_count: int = Field(default=0, ge=0)
    reported_request_count: int = Field(default=0, ge=0)
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)

    def record(self, usage: "ModelUsage") -> None:
        if usage.provider:
            self.provider = usage.provider
        if usage.model:
            self.model = usage.model
        self.request_count += usage.request_count
        self.reported_request_count += usage.reported_request_count
        self.prompt_tokens += usage.prompt_tokens
        self.completion_tokens += usage.completion_tokens
        self.total_tokens += usage.total_tokens


class TrialLedger(BaseModel):
    version: str = LEDGER_VERSION
    spec_sha256: str
    status: str = "running"
    metric_key: str
    direction: str
    baseline_score: float = 0.0
    best_score: float = 0.0
    holdout_baseline_score: float | None = None
    max_trials: int
    completed_trials: int = 0
    accepted_trials: int = 0
    stop_reason: str = ""
    best_candidate_files: dict[str, str] = Field(default_factory=dict)
    trials: list[ResearchTrial] = Field(default_factory=list)
    command_runs: int = 0
    command_duration_ms: int = 0
    model_usage: ModelUsage = Field(default_factory=ModelUsage)
    started_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime | None = None


class ValidationReport(BaseModel):
    version: str = VALIDATION_VERSION
    spec_sha256: str
    status: Literal["passed", "failed"]
    validation_mode: Literal["hidden_holdout", "public_replay"]
    expected_score: float
    baseline_score: float | None = None
    acceptance_rule: Literal["minimum_improvement", "public_replay_tolerance"] = (
        "public_replay_tolerance"
    )
    acceptance_delta: float = 0.0
    acceptance_target_score: float | None = None
    observed_scores: list[float]
    observed_score: float | None
    mean_score: float | None
    stddev: float
    passed_runs: int
    failed_runs: int
    score_matches: bool
    candidate_intact: bool
    protected_files_intact: bool
    command_results: list[CommandResult] = Field(default_factory=list)
    reason: str = ""


Evaluator = Callable[[list[str]], Awaitable[CommandResult]]
Proposer = Callable[[dict[str, Any]], Awaitable[CandidateProposal]]


def validate_command(command: list[str]) -> None:
    if not command or len(command) > 32:
        raise ValueError("AutoResearch command must contain 1 to 32 arguments")
    executable = Path(str(command[0])).name.lower()
    if executable not in COMMAND_ALLOWLIST:
        raise ValueError(f"AutoResearch executable is not allowed: {executable}")
    for argument in command:
        value = str(argument)
        if not value or "\x00" in value or "\r" in value or "\n" in value or len(value) > 4096:
            raise ValueError("AutoResearch command contains an invalid argument")


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_existing_file(root: Path, relative: str, *, max_bytes: int = 512_000) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"AutoResearch path must be relative: {relative}")
    path = root / candidate
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"AutoResearch file is missing or unsafe: {relative}")
    resolved = path.resolve(strict=True)
    if root != resolved and root not in resolved.parents:
        raise ValueError(f"AutoResearch path escaped workspace: {relative}")
    if resolved.stat().st_size > max_bytes:
        raise ValueError(f"AutoResearch file exceeds size limit: {relative}")
    return resolved


def _normalized_paths(root: Path, values: list[str], *, max_bytes: int = 512_000) -> list[str]:
    normalized: list[str] = []
    for value in values:
        path = _safe_existing_file(root, str(value), max_bytes=max_bytes)
        relative = path.relative_to(root).as_posix()
        if relative not in normalized:
            normalized.append(relative)
    return normalized


def hash_files(root: Path, relatives: list[str]) -> dict[str, str]:
    return {relative: sha256_file(_safe_existing_file(root, relative)) for relative in relatives}


def workspace_fingerprint(root: Path, editable_files: list[str]) -> str:
    editable = set(editable_files)
    records: list[tuple[str, str]] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any(part in IGNORED_PARTS for part in relative.parts):
            continue
        name = relative.as_posix()
        if name in editable:
            continue
        if path.is_symlink():
            records.append((name, "symlink"))
        elif path.is_file():
            records.append((name, sha256_file(path)))
        if len(records) > 5000:
            raise ValueError("AutoResearch workspace contains too many files")
    return canonical_sha256(records)


def _spec_payload(spec: ResearchSpec) -> dict[str, Any]:
    payload = spec.model_dump(mode="json")
    payload["spec_sha256"] = ""
    return payload


def parse_uploaded_research_spec(uploads: Any) -> dict[str, Any] | None:
    if not isinstance(uploads, list):
        return None
    for item in uploads:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).lower()
        if not name.endswith(".json"):
            continue
        source = Path(str(item.get("storage_path", "")))
        if not source.is_file() or source.is_symlink() or source.stat().st_size > 256_000:
            continue
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and payload.get("version") == SPEC_VERSION:
            return payload
    return None


def locate_research_spec(workspace: str | Path) -> tuple[dict[str, Any], str]:
    root = Path(workspace).resolve(strict=True)
    candidates = [root / "autoresearch.json", root / ".repropilot" / "autoresearch" / "spec.json"]
    upload_root = root / ".repropilot" / "uploads"
    if upload_root.is_dir() and not upload_root.is_symlink():
        candidates.extend(sorted(upload_root.glob("*.json")))
    for path in candidates:
        try:
            if path.is_symlink() or not path.is_file() or path.stat().st_size > 256_000:
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and payload.get("version") == SPEC_VERSION:
            return payload, path.relative_to(root).as_posix()
    raise ValueError("AutoResearch spec not found; upload an autoresearch.spec/v1 JSON file")


def freeze_research_spec(
    workspace: str | Path,
    payload: dict[str, Any],
    repo_manifest: dict[str, Any],
    *,
    source_path: str = "",
) -> ResearchSpec:
    root = Path(workspace).resolve(strict=True)
    spec = ResearchSpec.model_validate(payload)
    actual_revision = str(repo_manifest.get("repository_commit", "")).strip().lower()
    requested_revision = str(repo_manifest.get("requested_revision", "")).strip().lower()
    if actual_revision != spec.repository_revision or requested_revision != spec.repository_revision:
        raise ValueError("AutoResearch repository_revision does not match prepared repository commit")
    spec.editable_files = _normalized_paths(root, spec.editable_files)
    spec.protected_files = _normalized_paths(root, spec.protected_files, max_bytes=2_000_000)
    overlap = set(spec.editable_files) & set(spec.protected_files)
    if overlap:
        raise ValueError(f"editable and protected files overlap: {sorted(overlap)}")
    protected_set = set(spec.protected_files)
    for command_name, command in (("eval_command", spec.eval_command), ("holdout_command", spec.holdout_command)):
        if not command:
            continue
        entrypoints = [str(argument) for argument in command[1:] if str(argument).endswith(".py")]
        if not entrypoints:
            raise ValueError(f"{command_name} must reference a protected Python evaluator file")
        entrypoint = _safe_existing_file(root, entrypoints[-1], max_bytes=2_000_000).relative_to(root).as_posix()
        if entrypoint not in protected_set:
            raise ValueError(f"{command_name} evaluator entrypoint must be protected")
    spec.source_path = source_path
    spec.frozen_files = hash_files(root, spec.protected_files)
    spec.frozen_workspace_sha256 = workspace_fingerprint(root, spec.editable_files)
    spec.spec_sha256 = canonical_sha256(_spec_payload(spec))
    return spec


def snapshot_files(root: Path, relatives: list[str]) -> dict[str, bytes]:
    return {relative: _safe_existing_file(root, relative).read_bytes() for relative in relatives}


def snapshot_immutable_workspace(root: Path, editable_files: list[str]) -> dict[str, bytes]:
    editable = set(editable_files)
    snapshots: dict[str, bytes] = {}
    total = 0
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any(part in IGNORED_PARTS for part in relative.parts) or relative.as_posix() in editable:
            continue
        if path.is_file() and not path.is_symlink():
            content = path.read_bytes()
            total += len(content)
            if total > 32 * 1024 * 1024:
                raise ValueError("AutoResearch immutable workspace snapshot exceeds 32 MiB")
            snapshots[relative.as_posix()] = content
    return snapshots


def restore_files(root: Path, snapshots: dict[str, bytes]) -> None:
    for relative, content in snapshots.items():
        path = _safe_existing_file(root, relative)
        parent = path.parent
        if parent.is_symlink():
            raise ValueError(f"refusing to restore through symlinked parent: {relative}")
        temporary = parent / f".{path.name}.autoresearch-{os.getpid()}.tmp"
        temporary.write_bytes(content)
        os.replace(temporary, path)


def restore_immutable_workspace(root: Path, editable_files: list[str], snapshots: dict[str, bytes]) -> None:
    editable = set(editable_files)
    current: set[str] = set()
    for path in sorted(root.rglob("*"), reverse=True):
        relative = path.relative_to(root)
        if any(part in IGNORED_PARTS for part in relative.parts) or relative.as_posix() in editable:
            continue
        name = relative.as_posix()
        if path.is_file() or path.is_symlink():
            current.add(name)
            if name not in snapshots:
                path.unlink(missing_ok=True)
    for relative, content in snapshots.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink():
            path.unlink()
        temporary = path.parent / f".{path.name}.immutable-{os.getpid()}.tmp"
        temporary.write_bytes(content)
        os.replace(temporary, path)


def parse_metric(stdout: str, metric_key: str) -> float:
    values: list[Any] = []
    decoder = json.JSONDecoder()
    for index, char in enumerate(stdout):
        if char not in "{[":
            continue
        try:
            value, _ = decoder.raw_decode(stdout[index:])
        except json.JSONDecodeError:
            continue
        values.append(value)
    for value in reversed(values):
        current: Any = value
        try:
            for part in metric_key.split("."):
                current = current[part] if isinstance(current, dict) else None
            metric = float(current)
        except (KeyError, TypeError, ValueError):
            continue
        if math.isfinite(metric):
            return metric
    raise ValueError(f"evaluator did not emit finite metric {metric_key!r}")


def aggregate_scores(scores: list[float], aggregation: str, direction: str) -> float:
    if not scores or any(not math.isfinite(value) for value in scores):
        raise ValueError("AutoResearch scores must be finite and non-empty")
    if aggregation == "mean":
        return statistics.fmean(scores)
    if aggregation == "median":
        return statistics.median(scores)
    if aggregation == "worst":
        return min(scores) if direction == "maximize" else max(scores)
    raise ValueError(f"unsupported score aggregation: {aggregation}")


def improved(candidate: float, best: float, direction: str, min_delta: float) -> bool:
    delta = candidate - best if direction == "maximize" else best - candidate
    return delta >= min_delta and candidate != best


def target_reached(score: float, target: float | None, direction: str) -> bool:
    if target is None:
        return False
    return score >= target if direction == "maximize" else score <= target


async def _evaluate(spec: ResearchSpec, evaluator: Evaluator, command: list[str] | None = None, runs: int | None = None) -> tuple[float, list[float], list[CommandResult]]:
    scores: list[float] = []
    results: list[CommandResult] = []
    selected = command or spec.eval_command
    count = runs or spec.search_runs
    for _ in range(count):
        for guard in spec.guard_commands:
            guarded = await evaluator(guard)
            results.append(guarded)
            if guarded.exit_code != 0:
                raise RuntimeError(f"guard command failed: {guarded.stderr or guarded.stdout}")
        result = await evaluator(selected)
        results.append(result)
        if result.exit_code != 0:
            raise RuntimeError(f"evaluator command failed: {result.stderr or result.stdout}")
        scores.append(parse_metric(result.stdout, spec.metric_key))
    return aggregate_scores(scores, spec.search_aggregation, spec.direction), scores, results


def _assert_integrity(root: Path, spec: ResearchSpec) -> None:
    if hash_files(root, spec.protected_files) != spec.frozen_files:
        raise RuntimeError("AutoResearch protected evaluator or data changed")
    if workspace_fingerprint(root, spec.editable_files) != spec.frozen_workspace_sha256:
        raise RuntimeError("AutoResearch non-editable workspace changed")


def _apply_candidate(root: Path, spec: ResearchSpec, proposal: CandidateProposal) -> list[dict[str, Any]]:
    if not proposal.patches:
        raise ValueError("candidate must include at least one patch")
    editable = set(spec.editable_files)
    records: list[dict[str, Any]] = []
    operations: dict[str, str] = {}
    for patch in proposal.patches:
        path = _safe_existing_file(root, patch.path)
        relative = path.relative_to(root).as_posix()
        if relative not in editable:
            raise ValueError(f"candidate patch is not authorized: {patch.path}")
        before = sha256_file(path)
        if patch.content is not None:
            if relative in operations:
                raise ValueError(f"complete replacement cannot be combined with other patches: {relative}")
            if path.stat().st_size > EDITABLE_CONTEXT_LIMIT:
                raise ValueError(f"complete replacement is not allowed for excerpted file: {relative}")
            operation = "replace_file"
            content = patch.content.encode()
            record = {"path": relative, "operation": operation, "before_sha256": before}
        else:
            if operations.get(relative) == "replace_file":
                raise ValueError(f"complete replacement cannot be combined with other patches: {relative}")
            operation = "replace_text"
            original = path.read_text(encoding="utf-8")
            assert patch.search is not None and patch.replace is not None
            occurrences = original.count(patch.search)
            if occurrences != 1:
                raise ValueError(
                    f"localized patch search must match exactly once in {relative}; matched {occurrences} times"
                )
            content = original.replace(patch.search, patch.replace, 1).encode()
            record = {
                "path": relative,
                "operation": operation,
                "before_sha256": before,
                "search_sha256": hashlib.sha256(patch.search.encode()).hexdigest(),
            }
        operations[relative] = operation
        if not content or len(content) > 256_000:
            raise ValueError(f"candidate content is empty or too large: {relative}")
        temporary = path.parent / f".{path.name}.candidate-{os.getpid()}.tmp"
        temporary.write_bytes(content)
        os.replace(temporary, path)
        records.append({**record, "after_sha256": sha256_file(path)})
    return records


def evaluator_feedback(results: list[CommandResult], limit: int = 12_000) -> str:
    chunks: list[str] = []
    seen: set[str] = set()
    for result in results:
        for stream, value in (("stdout", result.stdout), ("stderr", result.stderr)):
            content = value.strip()
            if not content or content in seen:
                continue
            seen.add(content)
            chunks.append(
                f"command={json.dumps(result.command, ensure_ascii=False)} "
                f"exit_code={result.exit_code} {stream}:\n{content}"
            )
    return "\n\n".join(chunks)[:limit]


def objective_terms(objective: str) -> set[str]:
    ignored = {
        "behavior",
        "including",
        "regressing",
        "requested",
        "whenever",
        "without",
        "should",
        "function",
        "values",
        "value",
        "files",
        "true",
        "false",
    }
    return {
        token.lower()
        for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]{3,}", objective)
        if token.lower() not in ignored
    }


def editable_file_context(path: Path, objective: str, limit: int = EDITABLE_CONTEXT_LIMIT) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines(keepends=True)
    if len(text) <= limit:
        return {
            "mode": "full",
            "patch_mode": "replace_text_or_file",
            "total_characters": len(text),
            "total_lines": len(lines),
            "content": text,
        }

    terms = objective_terms(objective)
    scored: list[tuple[int, int]] = []
    for index, line in enumerate(lines):
        lowered = line.lower()
        matches = sum(term in lowered for term in terms)
        if matches:
            definition_bonus = 20 if line.lstrip().startswith(("def ", "class ")) else 0
            scored.append((definition_bonus + matches, index))
    centers = [index for _, index in sorted(scored, key=lambda item: (-item[0], item[1]))]
    selected: set[int] = set()
    selected_characters = 0
    for center in centers:
        start = max(0, center - 50)
        end = min(len(lines), center + 51)
        new_indexes = [index for index in range(start, end) if index not in selected]
        added = sum(len(lines[index]) for index in new_indexes)
        if selected and selected_characters + added > limit:
            continue
        selected.update(new_indexes)
        selected_characters += added
        if selected_characters >= limit * 0.8:
            break
    if not selected:
        selected.update(range(min(len(lines), 200)))

    ranges: list[tuple[int, int]] = []
    for index in sorted(selected):
        if not ranges or index > ranges[-1][1]:
            ranges.append((index, index + 1))
        else:
            ranges[-1] = (ranges[-1][0], index + 1)
    excerpts = [
        {"start_line": start + 1, "end_line": end, "content": "".join(lines[start:end])}
        for start, end in ranges
    ]
    return {
        "mode": "excerpts",
        "patch_mode": "replace_text_required",
        "total_characters": len(text),
        "total_lines": len(lines),
        "objective_terms": sorted(terms),
        "excerpts": excerpts,
    }


def proposal_context(root: Path, spec: ResearchSpec, ledger: TrialLedger, rejected_feedback: str = "") -> dict[str, Any]:
    files = {
        relative: editable_file_context(_safe_existing_file(root, relative), spec.objective)
        for relative in spec.editable_files
    }
    public_spec = spec.model_dump(mode="json", exclude={"holdout_command", "holdout_min_delta", "protected_files", "frozen_files"})
    return {
        "spec": public_spec,
        "editable_files": files,
        "baseline_score": ledger.baseline_score,
        "best_score": ledger.best_score,
        "previous_trials": [trial.model_dump(mode="json", exclude={"command_results"}) for trial in ledger.trials[-4:]],
        "rejected_feedback": rejected_feedback[:12_000],
    }


async def run_autoresearch(workspace: str | Path, spec: ResearchSpec, evaluator: Evaluator, proposer: Proposer) -> TrialLedger:
    root = Path(workspace).resolve(strict=True)
    if spec.spec_sha256 != canonical_sha256(_spec_payload(spec)):
        raise ValueError("AutoResearch frozen spec hash mismatch")
    _assert_integrity(root, spec)
    original = snapshot_files(root, spec.editable_files)
    immutable_original = snapshot_immutable_workspace(root, spec.editable_files)
    best = dict(original)
    ledger = TrialLedger(spec_sha256=spec.spec_sha256, metric_key=spec.metric_key, direction=spec.direction, max_trials=spec.max_trials)
    started = time.monotonic()
    try:
        baseline, samples, commands = await _evaluate(spec, evaluator)
        _assert_integrity(root, spec)
        trial = ResearchTrial(number=0, status="baseline", decision="keep", reason="frozen baseline", metric=baseline, metric_samples=samples, metric_stddev=statistics.pstdev(samples) if len(samples) > 1 else 0.0, metric_aggregation=spec.search_aggregation, command_results=commands, finished_at=utc_now())
        ledger.trials.append(trial)
        ledger.baseline_score = baseline
        ledger.best_score = baseline
        if spec.holdout_command:
            holdout, _, holdout_results = await _evaluate(spec, evaluator, spec.holdout_command, 1)
            _assert_integrity(root, spec)
            ledger.holdout_baseline_score = holdout
            ledger.command_runs += len(holdout_results)
            ledger.command_duration_ms += sum(item.duration_ms for item in holdout_results)
        ledger.command_runs += len(commands)
        ledger.command_duration_ms += sum(item.duration_ms for item in commands)
    except Exception:
        restore_immutable_workspace(root, spec.editable_files, immutable_original)
        restore_files(root, original)
        ledger.status = "failed"
        ledger.stop_reason = "baseline_failed"
        ledger.finished_at = utc_now()
        raise

    evaluation_feedback = ""
    for number in range(1, spec.max_trials + 1):
        if time.monotonic() - started >= spec.max_wall_seconds:
            ledger.stop_reason = "wall_time_budget_exhausted"
            break
        trial = ResearchTrial(number=number, status="running", decision="reject")
        try:
            proposal = await proposer(proposal_context(root, spec, ledger, rejected_feedback=evaluation_feedback))
            trial.diagnosis = proposal.diagnosis
            trial.hypothesis = proposal.hypothesis
            if proposal.status == "stop":
                trial.status = "stopped"
                trial.reason = proposal.reason or "candidate model stopped"
                trial.finished_at = utc_now()
                ledger.trials.append(trial)
                ledger.stop_reason = "candidate_stopped"
                break
            trial.patches = _apply_candidate(root, spec, proposal)
            _assert_integrity(root, spec)
            score, samples, commands = await _evaluate(spec, evaluator)
            _assert_integrity(root, spec)
            trial.metric = score
            trial.metric_samples = samples
            trial.metric_stddev = statistics.pstdev(samples) if len(samples) > 1 else 0.0
            trial.metric_aggregation = spec.search_aggregation
            trial.command_results = commands
            ledger.command_runs += len(commands)
            ledger.command_duration_ms += sum(item.duration_ms for item in commands)
            if improved(score, ledger.best_score, spec.direction, spec.min_delta):
                trial.status = "kept"
                trial.decision = "keep"
                trial.reason = f"{spec.metric_key} improved from {ledger.best_score:.8g} to {score:.8g}"
                ledger.best_score = score
                ledger.accepted_trials += 1
                best = snapshot_files(root, spec.editable_files)
                continuation = (
                    f"target {spec.target_score!r} was not reached"
                    if spec.target_score is not None
                    else "the trial budget allows further improvement"
                )
                evaluation_feedback = (
                    f"Candidate improved to {score:.8g}, but {continuation}. "
                    f"Remaining public evaluator output:\n{evaluator_feedback(commands)}"
                )[:12_000]
            else:
                trial.status = "rejected"
                trial.reason = f"{spec.metric_key} did not improve by required delta {spec.min_delta:.8g}"
                evaluation_feedback = (
                    f"{trial.reason}; samples={samples}; public evaluator output:\n{evaluator_feedback(commands)}\n"
                    f"Rejected candidate: {proposal.model_dump_json()}"
                )[:12_000]
                restore_files(root, best)
        except Exception as exc:
            trial.status = "rejected"
            trial.reason = f"{type(exc).__name__}: {exc}".rstrip(": ")[:4000]
            evaluation_feedback = trial.reason
            restore_files(root, best)
            try:
                _assert_integrity(root, spec)
            except Exception:
                restore_immutable_workspace(root, spec.editable_files, immutable_original)
                restore_files(root, original)
                ledger.status = "failed"
                ledger.stop_reason = "integrity_failure"
                trial.decision = "abort"
                trial.finished_at = utc_now()
                ledger.trials.append(trial)
                ledger.finished_at = utc_now()
                raise
        trial.finished_at = utc_now()
        ledger.trials.append(trial)
        ledger.completed_trials += 1
        if trial.decision == "keep" and target_reached(ledger.best_score, spec.target_score, spec.direction):
            ledger.stop_reason = "target_score_reached"
            break
    if not ledger.stop_reason:
        ledger.stop_reason = "trial_budget_exhausted"
    restore_files(root, best)
    _assert_integrity(root, spec)
    ledger.best_candidate_files = hash_files(root, spec.editable_files)
    ledger.status = "completed"
    ledger.finished_at = utc_now()
    return ledger


async def validate_autoresearch(workspace: str | Path, spec: ResearchSpec, ledger: TrialLedger, evaluator: Evaluator) -> ValidationReport:
    root = Path(workspace).resolve(strict=True)
    if spec.spec_sha256 != canonical_sha256(_spec_payload(spec)):
        raise ValueError("AutoResearch frozen spec hash mismatch")
    if ledger.spec_sha256 != spec.spec_sha256 or ledger.metric_key != spec.metric_key or ledger.direction != spec.direction:
        raise ValueError("AutoResearch trial ledger does not match the frozen spec")
    candidate_intact = hash_files(root, spec.editable_files) == ledger.best_candidate_files
    protected_intact = hash_files(root, spec.protected_files) == spec.frozen_files and workspace_fingerprint(root, spec.editable_files) == spec.frozen_workspace_sha256
    command = spec.holdout_command or spec.eval_command
    mode: Literal["hidden_holdout", "public_replay"] = "hidden_holdout" if spec.holdout_command else "public_replay"
    results: list[CommandResult] = []
    scores: list[float] = []
    reason = ""
    if candidate_intact and protected_intact:
        for _ in range(spec.validation_runs):
            result = await evaluator(command)
            results.append(result)
            if result.exit_code != 0:
                reason = result.stderr or result.stdout or "validation command failed"
                continue
            try:
                scores.append(parse_metric(result.stdout, spec.metric_key))
            except ValueError as exc:
                reason = str(exc)
    candidate_intact = candidate_intact and hash_files(root, spec.editable_files) == ledger.best_candidate_files
    protected_intact = protected_intact and hash_files(root, spec.protected_files) == spec.frozen_files and workspace_fingerprint(root, spec.editable_files) == spec.frozen_workspace_sha256
    expected = ledger.holdout_baseline_score if mode == "hidden_holdout" else ledger.best_score
    if expected is None:
        expected = ledger.best_score
    observed = aggregate_scores(scores, spec.search_aggregation, spec.direction) if scores else None
    if mode == "hidden_holdout":
        threshold = spec.holdout_min_delta if spec.holdout_min_delta is not None else spec.min_delta
        acceptance_rule: Literal["minimum_improvement", "public_replay_tolerance"] = "minimum_improvement"
        acceptance_delta = threshold
        acceptance_target = expected + threshold if spec.direction == "maximize" else expected - threshold
        score_matches = observed is not None and len(scores) == spec.validation_runs and improved(observed, expected, spec.direction, threshold)
    else:
        tolerance = max(1e-9, spec.min_delta)
        acceptance_rule = "public_replay_tolerance"
        acceptance_delta = tolerance
        acceptance_target = expected
        score_matches = observed is not None and len(scores) == spec.validation_runs and abs(observed - expected) <= tolerance
    passed = candidate_intact and protected_intact and score_matches
    if not candidate_intact:
        reason = "best candidate files no longer match the trial ledger"
    elif not protected_intact:
        reason = "protected or non-editable workspace files changed"
    elif not score_matches and not reason:
        reason = "fresh validation score did not satisfy the frozen acceptance rule"
    return ValidationReport(
        spec_sha256=spec.spec_sha256,
        status="passed" if passed else "failed",
        validation_mode=mode,
        expected_score=expected,
        baseline_score=expected,
        acceptance_rule=acceptance_rule,
        acceptance_delta=acceptance_delta,
        acceptance_target_score=acceptance_target,
        observed_scores=scores,
        observed_score=observed,
        mean_score=statistics.fmean(scores) if scores else None,
        stddev=statistics.pstdev(scores) if len(scores) > 1 else 0.0,
        passed_runs=len(scores),
        failed_runs=spec.validation_runs - len(scores),
        score_matches=score_matches,
        candidate_intact=candidate_intact,
        protected_files_intact=protected_intact,
        command_results=results,
        reason=reason,
    )
