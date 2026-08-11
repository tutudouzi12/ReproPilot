from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, Field

from .plotting import validate_plot_base64


RUBRIC_VERSION = "claim.rubric/v1"
GRAPH_VERSION = "claim.evidence/v1"
STATUS = Literal["verified", "partially_reproduced", "contradicted", "unverifiable", "blocked_by_missing_asset"]
EVIDENCE_KEYS = [
    "parsed_paper", "repo_manifest", "reproduction_mode_report", "dependency_install_report",
    "run_metrics", "paper_debug_report", "paper_patch_manifest", "comparison_report",
    "rerun_metrics", "rerun_report", "gap_debug_report", "gap_patch_manifest", "result_plot",
]
EXECUTION_EVIDENCE = {"run_metrics", "paper_debug_report", "comparison_report", "rerun_metrics", "rerun_report", "gap_debug_report", "result_plot"}


class ClaimCriterion(BaseModel):
    id: str = ""
    description: str
    metric_name: str = ""
    expected_value: float | None = None
    tolerance: float | None = None
    unit: str = ""
    required_evidence: list[str] = Field(default_factory=list)


class PaperClaim(BaseModel):
    id: str = ""
    title: str
    statement: str
    source_locator: str = "not specified in parsed artifact"
    claim_type: str = "qualitative"
    importance: float = 0.0
    criteria: list[ClaimCriterion]


class ClaimRubric(BaseModel):
    version: str = RUBRIC_VERSION
    paper_title: str = "Unspecified paper"
    source_artifact: str = "parsed_paper"
    sha256: str = ""
    claims: list[PaperClaim]


class EvidenceNode(BaseModel):
    id: str
    artifact_key: str
    evidence_type: str
    sha256: str = ""
    available: bool
    summary: str = ""


class CriterionVerdict(BaseModel):
    criterion_id: str
    description: str
    status: STATUS
    confidence: float
    observed_value: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    reason: str


class ClaimResult(BaseModel):
    claim_id: str
    title: str
    statement: str
    source_locator: str
    claim_type: str
    status: STATUS
    confidence: float
    criteria: list[CriterionVerdict]


class EvidenceSummary(BaseModel):
    total_claims: int = 0
    total_criteria: int = 0
    verified: int = 0
    partially_reproduced: int = 0
    contradicted: int = 0
    unverifiable: int = 0
    blocked_by_missing_asset: int = 0
    criterion_evidence_coverage: float = 0.0


class ClaimEvidenceGraph(BaseModel):
    version: str = GRAPH_VERSION
    status: str
    status_reason: str = ""
    rubric_sha256: str
    evidence: list[EvidenceNode]
    claims: list[ClaimResult]
    summary: EvidenceSummary


def normalize_rubric(proposed: ClaimRubric) -> ClaimRubric:
    normalized_claims = []
    for raw_claim in proposed.claims[:16]:
        statement = raw_claim.statement.strip()[:2000]
        if not statement:
            continue
        criteria = []
        for raw in raw_claim.criteria[:6]:
            description = raw.description.strip()[:1200]
            if not description:
                continue
            tolerance = raw.tolerance if raw.expected_value is not None and (raw.tolerance is None or raw.tolerance >= 0) else None
            criteria.append(ClaimCriterion(
                description=description,
                metric_name=raw.metric_name.strip()[:160],
                expected_value=raw.expected_value,
                tolerance=tolerance,
                unit=raw.unit.strip()[:80],
                required_evidence=_normalize_required_evidence(raw.required_evidence),
            ))
        if not criteria:
            continue
        claim_id = f"claim-{len(normalized_claims) + 1:03d}"
        for index, criterion in enumerate(criteria, 1):
            criterion.id = f"{claim_id}.criterion-{index:02d}"
        claim_type = raw_claim.claim_type.strip().lower()
        if claim_type not in {"quantitative", "qualitative", "efficiency", "ablation", "robustness"}:
            claim_type = "qualitative"
        normalized_claims.append(PaperClaim(
            id=claim_id,
            title=(raw_claim.title.strip() or statement[:120])[:240],
            statement=statement,
            source_locator=(raw_claim.source_locator.strip() or "not specified in parsed artifact")[:500],
            claim_type=claim_type,
            importance=max(0.0, min(1.0, raw_claim.importance)),
            criteria=criteria,
        ))
    if not normalized_claims:
        raise ValueError("claim rubric contains no valid independently gradable claims")
    rubric = ClaimRubric(
        paper_title=(proposed.paper_title.strip() or "Unspecified paper")[:300],
        claims=normalized_claims,
    )
    rubric.sha256 = rubric_sha256(rubric)
    return rubric


