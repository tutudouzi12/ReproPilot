from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from app.autoresearch import ModelUsage, ResearchSpec, TrialLedger, ValidationReport, canonical_sha256
from app.models import PlanGraph, TaskNode
from app.plan_assessment import assessment_state, build_plan_assessment
from app.run_assessment import ASSESSMENT_METHOD, ASSESSMENT_VERSION, build_assessment
from app.scheduler import build_artifact
from app.trajectory import TrajectoryRecorder, finalize_trajectory


def fixed_clock() -> datetime:
    return datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)


def frozen_spec() -> ResearchSpec:
    spec = ResearchSpec(
        name="assessment-fixture",
        objective="Improve the frozen metric without changing protected evidence.",
        repository_revision="a" * 40,
        editable_files=["candidate.py"],
        protected_files=["evaluator.py", "holdout.py"],
        eval_command=["python", "evaluator.py"],
        holdout_command=["python", "holdout.py"],
        guard_commands=[["python", "-m", "py_compile", "candidate.py"]],
        metric_key="metrics.score",
        direction="maximize",
        min_delta=0.1,
        holdout_min_delta=0.1,
        target_score=1.0,
        max_trials=3,
        validation_runs=3,
        frozen_files={"evaluator.py": "b" * 64, "holdout.py": "c" * 64},
        frozen_workspace_sha256="d" * 64,
    )
    payload = spec.model_dump(mode="json")
    payload["spec_sha256"] = ""
    spec.spec_sha256 = canonical_sha256(payload)
    return spec


def completed_ledger(spec: ResearchSpec) -> TrialLedger:
    return TrialLedger(
        spec_sha256=spec.spec_sha256,
        status="completed",
        metric_key=spec.metric_key,
        direction=spec.direction,
        baseline_score=0.5,
        best_score=1.0,
        holdout_baseline_score=0.4,
        max_trials=spec.max_trials,
        completed_trials=1,
        accepted_trials=1,
        stop_reason="target_score_reached",
        command_runs=5,
        command_duration_ms=1250,
        model_usage=ModelUsage(
            provider="provider.example",
            model="model-name",
            request_count=1,
            reported_request_count=1,
            prompt_tokens=80,
            completion_tokens=20,
            total_tokens=100,
        ),
    )


def validation_report(spec: ResearchSpec, *, protected_files_intact: bool = True) -> ValidationReport:
    return ValidationReport(
        spec_sha256=spec.spec_sha256,
        status="passed",
        validation_mode="hidden_holdout",
        expected_score=0.4,
        baseline_score=0.4,
        acceptance_rule="minimum_improvement",
        acceptance_delta=0.1,
        acceptance_target_score=0.5,
        observed_scores=[1.0, 1.0, 1.0],
        observed_score=1.0,
        mean_score=1.0,
        stddev=0.0,
        passed_runs=3,
        failed_runs=0,
        score_matches=True,
        candidate_intact=True,
        protected_files_intact=protected_files_intact,
    )


def native_trajectory(spec: ResearchSpec, ledger: TrialLedger, validation: ValidationReport):
    recorder = TrajectoryRecorder(clock=fixed_clock)
    recorder.emit("baseline", {"status": "started", "spec_sha256": spec.spec_sha256})
    recorder.emit("baseline", {"status": "completed", "score": 0.5, "spec_sha256": spec.spec_sha256})
    recorder.emit("proposal", {"trial": 1, "status": "candidate", "patch_count": 1})
    recorder.emit("apply_patch", {"trial": 1, "status": "applied", "patch_count": 1})
    recorder.emit("guard", {"trial": 1, "run": 1, "status": "passed", "exit_code": 0})
    recorder.emit("public_evaluation", {"trial": 1, "run": 1, "status": "passed", "score": 1.0})
    recorder.emit("decision", {"trial": 1, "decision": "keep", "status": "kept", "score": 1.0})
    recorder.emit(
        "hidden_validation",
        {
            "phase": "validation_summary",
            "status": "passed",
            "candidate_intact": True,
            "protected_files_intact": validation.protected_files_intact,
        },
    )
    manifest = finalize_trajectory(
        recorder,
        spec_sha256=spec.spec_sha256,
        ledger=ledger,
        validation=validation,
        terminal_status="passed",
    )
    return recorder, manifest


def run_result() -> dict:
    return {
        "outcome": "validation_passed",
        "search": {"request_cap": 3, "baseline_score": 0.5, "best_score": 1.0},
        "model": {
            "attempted_request_count": 1,
            "request_count": 1,
            "reported_request_count": 1,
            "total_tokens": 100,
        },
        "validation": {"status": "passed", "observed_score": 1.0},
        "failure": None,
    }


