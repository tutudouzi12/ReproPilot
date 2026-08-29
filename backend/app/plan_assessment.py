from __future__ import annotations

import json
from typing import Any

from .models import PlanGraph
from .run_assessment import RunAssessment, build_assessment


ASSESSMENT_STATUS_VERSION = "autoresearch.assessment-status/v1"


class AssessmentUnavailable(ValueError):
    pass


def _artifact_value(plan: PlanGraph, key: str) -> Any:
    artifact = plan.artifacts.get(key)
    if isinstance(artifact, dict) and "value" in artifact:
        return artifact["value"]
    return artifact


def _json_object(value: Any, label: str) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{label} artifact is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} artifact must contain a JSON object")
    return value


def build_plan_assessment(plan: PlanGraph) -> RunAssessment:
    """Rebuild a plan assessment from source artifacts instead of trusting a cached summary."""

    spec = _json_object(_artifact_value(plan, "research_spec"), "research_spec")
    if spec is None:
        raise AssessmentUnavailable("frozen research spec is not available")
    ledger = _json_object(_artifact_value(plan, "research_trial_ledger"), "research_trial_ledger")
    validation = _json_object(_artifact_value(plan, "research_validation_report"), "research_validation_report")
    if ledger is None and validation is None:
        raise AssessmentUnavailable("trial ledger and validation report are not available")

    trajectory_jsonl = _artifact_value(plan, "research_trajectory_jsonl")
    trajectory_manifest = _artifact_value(plan, "research_trajectory_manifest")
    if (trajectory_jsonl is None) != (trajectory_manifest is None):
        raise ValueError("native trajectory evidence is incomplete")
    if trajectory_jsonl is not None and not isinstance(trajectory_jsonl, str):
        raise ValueError("research_trajectory_jsonl artifact must contain text")

    assessment = build_assessment(
        spec=spec,
        ledger=ledger,
        validation=validation,
        trajectory_jsonl=trajectory_jsonl,
        trajectory_manifest=trajectory_manifest,
    )
    cached = _json_object(_artifact_value(plan, "research_assessment"), "research_assessment")
    if cached is not None:
        cached_assessment = RunAssessment.model_validate(cached)
        if cached_assessment.model_dump(mode="json") != assessment.model_dump(mode="json"):
            raise ValueError("persisted assessment does not match its source evidence")
    return assessment


def assessment_state(plan: PlanGraph) -> dict[str, Any]:
    validation_task = next((node for node in plan.nodes if node.type == "autoresearch_validate"), None)
    if validation_task is not None and validation_task.structured_data and _artifact_value(plan, "research_assessment") is None:
        try:
            task_status = json.loads(validation_task.structured_data)
        except json.JSONDecodeError:
            task_status = None
        if isinstance(task_status, dict) and task_status.get("version") == ASSESSMENT_STATUS_VERSION:
            return {
                "version": ASSESSMENT_STATUS_VERSION,
                "status": "blocked",
                "assessment": None,
                "reason": str(task_status.get("reason") or "assessment generation was blocked")[:1000],
            }
    try:
        assessment = build_plan_assessment(plan)
    except AssessmentUnavailable as exc:
        return {
            "version": ASSESSMENT_STATUS_VERSION,
            "status": "unavailable",
            "assessment": None,
            "reason": str(exc)[:1000],
        }
    except (TypeError, ValueError) as exc:
        return {
            "version": ASSESSMENT_STATUS_VERSION,
            "status": "blocked",
            "assessment": None,
            "reason": str(exc)[:1000],
        }
    return {
        "version": ASSESSMENT_STATUS_VERSION,
        "status": "available",
        "assessment": assessment.model_dump(mode="json"),
        "reason": None,
    }
