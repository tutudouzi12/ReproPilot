from __future__ import annotations

import json
import math
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .autoresearch import ResearchSpec, TrialLedger, ValidationReport, canonical_sha256
from .trajectory import (
    TrajectoryEvent,
    TrajectoryManifest,
    evidence_sha256,
    parse_trajectory_jsonl,
    verify_trajectory,
)


ASSESSMENT_VERSION = "autoresearch.assessment/v1"
ASSESSMENT_METHOD = "deterministic_raw_facts_no_composite_score"
RUN_FACT_FIELDS = ("outcome", "search", "model", "validation", "failure")


class AssessmentModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AssessmentEvidence(AssessmentModel):
    trajectory_source: Literal["native_hash_linked", "derived_from_ledger"]
    integrity: Literal["verified", "partial"]
    spec_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    trajectory_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    last_event_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    ledger_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    validation_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    failure_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    run_facts_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    source_bindings_verified: bool | None = None


class OutcomeFacts(AssessmentModel):
    status: Literal["passed", "failed", "not_assessable"]
    terminal_status: str
    metric_key: str | None = None
    direction: Literal["maximize", "minimize"] | None = None
    baseline_score: float | None = None
    best_score: float | None = None
    directional_improvement: float | None = None
    validation_status: Literal["passed", "failed", "not_run"]
    validation_mode: Literal["hidden_holdout", "public_replay"] | None = None
    validation_baseline_score: float | None = None
    validation_observed_score: float | None = None
    acceptance_rule: Literal["minimum_improvement", "public_replay_tolerance"] | None = None
    acceptance_delta: float | None = None
    acceptance_target_score: float | None = None
    score_matches: bool | None = None
    validation_passed_runs: int | None = Field(default=None, ge=0)
    validation_failed_runs: int | None = Field(default=None, ge=0)


class ComplianceFacts(AssessmentModel):
    status: Literal["verified", "violated", "partial"]
    hard_violation: bool
    hard_violation_reasons: list[str]
    trajectory_chain_verified: bool | None = None
    terminal_evidence_bindings_verified: bool | None = None
    spec_ledger_alignment: bool | None = None
    spec_validation_alignment: bool | None = None
    candidate_intact: bool | None = None
    protected_files_intact: bool | None = None
    integrity_stop_triggered: bool | None = None


class ProcessFacts(AssessmentModel):
    status: Literal["complete", "partial"]
    event_count: int | None = Field(default=None, ge=0)
    sequence_verified: bool | None = None
    finish_event_present: bool | None = None
    baseline_completed: bool | None = None
    event_type_counts: dict[str, int]
    event_status_counts: dict[str, dict[str, int]]
    decision_counts: dict[str, int]
    rollback_count: int | None = Field(default=None, ge=0)
    completed_trials: int | None = Field(default=None, ge=0)
    accepted_trials: int | None = Field(default=None, ge=0)
    max_trials: int | None = Field(default=None, ge=0)
    command_runs: int | None = Field(default=None, ge=0)
    command_duration_ms: int | None = Field(default=None, ge=0)
    stop_reason: str | None = None
    request_cap: int | None = Field(default=None, ge=0)
    attempted_requests: int | None = Field(default=None, ge=0)
    completed_responses: int | None = Field(default=None, ge=0)
    usage_reports: int | None = Field(default=None, ge=0)
    reported_tokens: int | None = Field(default=None, ge=0)


class AssessmentScoring(AssessmentModel):
    status: Literal["not_calculated"] = "not_calculated"
    composite_score: None = None
    reason: Literal["raw dimension facts are retained before any validated weighting policy"] = (
        "raw dimension facts are retained before any validated weighting policy"
    )


class RunAssessment(AssessmentModel):
    version: Literal[ASSESSMENT_VERSION] = ASSESSMENT_VERSION
    method: Literal[ASSESSMENT_METHOD] = ASSESSMENT_METHOD
    evidence: AssessmentEvidence
    outcome: OutcomeFacts
    compliance: ComplianceFacts
    process: ProcessFacts
    scoring: AssessmentScoring = Field(default_factory=AssessmentScoring)


def _model_payload(value: BaseModel | dict[str, Any] | None, model: type[BaseModel]) -> tuple[dict[str, Any] | None, BaseModel | None]:
    if value is None:
        return None, None
    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else dict(value)
    return payload, model.model_validate(payload)


