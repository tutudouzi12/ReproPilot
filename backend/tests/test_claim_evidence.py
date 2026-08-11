from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.claim_evidence import (
    ClaimCriterion,
    ClaimRubric,
    PaperClaim,
    build_evidence_graph,
    normalize_rubric,
    rubric_sha256,
    validate_frozen_rubric,
    EVIDENCE_KEYS,
)


def sample_rubric():
    return normalize_rubric(ClaimRubric(
        paper_title="Tiny Reproduction Study",
        claims=[PaperClaim(
            title="Accuracy claim",
            statement="The method reaches 80 percent accuracy.",
            source_locator="Table 1",
            claim_type="quantitative",
            importance=0.9,
            criteria=[ClaimCriterion(
                description="Evaluate accuracy using the paper protocol.",
                metric_name="accuracy",
                expected_value=0.8,
                tolerance=0.01,
                unit="ratio",
                required_evidence=["paper", "run", "metric"],
            )],
        )],
    ))


def test_rubric_freezes_stable_ids_and_hash():
    rubric = sample_rubric()
    assert rubric.version == "claim.rubric/v1"
    assert rubric.claims[0].id == "claim-001"
    assert rubric.claims[0].criteria[0].id == "claim-001.criterion-01"
    assert rubric.sha256 == rubric_sha256(rubric)
    assert validate_frozen_rubric(rubric).sha256 == rubric.sha256


def test_verified_claim_requires_execution_evidence():
    rubric = sample_rubric()
    proposal = {"findings": [{
        "claim_id": "claim-001",
        "criterion_id": "claim-001.criterion-01",
        "status": "verified",
        "confidence": 0.95,
        "observed_value": "repository documents the metric",
        "evidence_keys": ["repo_manifest"],
        "reason": "The repository describes an accuracy target.",
    }]}
    graph = build_evidence_graph(rubric, proposal, {"repo_manifest": '{"entrypoint":"train.py"}'})
    verdict = graph.claims[0].criteria[0]
    assert verdict.status == "unverifiable"
    assert verdict.confidence <= 0.25
    assert graph.claims[0].title
    assert verdict.description


def test_incomplete_adjudication_degrades_all_findings():
    rubric = sample_rubric()
    rubric.claims[0].criteria.append(ClaimCriterion(
        id="claim-001.criterion-02",
        description="Run a second independently gradable check.",
        required_evidence=["run"],
    ))
    rubric.sha256 = rubric_sha256(rubric)
    proposal = {"findings": [{
        "claim_id": "claim-001",
        "criterion_id": "claim-001.criterion-01",
        "status": "verified",
        "confidence": 0.9,
        "evidence_keys": ["run_metrics"],
        "reason": "The measured accuracy matches.",
    }]}
    graph = build_evidence_graph(rubric, proposal, {"run_metrics": '{"accuracy":0.8}'})
    assert graph.status == "degraded"
    assert graph.summary.unverifiable == 1
    assert all(item.status == "unverifiable" for item in graph.claims[0].criteria)


def test_rehashed_noncanonical_rubric_is_rejected():
    rubric = sample_rubric()
    rubric.claims[0].criteria[0].id = "criterion-forged"
    rubric.sha256 = rubric_sha256(rubric)
    with pytest.raises(ValueError, match="canonical"):
        validate_frozen_rubric(rubric)


def test_claim_evidence_golden_fixture_matches_runtime_contract():
    fixture_root = Path(__file__).resolve().parents[2] / "test" / "claim-evidence"
    scenario = json.loads((fixture_root / "scenario.json").read_text(encoding="utf-8"))
    expected = json.loads((fixture_root / "expected_graph.json").read_text(encoding="utf-8"))
    rubric = normalize_rubric(ClaimRubric.model_validate({
        "paper_title": scenario["paper_title"],
        "claims": scenario["rubric_response"]["claims"],
    }))
    artifacts = {key: str(scenario.get(key, "")) for key in EVIDENCE_KEYS}
    graph = build_evidence_graph(rubric, scenario["evidence_response"], artifacts)

    def omit_empty(value):
        if isinstance(value, list):
            return [omit_empty(item) for item in value]
        if isinstance(value, dict):
            return {
                key: omit_empty(item)
                for key, item in value.items()
                if item not in ("", None)
            }
        return value

    assert omit_empty(graph.model_dump(mode="json")) == omit_empty(expected)
