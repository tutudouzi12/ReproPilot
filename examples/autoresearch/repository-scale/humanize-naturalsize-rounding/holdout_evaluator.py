from __future__ import annotations

import json
import sys
from pathlib import Path


sys.path.insert(0, str(Path.cwd() / "src"))

from humanize.filesize import naturalsize  # noqa: E402


CASES = [
    {"value": 999999999, "kwargs": {}, "expected": "1.0 GB"},
    {"value": 999999999999, "kwargs": {}, "expected": "1.0 TB"},
    {"value": 1024**2 - 1, "kwargs": {"binary": True}, "expected": "1.0 MiB"},
    {"value": 1024**3 - 1, "kwargs": {"binary": True}, "expected": "1.0 GiB"},
    {"value": 1024**2 - 1, "kwargs": {"gnu": True}, "expected": "1.0M"},
    {"value": 1024**2, "kwargs": {"binary": True}, "expected": "1.0 MiB"},
]


results = []
for case in CASES:
    observed = naturalsize(case["value"], **case["kwargs"])
    results.append({**case, "observed": observed, "passed": observed == case["expected"]})

passed = sum(result["passed"] for result in results)
print(json.dumps({"metrics": {"rounding_score": passed / len(results)}, "passed": passed, "total": len(results), "cases": results}, ensure_ascii=False))