def _normalize_required_evidence(values: list[str]) -> list[str]:
    allowed = {"paper", "repository", "environment", "run", "metric", "patch", "comparison", "figure"}
    result: list[str] = []
    for raw in values:
        value = raw.strip().lower()
        if value in allowed and value not in result:
            result.append(value)
    return result or ["paper", "run", "comparison"]


def rubric_sha256(rubric: ClaimRubric) -> str:
    payload = rubric.model_dump(mode="json")
    payload["sha256"] = ""
    # Preserve the versioned model field order. This keeps the frozen rubric
    # digest stable across services that serialize the same contract.
    canonical = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_frozen_rubric(value: str | dict[str, Any] | ClaimRubric) -> ClaimRubric:
    if isinstance(value, ClaimRubric):
        rubric = value
    elif isinstance(value, str):
        rubric = ClaimRubric.model_validate_json(value)
    else:
        rubric = ClaimRubric.model_validate(value)
    if rubric.version != RUBRIC_VERSION or not rubric.claims:
        raise ValueError("claim rubric version or claims are invalid")
    if not rubric.sha256 or rubric.sha256 != rubric_sha256(rubric):
        raise ValueError("claim rubric SHA-256 mismatch")
    canonical = normalize_rubric(rubric)
    if rubric.model_dump(mode="json") != canonical.model_dump(mode="json"):
        raise ValueError("claim rubric is not in canonical frozen form")
    return rubric


def build_evidence_graph(
    rubric_value: str | dict[str, Any] | ClaimRubric,
    proposal: dict[str, Any],
    artifacts: dict[str, str],
) -> ClaimEvidenceGraph:
    rubric = validate_frozen_rubric(rubric_value)
    evidence = [_evidence_node(key, artifacts.get(key, "")) for key in EVIDENCE_KEYS]
    by_key = {node.artifact_key: node for node in evidence}
    locations = {criterion.id: (claim, criterion) for claim in rubric.claims for criterion in claim.criteria}
    findings = proposal.get("findings", []) if isinstance(proposal, dict) else []
    incomplete = len(findings) != len(locations)
    verdicts: dict[str, CriterionVerdict] = {}
    for raw in findings:
        criterion_id = str(raw.get("criterion_id", "")).strip()
        claim_id = str(raw.get("claim_id", "")).strip()
        if criterion_id not in locations:
            raise ValueError(f"unknown criterion_id {criterion_id!r}")
        claim, criterion = locations[criterion_id]
        if claim_id != claim.id:
            raise ValueError(f"criterion {criterion_id} was assigned to the wrong claim")
        if criterion_id in verdicts:
            raise ValueError(f"duplicate criterion finding {criterion_id}")
        status = str(raw.get("status", "")).strip().lower()
        if status not in {"verified", "partially_reproduced", "contradicted", "unverifiable", "blocked_by_missing_asset"}:
            raise ValueError(f"invalid claim status {status!r}")
        cited_keys = []
        evidence_ids = []
        for key in raw.get("evidence_keys", []):
            key = str(key).strip()
            if key not in by_key:
                raise ValueError(f"criterion {criterion_id} references unknown evidence key {key!r}")
            if by_key[key].available and key not in cited_keys:
                cited_keys.append(key)
                evidence_ids.append(by_key[key].id)
        confidence = max(0.0, min(1.0, float(raw.get("confidence", 0))))
        reason = str(raw.get("reason", "")).strip()[:1600] or "no evidence-based reason was supplied"
        if status in {"verified", "partially_reproduced", "contradicted"} and not any(key in EXECUTION_EVIDENCE for key in cited_keys):
            status = "unverifiable"
            confidence = min(confidence, 0.25)
            reason = "downgraded because no execution-derived evidence was cited; " + reason
        verdicts[criterion_id] = CriterionVerdict(
            criterion_id=criterion_id,
            description=criterion.description,
            status=status,
            confidence=confidence,
            observed_value=str(raw.get("observed_value", "")).strip()[:500],
            evidence_ids=evidence_ids,
            reason=reason,
        )
    results = []
    for claim in rubric.claims:
        criteria = []
        for criterion in claim.criteria:
            verdict = verdicts.get(criterion.id) or CriterionVerdict(
                criterion_id=criterion.id,
                description=criterion.description,
                status="unverifiable",
                confidence=0,
                reason="adjudication did not cover this frozen criterion",
            )
            if incomplete:
                verdict = verdict.model_copy(update={"status": "unverifiable", "confidence": 0.0, "reason": "incomplete adjudication degraded all criterion verdicts"})
            criteria.append(verdict)
        claim_status, confidence = _aggregate(criteria)
        results.append(ClaimResult(
            claim_id=claim.id,
            title=claim.title,
            statement=claim.statement,
            source_locator=claim.source_locator,
            claim_type=claim.claim_type,
            status=claim_status,
            confidence=confidence,
            criteria=criteria,
        ))
    summary = _summary(results)
    return ClaimEvidenceGraph(
        status="degraded" if incomplete else "assessed",
        status_reason=(
            "incomplete adjudication"
            if incomplete
            else "all criterion verdicts were produced and validated against the bounded evidence inventory"
        ),
        rubric_sha256=rubric.sha256,
        evidence=evidence,
        claims=results,
        summary=summary,
    )


