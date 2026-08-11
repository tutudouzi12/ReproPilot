from __future__ import annotations

import json
import math
from typing import Any

from pydantic import BaseModel, Field


class PaperParseReport(BaseModel):
    version: str = "agent.paper_parse/v1"
    status: str
    paper_title: str = ""
    method_names: list[str] = Field(default_factory=list)
    datasets: list[str] = Field(default_factory=list)
    reported_metrics: dict[str, float] = Field(default_factory=dict)
    claims: list[str] = Field(default_factory=list)
    reproduction_requirements: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    source_mode: str = "model_proposed"
    summary: str = ""


class FrameworkResearchReport(BaseModel):
    version: str = "agent.framework_research/v1"
    status: str
    frameworks: list[str]
    comparison_dimensions: list[str]
    evidence: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    source_mode: str = "model_proposed"


class EvidenceReport(BaseModel):
    version: str = "agent.evidence_report/v1"
    report_type: str
    status: str
    observations: list[str] = Field(default_factory=list)
    inferences: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    metrics: dict[str, float] = Field(default_factory=dict)
    evidence_artifacts: list[str] = Field(default_factory=list)
    recommendation: str = ""
    source_mode: str = "model_proposed"


def offline_paper_parse(user_intent: str) -> PaperParseReport:
    title = "Attention Is All You Need" if "attention is all you need" in user_intent.lower() else ""
    methods = ["Transformer"] if "transformer" in user_intent.lower() or title else []
    return PaperParseReport(
        status="partial",
        paper_title=title,
        method_names=methods,
        source_mode="offline_contract",
        summary="Only user-provided intent was available; paper claims and reported metrics were not inferred.",
        limitations=["No verified paper document or model extraction result was available."],
    )


def offline_framework_research(user_intent: str) -> FrameworkResearchReport:
    known = [name for marker, name in (
        ("langchain", "LangChain"), ("llamaindex", "LlamaIndex"), ("langgraph", "LangGraph"),
        ("haystack", "Haystack"), ("dspy", "DSPy"), ("autogen", "AutoGen"), ("crewai", "CrewAI"),
    ) if marker in user_intent.lower()]
    return FrameworkResearchReport(
        status="partial",
        frameworks=known or ["Framework A", "Framework B"],
        comparison_dimensions=["execution_success", "latency", "throughput", "dependency_complexity", "failure_reason"],
        evidence=["user_intent"],
        limitations=["Framework facts require verified documentation or executed benchmark artifacts."],
        source_mode="offline_contract",
    )


def build_evidence_report(report_type: str, inputs: dict[str, Any], source_mode: str = "deterministic") -> EvidenceReport:
    rejected_demo = sorted(key for key, value in inputs.items() if _is_unverified_demo(value))
    available = sorted(key for key, value in inputs.items() if value not in (None, "", [], {}) and key not in rejected_demo)
    metrics: dict[str, float] = {}
    for key in available:
        _collect_metrics(inputs[key], metrics, prefix=key, remaining=64)
    scope = _reproduction_scope(inputs.get("reproduction_mode_report"))
    observations = [f"artifact {key} is available" for key in available]
    limitations = []
    if report_type == "paper_compare" and scope != "full":
        limitations.append("The available execution is not a verified full reproduction; conclusions are limited to smoke or partial evidence.")
    if not metrics:
        limitations.append("No finite numeric metrics were found in the supplied artifacts.")
    if rejected_demo:
        limitations.append(f"Unverified offline demo artifacts were excluded from evidence: {', '.join(rejected_demo)}")
    status = "analyzed" if available else "insufficient_evidence"
    return EvidenceReport(
        report_type=report_type,
        status=status,
        observations=observations,
        limitations=limitations,
        metrics=metrics,
        evidence_artifacts=available,
        recommendation="Use only the listed artifacts as evidence; do not extrapolate beyond the recorded reproduction scope.",
        source_mode=source_mode,
    )


def validate_evidence_references(report: EvidenceReport, allowed: set[str]) -> None:
    unknown = sorted(set(report.evidence_artifacts) - allowed)
    if unknown:
        raise ValueError(f"report references unknown evidence artifacts: {unknown}")


def _collect_metrics(value: Any, output: dict[str, float], prefix: str, remaining: int) -> int:
    if remaining <= 0:
        return 0
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return 0
    used = 0
    if isinstance(value, dict):
        for key, item in value.items():
            used += _collect_metrics(item, output, f"{prefix}.{key}", remaining - used)
            if used >= remaining:
                break
    elif isinstance(value, list):
        for index, item in enumerate(value[:16]):
            used += _collect_metrics(item, output, f"{prefix}[{index}]", remaining - used)
            if used >= remaining:
                break
    elif isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
        output[prefix] = float(value)
        used = 1
    return used


def _reproduction_scope(value: Any) -> str:
    try:
        payload = value if isinstance(value, dict) else json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return "unknown"
    return str(payload.get("effective_mode") or payload.get("reproduction_mode") or "unknown").lower()


def _is_unverified_demo(value: Any) -> bool:
    if value == "offline-runtime":
        return True
    if isinstance(value, str):
        if "OFFLINE_DEMO_UNVERIFIED" in value:
            return True
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return False
    return isinstance(value, dict) and value.get("evidence_status") == "unverified_demo"
