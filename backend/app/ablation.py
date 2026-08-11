from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, Field


BRANCH_LIMIT = 8
MAX_DEPTH = 2
VALID_CATEGORIES = {"parameter", "module", "data_scale", "seed_stability", "runtime_cost"}
CATEGORY_ALIASES = {
    "parameters": "parameter", "hyperparameter": "parameter", "hyperparameters": "parameter",
    "modules": "module", "component": "module", "component_removal": "module",
    "data": "data_scale", "dataset": "data_scale", "data_size": "data_scale",
    "seed": "seed_stability", "random_seed": "seed_stability", "stability": "seed_stability",
    "cost": "runtime_cost", "runtime": "runtime_cost", "efficiency": "runtime_cost",
}


class AblationBudget(BaseModel):
    max_experiments: int
    max_gpu_minutes: int
    max_wall_minutes: int


class AblationCandidate(BaseModel):
    id: str
    parent_id: str = "root"
    category: str
    title: str
    hypothesis: str = ""
    change: str = ""
    metrics: list[str] = Field(default_factory=list)
    estimated_minutes: int = 1
    estimated_gpu_minutes: int = 0
    information_gain: float = 0.0
    relevance: float = 0.0
    reproducibility: float = 0.0
    risk: float = 0.0
    score: float = 0.0
    evaluation_reason: str = ""


class AblationEvaluation(BaseModel):
    id: str
    information_gain: float = 0.0
    relevance: float = 0.0
    reproducibility: float = 0.0
    risk: float = 0.0
    reason: str = ""


class AblationPlan(BaseModel):
    strategy: str = "bounded_tree_of_thoughts"
    max_depth: int = MAX_DEPTH
    branch_limit: int = BRANCH_LIMIT
    budget: AblationBudget
    candidates: list[AblationCandidate]
    selected: list[AblationCandidate]
    pruned_ids: list[str] = Field(default_factory=list)
    selection_reason: str


def default_candidates() -> list[AblationCandidate]:
    return [
        AblationCandidate(id="parameter", category="parameter", title="Parameter sensitivity", hypothesis="A core parameter controls the reported behavior.", change="Vary one structural or optimization parameter around the baseline.", metrics=["primary_metric", "latency"], estimated_minutes=15, information_gain=0.82, relevance=0.88, reproducibility=0.92, risk=0.12),
        AblationCandidate(id="module", category="module", title="Module removal", hypothesis="A named module is necessary for the claimed gain.", change="Disable one core module while keeping the remaining configuration fixed.", metrics=["primary_metric", "output_delta"], estimated_minutes=20, information_gain=0.94, relevance=0.95, reproducibility=0.84, risk=0.18),
        AblationCandidate(id="data_scale", category="data_scale", title="Data-scale sensitivity", hypothesis="The method behaves differently as evaluated data size changes.", change="Run the same configuration on bounded data slices.", metrics=["primary_metric", "throughput"], estimated_minutes=18, information_gain=0.76, relevance=0.72, reproducibility=0.9, risk=0.1),
        AblationCandidate(id="seed_stability", category="seed_stability", title="Random-seed stability", hypothesis="The observed result is stable across initialization.", change="Repeat the baseline with fixed seeds.", metrics=["primary_metric_mean", "primary_metric_std"], estimated_minutes=15, information_gain=0.7, relevance=0.78, reproducibility=0.98, risk=0.06),
        AblationCandidate(id="runtime_cost", category="runtime_cost", title="Runtime-cost comparison", hypothesis="The gain remains useful after accounting for cost.", change="Measure latency and memory under bounded workloads.", metrics=["latency", "throughput", "memory"], estimated_minutes=10, information_gain=0.6, relevance=0.68, reproducibility=0.96, risk=0.05),
    ]


def parse_candidates(raw: str) -> list[AblationCandidate]:
    payload = _clean_json(raw)
    try:
        values = json.loads(payload).get("candidates", [])
    except (json.JSONDecodeError, AttributeError):
        return []
    result = []
    seen = set()
    for value in values:
        if not isinstance(value, dict):
            continue
        candidate_id = _sanitize_id(str(value.get("id", "")))
        category = _sanitize_category(str(value.get("category", "")))
        title = str(value.get("title", "")).strip()
        if not candidate_id or not category or not title or candidate_id in seen:
            continue
        seen.add(candidate_id)
        value = dict(value)
        value.update(id=candidate_id, category=category, title=title)
        value["estimated_minutes"] = _clamp(int(value.get("estimated_minutes") or 1), 1, 240)
        value["estimated_gpu_minutes"] = _clamp(int(value.get("estimated_gpu_minutes") or 0), 0, value["estimated_minutes"])
        result.append(AblationCandidate.model_validate(value))
        if len(result) >= BRANCH_LIMIT:
            break
    return result