def _validated_spec(value: ResearchSpec | dict[str, Any]) -> tuple[dict[str, Any], ResearchSpec]:
    payload = value.model_dump(mode="json") if isinstance(value, ResearchSpec) else dict(value)
    spec = ResearchSpec.model_validate(payload)
    hash_payload = spec.model_dump(mode="json")
    hash_payload["spec_sha256"] = ""
    if spec.spec_sha256 != canonical_sha256(hash_payload):
        raise ValueError("assessment frozen spec hash mismatch")
    return payload, spec


def _run_facts(result: dict[str, Any] | None) -> dict[str, Any] | None:
    if result is None:
        return None
    return {field: result.get(field) for field in RUN_FACT_FIELDS}


def _finite_optional(value: Any, label: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"assessment {label} must be finite")
    return float(value)


def _nonnegative_int_optional(value: Any, label: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"assessment {label} must be a non-negative integer")
    return value


def _event_facts(events: list[TrajectoryEvent]) -> dict[str, Any]:
    event_types: Counter[str] = Counter()
    event_statuses: dict[str, Counter[str]] = defaultdict(Counter)
    decisions: Counter[str] = Counter()
    for event in events:
        event_types[event.event_type] += 1
        status = event.payload.get("status")
        if isinstance(status, str) and status:
            event_statuses[event.event_type][status] += 1
        if event.event_type == "decision":
            decision = event.payload.get("decision")
            if isinstance(decision, str) and decision:
                decisions[decision] += 1
    return {
        "event_type_counts": dict(sorted(event_types.items())),
        "event_status_counts": {
            event_type: dict(sorted(statuses.items()))
            for event_type, statuses in sorted(event_statuses.items())
        },
        "decision_counts": dict(sorted(decisions.items())),
        "baseline_completed": any(
            event.event_type == "baseline" and event.payload.get("status") == "completed" for event in events
        ),
    }


