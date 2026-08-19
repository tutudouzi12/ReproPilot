"""Model-hidden composition evaluator for the pinned Rank-BM25 task."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np


def load_candidate():
    path = Path.cwd() / "rank_bm25.py"
    spec = importlib.util.spec_from_file_location("rank_bm25_hidden_candidate", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("rank_bm25.py could not be imported")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def case(name, check):
    try:
        passed = bool(check())
        return {"name": name, "passed": passed, "error": "" if passed else "assertion failed"}
    except Exception as exc:
        return {"name": name, "passed": False, "error": f"{type(exc).__name__}: {exc}"}


def rejects_negative_index(instance) -> bool:
    try:
        instance.get_batch_scores(["x"], [-1])
    except (AssertionError, IndexError, TypeError, ValueError):
        return True
    return False


def main() -> None:
    candidate = load_candidate()
    variants = (candidate.BM25Okapi, candidate.BM25L, candidate.BM25Plus)
    cases = [
        case("all_variants_accept_empty_corpus", lambda: all(cls([]).get_scores(["x"]).size == 0 for cls in variants)),
        case(
            "all_variants_keep_all_empty_scores_finite",
            lambda: all(np.array_equal(cls([[], []]).get_scores(["x"]), np.zeros(2)) for cls in variants),
        ),
        case(
            "all_variants_return_empty_for_negative_top_n",
            lambda: all(cls([["x"], ["y"]]).get_top_n(["x"], ["x", "y"], -3) == [] for cls in variants),
        ),
        case(
            "all_variants_reject_negative_batch_indices",
            lambda: all(rejects_negative_index(cls([["x"], ["y"]])) for cls in variants),
        ),
    ]
    passed = sum(item["passed"] for item in cases)
    print(
        json.dumps(
            {
                "status": "ok",
                "metrics": {"robustness_score": passed / len(cases)},
                "passed_cases": passed,
                "total_cases": len(cases),
                "cases": cases,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