def _evidence_node(key: str, value: str) -> EvidenceNode:
    value = value.strip()
    evidence_type = {
        "parsed_paper": "paper", "repo_manifest": "repository", "run_metrics": "metric",
        "rerun_metrics": "metric", "comparison_report": "comparison", "result_plot": "figure",
        "paper_patch_manifest": "patch", "gap_patch_manifest": "patch",
        "reproduction_mode_report": "environment", "dependency_install_report": "environment",
    }.get(key, "run" if "report" in key else "artifact")
    valid_plot = True
    plot_summary = ""
    plot_sha256 = ""
    if key == "result_plot" and value:
        try:
            width, height, digest = validate_plot_base64(value)
            plot_sha256 = digest
            plot_summary = f"validated PNG {width}x{height}, sha256={digest}"
        except ValueError as exc:
            valid_plot = False
            plot_summary = f"invalid plot artifact excluded: {exc}"
    return EvidenceNode(
        id="evidence-" + key.replace("_", "-"),
        artifact_key=key,
        evidence_type=evidence_type,
        sha256=(plot_sha256 if key == "result_plot" else hashlib.sha256(value.encode()).hexdigest()) if value and valid_plot else "",
        available=bool(value) and valid_plot,
        summary=plot_summary if key == "result_plot" and value else (" ".join(value.split())[:500] if value else ""),
    )


def _aggregate(verdicts: list[CriterionVerdict]) -> tuple[STATUS, float]:
    confidence = sum(item.confidence for item in verdicts) / len(verdicts) if verdicts else 0.0
    statuses = [item.status for item in verdicts]
    if "contradicted" in statuses:
        return "contradicted", confidence
    if statuses and all(status == "verified" for status in statuses):
        return "verified", confidence
    if "verified" in statuses or "partially_reproduced" in statuses:
        return "partially_reproduced", confidence
    if "blocked_by_missing_asset" in statuses:
        return "blocked_by_missing_asset", confidence
    return "unverifiable", confidence


def _summary(results: list[ClaimResult]) -> EvidenceSummary:
    summary = EvidenceSummary(total_claims=len(results))
    covered = 0
    for result in results:
        setattr(summary, result.status, getattr(summary, result.status) + 1)
        for criterion in result.criteria:
            summary.total_criteria += 1
            covered += bool(criterion.evidence_ids)
    if summary.total_criteria:
        summary.criterion_evidence_coverage = covered / summary.total_criteria
    return summary