def test_native_assessment_retains_raw_dimension_facts_without_composite_score() -> None:
    spec = frozen_spec()
    ledger = completed_ledger(spec)
    validation = validation_report(spec)
    recorder, manifest = native_trajectory(spec, ledger, validation)

    assessment = build_assessment(
        spec=spec,
        ledger=ledger,
        validation=validation,
        trajectory_jsonl=recorder.jsonl(),
        trajectory_manifest=manifest,
        result=run_result(),
    )

    assert assessment.version == ASSESSMENT_VERSION
    assert assessment.method == ASSESSMENT_METHOD
    assert assessment.evidence.trajectory_source == "native_hash_linked"
    assert assessment.evidence.integrity == "verified"
    assert assessment.evidence.source_bindings_verified is True
    assert assessment.outcome.status == "passed"
    assert assessment.outcome.directional_improvement == 0.5
    assert assessment.outcome.validation_observed_score == 1.0
    assert assessment.compliance.status == "verified"
    assert assessment.compliance.hard_violation is False
    assert assessment.process.status == "complete"
    assert assessment.process.event_type_counts["finish"] == 1
    assert assessment.process.decision_counts == {"keep": 1}
    assert assessment.process.rollback_count == 0
    assert assessment.process.attempted_requests == 1
    assert assessment.scoring.status == "not_calculated"
    assert assessment.scoring.composite_score is None


def test_hard_compliance_violation_is_not_offset_by_passed_outcome() -> None:
    spec = frozen_spec()
    ledger = completed_ledger(spec)
    validation = validation_report(spec, protected_files_intact=False)
    recorder, manifest = native_trajectory(spec, ledger, validation)

    assessment = build_assessment(
        spec=spec,
        ledger=ledger,
        validation=validation,
        trajectory_jsonl=recorder.jsonl(),
        trajectory_manifest=manifest,
        result=run_result(),
    )

    assert assessment.outcome.status == "passed"
    assert assessment.compliance.status == "violated"
    assert assessment.compliance.hard_violation is True
    assert assessment.compliance.hard_violation_reasons == ["protected_or_non_editable_files_changed"]
    assert assessment.scoring.status == "not_calculated"


def test_corrupted_native_trajectory_cannot_produce_an_assessment() -> None:
    spec = frozen_spec()
    ledger = completed_ledger(spec)
    validation = validation_report(spec)
    recorder, manifest = native_trajectory(spec, ledger, validation)
    lines = recorder.jsonl().splitlines()
    changed = json.loads(lines[5])
    changed["payload"]["score"] = 999
    lines[5] = json.dumps(changed, sort_keys=True, separators=(",", ":"))

    with pytest.raises(ValueError, match="trajectory"):
        build_assessment(
            spec=spec,
            ledger=ledger,
            validation=validation,
            trajectory_jsonl="\n".join(lines) + "\n",
            trajectory_manifest=manifest,
            result=run_result(),
        )


def test_legacy_assessment_is_explicitly_partial_and_does_not_invent_events() -> None:
    spec = frozen_spec()
    ledger = completed_ledger(spec)
    validation = validation_report(spec)

    assessment = build_assessment(
        spec=spec,
        ledger=ledger,
        validation=validation,
        result=run_result(),
    )

    assert assessment.evidence.trajectory_source == "derived_from_ledger"
    assert assessment.evidence.integrity == "partial"
    assert assessment.evidence.trajectory_sha256 is None
    assert assessment.evidence.source_bindings_verified is None
    assert assessment.compliance.status == "partial"
    assert assessment.compliance.trajectory_chain_verified is None
    assert assessment.process.status == "partial"
    assert assessment.process.event_count is None
    assert assessment.process.event_type_counts == {}
    assert assessment.process.decision_counts == {}
    assert assessment.process.rollback_count is None


def test_assessment_rejects_ledger_or_manifest_evidence_mismatch() -> None:
    spec = frozen_spec()
    ledger = completed_ledger(spec)
    validation = validation_report(spec)
    recorder, manifest = native_trajectory(spec, ledger, validation)
    changed_ledger = ledger.model_copy(update={"best_score": 0.9})

    with pytest.raises(ValueError, match="ledger hash mismatch"):
        build_assessment(
            spec=spec,
            ledger=changed_ledger,
            validation=validation,
            trajectory_jsonl=recorder.jsonl(),
            trajectory_manifest=manifest,
            result=run_result(),
        )


