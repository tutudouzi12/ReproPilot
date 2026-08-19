"""Public development evaluator for the pinned Rank-BM25 task."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np


def load_candidate():
    path = Path.cwd() / "rank_bm25.py"
    spec = importlib.util.spec_from_file_location("rank_bm25_public_candidate", path)
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


def rejects_invalid_index(instance) -> bool:
    try:
        instance.get_batch_scores(["beta"], [-1])
    except (AssertionError, IndexError, TypeError, ValueError):
        return True
    return False


def main() -> None:
    candidate = load_candidate()
    corpus = [["alpha", "beta"], ["beta"], ["gamma"]]
    documents = ["alpha beta", "beta", "gamma"]
    ordinary = candidate.BM25Okapi(corpus)
    cases = [
        case("ordinary_ranking", lambda: ordinary.get_top_n(["alpha"], documents, n=2)[0] == "alpha beta"),
        case(
            "ordinary_batch_matches_scores",
            lambda: np.allclose(ordinary.get_batch_scores(["beta"], [0, 2]), ordinary.get_scores(["beta"])[[0, 2]]),
        ),
        case("empty_query_is_zero", lambda: np.array_equal(ordinary.get_scores([]), np.zeros(3))),
        case(
            "mixed_empty_documents_are_finite",
            lambda: np.isfinite(candidate.BM25Okapi([[], ["x"]]).get_scores(["x"])).all(),
        ),
        case("empty_corpus_is_supported", lambda: candidate.BM25Okapi([]).get_scores(["x"]).size == 0),
        case(
            "all_empty_corpus_is_zero",
            lambda: np.array_equal(candidate.BM25Okapi([[], []]).get_scores(["x"]), np.zeros(2)),
        ),
        case("zero_top_n_is_empty", lambda: ordinary.get_top_n(["alpha"], documents, n=0) == []),
        case("negative_top_n_is_empty", lambda: ordinary.get_top_n(["alpha"], documents, n=-1) == []),
        case("negative_batch_index_is_rejected", lambda: rejects_invalid_index(ordinary)),
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