def build_assessment(
    *,
    spec: ResearchSpec | dict[str, Any],
    ledger: TrialLedger | dict[str, Any] | None = None,
    validation: ValidationReport | dict[str, Any] | None = None,
    trajectory_jsonl: str | None = None,
    trajectory_manifest: TrajectoryManifest | dict[str, Any] | str | None = None,
    failure: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
) -> RunAssessment:
    _, spec_model = _validated_spec(spec)
    ledger_payload, selected_ledger = _model_payload(ledger, TrialLedger)
    validation_payload, selected_validation = _model_payload(validation, ValidationReport)
    ledger_model = selected_ledger if isinstance(selected_ledger, TrialLedger) else None
    validation_model = selected_validation if isinstance(selected_validation, ValidationReport) else None
    if ledger_model is not None and ledger_model.spec_sha256 != spec_model.spec_sha256:
        raise ValueError("assessment ledger does not match frozen spec")
    if validation_model is not None and validation_model.spec_sha256 != spec_model.spec_sha256:
        raise ValueError("assessment validation does not match frozen spec")

    has_trajectory = trajectory_jsonl is not None or trajectory_manifest is not None
    events: list[TrajectoryEvent] = []
    manifest_model: TrajectoryManifest | None = None
    if has_trajectory:
        if trajectory_jsonl is None or trajectory_manifest is None:
            raise ValueError("assessment native trajectory requires JSONL and manifest")
        if isinstance(trajectory_manifest, str):
            manifest_model = TrajectoryManifest.model_validate_json(trajectory_manifest)
        elif isinstance(trajectory_manifest, TrajectoryManifest):
            manifest_model = trajectory_manifest
        else:
            manifest_model = TrajectoryManifest.model_validate(trajectory_manifest)
        if (manifest_model.ledger_sha256 is None) != (ledger_payload is None):
            raise ValueError("assessment trajectory ledger evidence is missing or unexpected")
        if (manifest_model.validation_sha256 is None) != (validation_payload is None):
            raise ValueError("assessment trajectory validation evidence is missing or unexpected")
        if (manifest_model.failure_sha256 is None) != (failure is None):
            raise ValueError("assessment trajectory failure evidence is missing or unexpected")
        verification = verify_trajectory(
            trajectory_jsonl,
            manifest_model,
            spec_sha256=spec_model.spec_sha256,
            ledger=ledger_payload,
            validation=validation_payload,
            failure=failure,
        )
        events = parse_trajectory_jsonl(trajectory_jsonl)
        trajectory_source: Literal["native_hash_linked", "derived_from_ledger"] = "native_hash_linked"
        integrity: Literal["verified", "partial"] = "verified"
        source_bindings_verified: bool | None = True
        trajectory_sha256 = verification.trajectory_sha256
        last_event_sha256 = verification.last_event_sha256
        terminal_status = verification.terminal_status
    else:
        if ledger_model is None and validation_model is None:
            raise ValueError("assessment legacy derivation requires a ledger or validation report")
        trajectory_source = "derived_from_ledger"
        integrity = "partial"
        source_bindings_verified = None
        trajectory_sha256 = None
        last_event_sha256 = None
        terminal_status = str(
            result.get("outcome")
            if result is not None and result.get("outcome")
            else validation_model.status
            if validation_model is not None
            else ledger_model.status
        )

    baseline_score = _finite_optional(ledger_model.baseline_score, "baseline score") if ledger_model else None
    best_score = _finite_optional(ledger_model.best_score, "best score") if ledger_model else None
    directional_improvement = None
    if baseline_score is not None and best_score is not None:
        directional_improvement = (
            best_score - baseline_score if spec_model.direction == "maximize" else baseline_score - best_score
        )
    validation_status: Literal["passed", "failed", "not_run"] = (
        validation_model.status if validation_model is not None else "not_run"
    )
    outcome_status: Literal["passed", "failed", "not_assessable"] = (
        validation_model.status if validation_model is not None else "not_assessable"
    )

    integrity_stop = None
    spec_ledger_alignment = None
    if ledger_model is not None:
        integrity_stop = ledger_model.stop_reason == "integrity_failure" or any(
            trial.decision == "abort" for trial in ledger_model.trials
        )
        spec_ledger_alignment = ledger_model.spec_sha256 == spec_model.spec_sha256
    spec_validation_alignment = (
        validation_model.spec_sha256 == spec_model.spec_sha256 if validation_model is not None else None
    )
    candidate_intact = validation_model.candidate_intact if validation_model is not None else None
    protected_intact = validation_model.protected_files_intact if validation_model is not None else None
    hard_reasons: list[str] = []
    if integrity_stop:
        hard_reasons.append("integrity_stop_triggered")
    if candidate_intact is False:
        hard_reasons.append("candidate_no_longer_matches_ledger")
    if protected_intact is False:
        hard_reasons.append("protected_or_non_editable_files_changed")
    hard_violation = bool(hard_reasons)
    compliance_status: Literal["verified", "violated", "partial"]
    if hard_violation:
        compliance_status = "violated"
    elif integrity == "verified" and validation_model is not None:
        compliance_status = "verified"
    else:
        compliance_status = "partial"

    run_facts = _run_facts(result)
    result_model = result.get("model", {}) if isinstance(result, dict) else {}
    result_search = result.get("search", {}) if isinstance(result, dict) else {}
    usage = ledger_model.model_usage if ledger_model is not None else None
    if events:
        event_facts = _event_facts(events)
        process_status: Literal["complete", "partial"] = "complete"
        event_count: int | None = len(events)
        sequence_verified: bool | None = True
        finish_event_present: bool | None = events[-1].event_type == "finish"
        rollback_count: int | None = event_facts["event_type_counts"].get("rollback", 0)
    else:
        event_facts = {
            "event_type_counts": {},
            "event_status_counts": {},
            "decision_counts": {},
            "baseline_completed": None,
        }
        process_status = "partial"
        event_count = None
        sequence_verified = None
        finish_event_present = None
        rollback_count = None

    evidence = AssessmentEvidence(
        trajectory_source=trajectory_source,
        integrity=integrity,
        spec_sha256=spec_model.spec_sha256,
        trajectory_sha256=trajectory_sha256,
        last_event_sha256=last_event_sha256,
        ledger_sha256=evidence_sha256(ledger_payload) if ledger_payload is not None else None,
        validation_sha256=evidence_sha256(validation_payload) if validation_payload is not None else None,
        failure_sha256=evidence_sha256(failure) if failure is not None else None,
        run_facts_sha256=evidence_sha256(run_facts) if run_facts is not None else None,
        source_bindings_verified=source_bindings_verified,
    )
    outcome = OutcomeFacts(
        status=outcome_status,
        terminal_status=terminal_status,
        metric_key=ledger_model.metric_key if ledger_model is not None else spec_model.metric_key,
        direction=ledger_model.direction if ledger_model is not None else spec_model.direction,
        baseline_score=baseline_score,
        best_score=best_score,
        directional_improvement=directional_improvement,
        validation_status=validation_status,
        validation_mode=validation_model.validation_mode if validation_model is not None else None,
        validation_baseline_score=_finite_optional(validation_model.baseline_score, "validation baseline score")
        if validation_model is not None
        else None,
        validation_observed_score=_finite_optional(validation_model.observed_score, "validation observed score")
        if validation_model is not None
        else None,
        acceptance_rule=validation_model.acceptance_rule if validation_model is not None else None,
        acceptance_delta=_finite_optional(validation_model.acceptance_delta, "validation acceptance delta")
        if validation_model is not None
        else None,
        acceptance_target_score=_finite_optional(
            validation_model.acceptance_target_score,
            "validation acceptance target",
        )
        if validation_model is not None
        else None,
        score_matches=validation_model.score_matches if validation_model is not None else None,
        validation_passed_runs=validation_model.passed_runs if validation_model is not None else None,
        validation_failed_runs=validation_model.failed_runs if validation_model is not None else None,
    )
    compliance = ComplianceFacts(
        status=compliance_status,
        hard_violation=hard_violation,
        hard_violation_reasons=hard_reasons,
        trajectory_chain_verified=True if integrity == "verified" else None,
        terminal_evidence_bindings_verified=source_bindings_verified,
        spec_ledger_alignment=spec_ledger_alignment,
        spec_validation_alignment=spec_validation_alignment,
        candidate_intact=candidate_intact,
        protected_files_intact=protected_intact,
        integrity_stop_triggered=integrity_stop,
    )
    process = ProcessFacts(
        status=process_status,
        event_count=event_count,
        sequence_verified=sequence_verified,
        finish_event_present=finish_event_present,
        baseline_completed=event_facts["baseline_completed"],
        event_type_counts=event_facts["event_type_counts"],
        event_status_counts=event_facts["event_status_counts"],
        decision_counts=event_facts["decision_counts"],
        rollback_count=rollback_count,
        completed_trials=_nonnegative_int_optional(ledger_model.completed_trials, "completed trials")
        if ledger_model is not None
        else None,
        accepted_trials=_nonnegative_int_optional(ledger_model.accepted_trials, "accepted trials")
        if ledger_model is not None
        else None,
        max_trials=_nonnegative_int_optional(
            ledger_model.max_trials if ledger_model is not None else spec_model.max_trials,
            "maximum trials",
        ),
        command_runs=_nonnegative_int_optional(ledger_model.command_runs, "command runs")
        if ledger_model is not None
        else None,
        command_duration_ms=_nonnegative_int_optional(ledger_model.command_duration_ms, "command duration")
        if ledger_model is not None
        else None,
        stop_reason=ledger_model.stop_reason if ledger_model is not None else None,
        request_cap=_nonnegative_int_optional(result_search.get("request_cap"), "request cap"),
        attempted_requests=_nonnegative_int_optional(
            result_model.get("attempted_request_count"),
            "attempted requests",
        ),
        completed_responses=_nonnegative_int_optional(result_model.get("request_count"), "completed responses")
        if result_model.get("request_count") is not None
        else usage.request_count
        if usage is not None
        else None,
        usage_reports=_nonnegative_int_optional(result_model.get("reported_request_count"), "usage reports")
        if result_model.get("reported_request_count") is not None
        else usage.reported_request_count
        if usage is not None
        else None,
        reported_tokens=_nonnegative_int_optional(result_model.get("total_tokens"), "reported tokens")
        if result_model.get("total_tokens") is not None
        else usage.total_tokens
        if usage is not None
        else None,
    )
    return RunAssessment(evidence=evidence, outcome=outcome, compliance=compliance, process=process)


def write_assessment_atomic(path: Path, assessment: RunAssessment) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}-{os.getpid()}.tmp"
    try:
        temporary.write_text(
            json.dumps(assessment.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
