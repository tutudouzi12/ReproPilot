from __future__ import annotations

import re
from typing import Iterable

from pydantic import BaseModel, Field

from .dependencies import normalize_dependencies, package_root


class DependencyRecoveryPlan(BaseModel):
    action: str
    reason: str = ""
    remove_package: str = ""
    replace_package: str = ""
    with_package: str = ""
    target_image: str = ""
    next_dependencies: list[str] = Field(default_factory=list)


def apply_dependency_plan(packages: Iterable[str], plan: DependencyRecoveryPlan) -> tuple[list[str], str]:
    current = normalize_dependencies(packages)
    action = plan.action.strip()
    if action == "remove_package" and plan.remove_package.strip():
        root = package_root(plan.remove_package)
        return [item for item in current if package_root(item) != root], plan.reason or f"removed {root}"
    if action == "replace_package" and plan.replace_package.strip() and plan.with_package.strip():
        root = package_root(plan.replace_package)
        replacement = normalize_dependencies([plan.with_package])
        if not replacement:
            return current, "invalid replacement"
        result = [replacement[0] if package_root(item) == root else item for item in current]
        return normalize_dependencies(result), plan.reason or f"replaced {root}"
    if action == "rewrite_dependencies" and plan.next_dependencies:
        return normalize_dependencies(plan.next_dependencies), plan.reason or "rewrote dependency set"
    return current, plan.reason or "no effective ReAct action"


def validate_python_image(image: str) -> str:
    match = re.fullmatch(r"python:(3\.(?:9|10|11|12|13))-slim", image.strip())
    if not match:
        raise ValueError("ReAct target_image must be an allowed official Python slim image")
    return image.strip()


def repair_dependency_set(packages: Iterable[str], error: str) -> tuple[list[str], str]:
    current = normalize_dependencies(packages)
    lowered = error.lower()
    failing = _failing_requirement(error)
    if failing and any(marker in lowered for marker in ("no matching distribution", "could not find a version")):
        failing_root = package_root(failing)
        repaired = []
        changed = False
        for package in current:
            if package_root(package) == failing_root and package.strip().lower() != failing_root:
                repaired.append(failing_root)
                changed = True
            else:
                repaired.append(package)
        if changed:
            return normalize_dependencies(repaired), f"removed incompatible version pin for {failing_root}"
    normalized = normalize_dependencies(current)
    if normalized != current:
        return normalized, "normalized legacy dependency names"
    missing = _missing_module(error)
    if missing:
        mapped = normalize_dependencies([missing])
        if mapped and all(package_root(item) != package_root(mapped[0]) for item in current):
            return [*current, mapped[0]], f"added package for missing module {missing}"
    return current, "no safe rule-based dependency repair available"


def suggested_python_image(error: str) -> str:
    patterns = (
        r"requires[- ]python\s*(?:>=|>|~=)\s*(3\.\d+)",
        r"python\s*(3\.\d+)\s*or newer",
        r"requires a different python[^0-9]*(3\.\d+)",
    )
    lowered = error.lower()
    for pattern in patterns:
        match = re.search(pattern, lowered)
        if match:
            major, minor = (int(part) for part in match.group(1).split("."))
            if major == 3 and 9 <= minor <= 13:
                return f"python:{major}.{minor}-slim"
    return ""


def _failing_requirement(error: str) -> str:
    patterns = (
        r"no matching distribution found for\s+([^\s;]+)",
        r"could not find a version that satisfies the requirement\s+([^\s;(]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, error, re.IGNORECASE)
        if match:
            return match.group(1).strip("'\"")
    return ""


def _missing_module(error: str) -> str:
    match = re.search(r"No module named ['\"]([^'\".]+)", error)
    return match.group(1) if match else ""
