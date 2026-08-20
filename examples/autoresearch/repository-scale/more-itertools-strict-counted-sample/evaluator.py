from __future__ import annotations

import json
import random
import sys
from collections import Counter
from collections.abc import Callable
from pathlib import Path


sys.path.insert(0, str(Path.cwd()))

from more_itertools import sample  # noqa: E402


SEED = 20250111


def raises_value_error(*args, **kwargs) -> bool:
    try:
        sample(*args, **kwargs)
    except ValueError:
        return True
    return False


def evaluate(name: str, check: Callable[[], bool]) -> dict[str, object]:
    random.seed(SEED)
    try:
        observed: object = bool(check())
    except Exception as exc:  # evaluator evidence should retain unexpected failures
        observed = f"{type(exc).__name__}: {exc}"
    return {"name": name, "expected": True, "observed": observed, "passed": observed is True}


CASES = [
    (
        "strict_unit_counts",
        lambda: raises_value_error("abcde", 10, counts=[1, 1, 1, 1, 1], strict=True),
    ),
    (
        "strict_aggregated_counts",
        lambda: raises_value_error("ab", 4, counts=[2, 1], strict=True),
    ),
    (
        "strict_exact_total",
        lambda: Counter(sample("ab", 3, counts=[2, 1], strict=True)) == Counter("aab"),
    ),
    (
        "non_strict_undersized",
        lambda: Counter(sample("ab", 5, counts=[2, 1])) == Counter("aab"),
    ),
    (
        "weighted_strict_undersized",
        lambda: raises_value_error("ab", 3, weights=[1, 1], strict=True),
    ),
    (
        "negative_k",
        lambda: raises_value_error("a", -1, counts=[1], strict=True),
    ),
]


results = [evaluate(name, check) for name, check in CASES]
passed = sum(result["passed"] for result in results)
print(
    json.dumps(
        {
            "metrics": {"strict_counted_score": passed / len(results)},
            "passed": passed,
            "total": len(results),
            "cases": results,
        },
        ensure_ascii=False,
    )
)