@pytest.mark.parametrize("invalid_count", [True, -1, 1.5, "1"])
def test_assessment_rejects_non_integer_or_negative_run_counters(invalid_count: object) -> None:
    spec = frozen_spec()
    ledger = completed_ledger(spec)
    validation = validation_report(spec)
    recorder, manifest = native_trajectory(spec, ledger, validation)
    result = run_result()
    result["model"]["attempted_request_count"] = invalid_count

    with pytest.raises(ValueError, match="attempted requests must be a non-negative integer"):
        build_assessment(
            spec=spec,
            ledger=ledger,
            validation=validation,
            trajectory_jsonl=recorder.jsonl(),
            trajectory_manifest=manifest,
            result=result,
        )


def plan_with_assessment_sources(
    spec: ResearchSpec,
    ledger: TrialLedger,
    validation: ValidationReport,
    *,
    include_trajectory: bool,
) -> PlanGraph:
    plan = PlanGraph(
        user_intent="assess the completed run",
        intent_type="AutoResearch",
        nodes=[TaskNode(name="validate", type="autoresearch_validate", description="validate", assigned_to="research_coding_agent")],
        edges=[],
    )
    values: dict[str, object] = {
        "research_spec": spec.model_dump_json(),
        "research_trial_ledger": ledger.model_dump_json(),
        "research_validation_report": validation.model_dump_json(),
    }
    if include_trajectory:
        recorder, manifest = native_trajectory(spec, ledger, validation)
        values["research_trajectory_jsonl"] = recorder.jsonl()
        values["research_trajectory_manifest"] = manifest.model_dump_json()
    for key, value in values.items():
        plan.artifacts[key] = build_artifact(key, plan.nodes[0].id, value)
    return plan


def test_plan_assessment_rebuilds_native_sources_and_rejects_cached_drift() -> None:
    spec = frozen_spec()
    ledger = completed_ledger(spec)
    validation = validation_report(spec)
    plan = plan_with_assessment_sources(spec, ledger, validation, include_trajectory=True)
    assessment = build_plan_assessment(plan)
    plan.artifacts["research_assessment"] = build_artifact(
        "research_assessment",
        plan.nodes[0].id,
        assessment.model_dump_json(),
    )

    assert assessment_state(plan)["assessment"]["evidence"]["integrity"] == "verified"

    changed = assessment.model_copy(deep=True)
    changed.outcome.best_score = 999
    plan.artifacts["research_assessment"]["value"] = changed.model_dump_json()
    blocked = assessment_state(plan)
    assert blocked["status"] == "blocked"
    assert blocked["assessment"] is None
    assert "does not match" in blocked["reason"]


def test_plan_assessment_marks_legacy_sources_partial() -> None:
    spec = frozen_spec()
    plan = plan_with_assessment_sources(spec, completed_ledger(spec), validation_report(spec), include_trajectory=False)

    state = assessment_state(plan)

    assert state["status"] == "available"
    assert state["assessment"]["evidence"]["trajectory_source"] == "derived_from_ledger"
    assert state["assessment"]["evidence"]["integrity"] == "partial"
    assert state["assessment"]["process"]["status"] == "partial"


def test_plan_assessment_blocks_tampered_native_trajectory() -> None:
    spec = frozen_spec()
    plan = plan_with_assessment_sources(spec, completed_ledger(spec), validation_report(spec), include_trajectory=True)
    trajectory = str(plan.artifacts["research_trajectory_jsonl"]["value"])
    plan.artifacts["research_trajectory_jsonl"]["value"] = trajectory.replace('"score":1.0', '"score":999.0', 1)

    state = assessment_state(plan)

    assert state["status"] == "blocked"
    assert state["assessment"] is None
    assert "trajectory" in state["reason"]


def test_blocked_validation_cannot_be_downgraded_to_legacy_partial() -> None:
    spec = frozen_spec()
    plan = plan_with_assessment_sources(spec, completed_ledger(spec), validation_report(spec), include_trajectory=False)
    plan.artifacts.pop("research_validation_report")
    plan.nodes[0].status = "failed"
    plan.nodes[0].structured_data = json.dumps(
        {
            "version": "autoresearch.assessment-status/v1",
            "status": "blocked",
            "reason": "trajectory event hash mismatch",
        }
    )

    state = assessment_state(plan)

    assert state["status"] == "blocked"
    assert state["assessment"] is None
    assert state["reason"] == "trajectory event hash mismatch"