def parse_evaluations(raw: str) -> dict[str, AblationEvaluation]:
    try:
        values = json.loads(_clean_json(raw)).get("evaluations", [])
    except (json.JSONDecodeError, AttributeError):
        return {}
    result = {}
    for value in values:
        if not isinstance(value, dict):
            continue
        candidate_id = _sanitize_id(str(value.get("id", "")))
        if not candidate_id:
            continue
        normalized = dict(value, id=candidate_id)
        for key in ("information_gain", "relevance", "reproducibility", "risk"):
            normalized[key] = _unit(float(normalized.get(key) or 0))
        result[candidate_id] = AblationEvaluation.model_validate(normalized)
    return result


def ensure_category_coverage(generated: list[AblationCandidate], defaults: list[AblationCandidate] | None = None) -> list[AblationCandidate]:
    merged = [item.model_copy(deep=True) for item in generated]
    covered = {item.category for item in merged}
    for candidate in defaults or default_candidates():
        if len(merged) >= BRANCH_LIMIT:
            break
        if candidate.category not in covered:
            merged.append(candidate.model_copy(deep=True))
            covered.add(candidate.category)
    return merged


def select_candidates(
    candidates: list[AblationCandidate],
    evaluations: dict[str, AblationEvaluation] | None,
    budget: AblationBudget,
) -> AblationPlan:
    bounded = []
    for source in candidates[:BRANCH_LIMIT]:
        candidate = source.model_copy(deep=True)
        evaluation = (evaluations or {}).get(candidate.id)
        if evaluation:
            candidate.information_gain = evaluation.information_gain
            candidate.relevance = evaluation.relevance
            candidate.reproducibility = evaluation.reproducibility
            candidate.risk = evaluation.risk
            candidate.evaluation_reason = evaluation.reason.strip()
        candidate.information_gain = _default_unit(candidate.information_gain, 0.6)
        candidate.relevance = _default_unit(candidate.relevance, 0.6)
        candidate.reproducibility = _default_unit(candidate.reproducibility, 0.8)
        candidate.risk = _unit(candidate.risk)
        cost_penalty = min(1.0, candidate.estimated_minutes / max(1, budget.max_wall_minutes))
        candidate.score = round(0.4 * candidate.information_gain + 0.3 * candidate.relevance + 0.2 * candidate.reproducibility - 0.07 * cost_penalty - 0.03 * candidate.risk, 4)
        bounded.append(candidate)
    bounded.sort(key=lambda item: (-item.score, item.estimated_minutes))
    selected = []
    pruned = []
    used_wall = 0
    used_gpu = 0
    categories = set()
    for candidate in bounded:
        fits = (
            len(selected) < budget.max_experiments
            and used_wall + candidate.estimated_minutes <= budget.max_wall_minutes
            and used_gpu + candidate.estimated_gpu_minutes <= budget.max_gpu_minutes
            and candidate.category not in categories
        )
        if not fits:
            pruned.append(candidate.id)
            continue
        selected.append(candidate)
        used_wall += candidate.estimated_minutes
        used_gpu += candidate.estimated_gpu_minutes
        categories.add(candidate.category)
    return AblationPlan(
        budget=budget,
        candidates=bounded,
        selected=selected,
        pruned_ids=pruned,
        selection_reason=f"greedy beam selection kept {len(selected)} diverse branch(es) within wall={used_wall}/{budget.max_wall_minutes} and gpu={used_gpu}/{budget.max_gpu_minutes} minutes",
    )


def design_from_model_outputs(candidate_json: str, evaluation_json: str, inputs: dict[str, Any]) -> AblationPlan:
    budget = AblationBudget(
        max_experiments=_clamp(int(inputs.get("ablation_max_experiments", 3)), 1, 6),
        max_gpu_minutes=_clamp(int(inputs.get("ablation_max_gpu_minutes", 30)), 0, 1440),
        max_wall_minutes=_clamp(int(inputs.get("ablation_max_wall_minutes", 60)), 5, 1440),
    )
    generated = ensure_category_coverage(parse_candidates(candidate_json))
    return select_candidates(generated, parse_evaluations(evaluation_json), budget)


def _clean_json(raw: str) -> str:
    return raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()


def _sanitize_id(value: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "", re.sub(r"[\s\-/]+", "_", value.lower().strip())).strip("_")


def _sanitize_category(value: str) -> str:
    normalized = CATEGORY_ALIASES.get(_sanitize_id(value), _sanitize_id(value))
    return normalized if normalized in VALID_CATEGORIES else ""


def _clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, value))


def _unit(value: float) -> float:
    return max(0.0, min(1.0, value))


def _default_unit(value: float, fallback: float) -> float:
    return fallback if value <= 0 else _unit(value)

