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
    ("strict_empty", lambda: raises_value_error([], 1, counts=[], strict=True)),
    (
        "strict_zero_leading",
        lambda: raises_value_error(["a", "b"], 2, counts=[0, 1], strict=True),
    ),
    (
        "strict_short_counts_iterator",
        lambda: raises_value_error("abc", 2, counts=iter([1]), strict=True),
    ),
    (
        "strict_generator_inputs",
        lambda: raises_value_error(
            (item for item in "abc"),
            4,
            counts=(1 for _ in range(3)),
            strict=True,
        ),
    ),
    (
        "strict_mixed_counts",
        lambda: raises_value_error("abcd", 7, counts=[2, 0, 3, 1], strict=True),
    ),
    (
        "non_strict_generator_inputs",
        lambda: Counter(
            sample((item for item in "ab"), 5, counts=(count for count in [2, 1]))
        )
        == Counter("aab"),
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
