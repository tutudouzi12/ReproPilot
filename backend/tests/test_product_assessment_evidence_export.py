from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import PlanGraph, TaskNode  # noqa: E402


SCRIPT = ROOT / "scripts" / "export_product_assessment_evidence.py"
SPEC = importlib.util.spec_from_file_location("product_assessment_evidence_export", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
evidence_export = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(evidence_export)

SOURCE = (
    ROOT
    / "examples"
    / "autoresearch"
    / "minimal"
    / "results"
    / "2026-08-29-product-assessment-e2e"
)


def load_json(name: str) -> dict:
    return json.loads((SOURCE / name).read_text(encoding="utf-8"))


def artifact(value: object) -> dict[str, object]:
    return {"value": value}


def test_export_rebuilds_assessment_and_binds_every_output(tmp_path: Path) -> None:
    plan_id = "product-assessment-export-fixture"
    node = TaskNode(
        name="Validate AutoResearch result",
        type="autoresearch_validate",
        description="Rebuild verified evidence",
        assigned_to="research_coding_agent",
        status="completed",
        run_count=1,
    )
    plan = PlanGraph(
        id=plan_id,
        user_intent="Export a bounded product Assessment run",
        intent_type="AutoResearch",
        status="completed",
        nodes=[node],
        edges=[],
        artifacts={
            "repo_url": artifact("https://github.com/tutudouzi12/ReproPilot"),
            "research_spec": artifact(load_json("frozen-spec.json")),
            "research_trial_ledger": artifact(load_json("trial-ledger.json")),
            "research_validation_report": artifact(load_json("validation-report.json")),
            "research_trajectory_jsonl": artifact((SOURCE / "trajectory.jsonl").read_text(encoding="utf-8")),
            "research_trajectory_manifest": artifact(load_json("trajectory-manifest.json")),
            "research_assessment": artifact(load_json("assessment.json")),
        },
    )
    plan_store = tmp_path / "plans.json"
    plan_store.write_text(
        json.dumps(
            {
                "plans": {plan_id: plan.model_dump(mode="json", by_alias=True)},
                "events": {plan_id: [{"event_type": "task_completed"}]},
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "evidence"

    checksums = evidence_export.export_evidence(plan_store, plan_id, output)

    assert set(checksums) == {
        "assessment.json",
        "frozen-spec.json",
        "plan-summary.json",
        "trajectory-manifest.json",
        "trajectory.jsonl",
        "trial-ledger.json",
        "validation-report.json",
    }
    for name, expected in checksums.items():
        assert hashlib.sha256((output / name).read_bytes()).hexdigest() == expected
    assert json.loads((output / "checksums.json").read_text(encoding="utf-8")) == checksums
    assert load_json("assessment.json") == json.loads((output / "assessment.json").read_text(encoding="utf-8"))
    summary = json.loads((output / "plan-summary.json").read_text(encoding="utf-8"))
    assert summary["assessment"] == {
        "trajectory_source": "native_hash_linked",
        "integrity": "verified",
        "outcome": "passed",
        "compliance": "verified",
        "process": "complete",
        "composite_score": None,
    }

    with pytest.raises(ValueError, match="refusing to overwrite"):
        evidence_export.export_evidence(plan_store, plan_id, output)
