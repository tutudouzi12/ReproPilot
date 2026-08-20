from __future__ import annotations

import json
import random
import sys
from collections import Counter
from collections.abc import Callable, Iterator
from pathlib import Path


sys.path.insert(0, str(Path.cwd()))

from more_itertools import sample  # noqa: E402


SEED = 20250111


class GuardedCounts(Iterator[int]):
    def __init__(self) -> None:
        self.calls = 0

    def __next__(self) -> int:
        self.calls += 1
        if self.calls == 1:
            return 1
        raise AssertionError("counts iterator was consumed past the matched population")


def raises_value_error(*args, **kwargs) -> bool:
    try:
        sample(*args, **kwargs)
    except ValueError:
        return True
    return False


def preserves_lazy_counts() -> bool:
    counts = GuardedCounts()
    result = sample(iter("a"), 1, counts=counts, strict=True)
    return result == ["a"] and counts.calls == 1


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
    (
        "strict_single_zero",
        lambda: raises_value_error("a", 1, counts=[0], strict=True),
    ),
    (
        "strict_trailing_zero",
        lambda: raises_value_error("ab", 2, counts=[1, 0], strict=True),
    ),
    (
        "strict_sparse_generator",
        lambda: raises_value_error(
            (item for item in "abc"),
            3,
            counts=(count for count in [1, 0, 1]),
            strict=True,
        ),
    ),
    ("strict_counts_remain_lazy", preserves_lazy_counts),
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
