from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import PlanGraph  # noqa: E402
from app.plan_assessment import build_plan_assessment  # noqa: E402


ARTIFACT_FILES = {
    "research_spec": "frozen-spec.json",
    "research_trial_ledger": "trial-ledger.json",
    "research_validation_report": "validation-report.json",
    "research_trajectory_jsonl": "trajectory.jsonl",
    "research_trajectory_manifest": "trajectory-manifest.json",
}


def artifact_value(plan: PlanGraph, key: str) -> Any:
    artifact = plan.artifacts.get(key)
    if isinstance(artifact, dict) and "value" in artifact:
        return artifact["value"]
    return artifact


def json_object(value: Any, label: str) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return value


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_plan_store(path: Path, plan_id: str) -> tuple[PlanGraph, list[dict[str, Any]]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    plans = payload.get("plans")
    if not isinstance(plans, dict) or plan_id not in plans:
        raise ValueError(f"plan not found in store: {plan_id}")
    events = payload.get("events", {}).get(plan_id, [])
    if not isinstance(events, list) or any(not isinstance(item, dict) for item in events):
        raise ValueError("plan events are malformed")
    return PlanGraph.model_validate(plans[plan_id]), events


def build_summary(plan: PlanGraph, events: list[dict[str, Any]], assessment: dict[str, Any]) -> dict[str, Any]:
    spec = json_object(artifact_value(plan, "research_spec"), "research_spec")
    ledger = json_object(artifact_value(plan, "research_trial_ledger"), "research_trial_ledger")
    validation = json_object(artifact_value(plan, "research_validation_report"), "research_validation_report")
    cleanup_value = artifact_value(plan, "runtime_cleanup_report")
    cleanup = json_object(cleanup_value, "runtime_cleanup_report") if cleanup_value is not None else None
    cleanup_summary = None
    if cleanup is not None:
        deleted = cleanup.get("deleted") if isinstance(cleanup.get("deleted"), list) else []
        failures = cleanup.get("failures") if isinstance(cleanup.get("failures"), list) else []
        cleanup_summary = {
            "status": cleanup.get("status"),
            "requested": cleanup.get("requested"),
            "deleted_count": len(deleted),
            "failure_count": len(failures),
        }
    event_counts = Counter(str(event.get("event_type") or "unknown") for event in events)
    return {
        "version": "repropilot.product-assessment-evidence/v1",
        "plan": {
            "id": plan.id,
            "status": plan.status,
            "intent_type": plan.intent_type,
            "created_at": plan.created_at.isoformat(),
            "updated_at": plan.updated_at.isoformat(),
            "nodes": [
                {
                    "type": node.type,
                    "assigned_to": node.assigned_to,
                    "status": node.status,
                    "run_count": node.run_count,
                }
                for node in plan.nodes
            ],
        },
        "target": {
            "repository_url": artifact_value(plan, "repo_url"),
            "repository_revision": spec.get("repository_revision"),
            "spec_sha256": spec.get("spec_sha256"),
        },
        "search": {
            "metric_key": ledger.get("metric_key"),
            "aggregation": spec.get("search_aggregation"),
            "runs_per_measurement": spec.get("search_runs"),
            "baseline_score": ledger.get("baseline_score"),
            "best_score": ledger.get("best_score"),
            "completed_trials": ledger.get("completed_trials"),
            "accepted_trials": ledger.get("accepted_trials"),
            "stop_reason": ledger.get("stop_reason"),
        },
        "validation": {
            "status": validation.get("status"),
            "mode": validation.get("validation_mode"),
            "observed_scores": validation.get("observed_scores"),
            "candidate_intact": validation.get("candidate_intact"),
            "protected_files_intact": validation.get("protected_files_intact"),
        },
        "assessment": {
            "trajectory_source": assessment["evidence"]["trajectory_source"],
            "integrity": assessment["evidence"]["integrity"],
            "outcome": assessment["outcome"]["status"],
            "compliance": assessment["compliance"]["status"],
            "process": assessment["process"]["status"],
            "composite_score": assessment["scoring"]["composite_score"],
        },
        "model_usage": ledger.get("model_usage", {}),
        "execution": {
            "event_count": len(events),
            "event_type_counts": dict(sorted(event_counts.items())),
            "runtime_cleanup": cleanup_summary,
        },
        "evidence_boundary": (
            "One bounded product-chain run proving deterministic execution, evidence binding, "
            "and assessment generation; not a general success rate, production SLA, or model ranking."
        ),
    }


def export_evidence(plan_store: Path, plan_id: str, output: Path) -> dict[str, str]:
    plan_store = plan_store.resolve(strict=True)
    output = output.resolve()
    if output.exists():
        raise ValueError(f"refusing to overwrite evidence output: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    plan, events = load_plan_store(plan_store, plan_id)
    assessment_model = build_plan_assessment(plan)
    assessment = assessment_model.model_dump(mode="json")
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=output.parent))
    moved = False
    try:
        for artifact_key, filename in ARTIFACT_FILES.items():
            value = artifact_value(plan, artifact_key)
            if value is None:
                raise ValueError(f"required product evidence is missing: {artifact_key}")
            destination = temporary / filename
            if filename.endswith(".jsonl"):
                if not isinstance(value, str):
                    raise ValueError(f"{artifact_key} must contain text")
                destination.write_text(value, encoding="utf-8", newline="\n")
            else:
                write_json(destination, json_object(value, artifact_key))
        write_json(temporary / "assessment.json", assessment)
        write_json(temporary / "plan-summary.json", build_summary(plan, events, assessment))
        evidence_files = sorted(temporary.iterdir(), key=lambda path: path.name)
        checksums = {path.name: sha256_file(path) for path in evidence_files}
        write_json(temporary / "checksums.json", checksums)
        os.replace(temporary, output)
        moved = True
        return checksums
    finally:
        if not moved and temporary.exists():
            shutil.rmtree(temporary)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export a verified, path-sanitized product Assessment evidence bundle.")
    parser.add_argument("--plan-store", type=Path, required=True)
    parser.add_argument("--plan-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        checksums = export_evidence(args.plan_store, args.plan_id, args.output)
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 1
    print(
        json.dumps(
            {
                "status": "exported",
                "output": str(args.output.resolve()),
                "files": sorted([*checksums, "checksums.json"]),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
