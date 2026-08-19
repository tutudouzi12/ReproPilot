from __future__ import annotations

import json
import sys
from pathlib import Path


sys.path.insert(0, str(Path.cwd() / "src"))

from humanize.filesize import naturalsize  # noqa: E402


CASES = [
    {"value": 999999, "kwargs": {}, "expected": "1.0 MB"},
    {"value": -999999, "kwargs": {}, "expected": "-1.0 MB"},
    {"value": 1000, "kwargs": {}, "expected": "1.0 kB"},
    {"value": 1024, "kwargs": {"binary": True}, "expected": "1.0 KiB"},
    {"value": 0, "kwargs": {}, "expected": "0 Bytes"},
    {"value": 3 * 10**34, "kwargs": {}, "expected": "30000.0 QB"},
]


results = []
for case in CASES:
    observed = naturalsize(case["value"], **case["kwargs"])
    results.append({**case, "observed": observed, "passed": observed == case["expected"]})

passed = sum(result["passed"] for result in results)
print(json.dumps({"metrics": {"rounding_score": passed / len(results)}, "passed": passed, "total": len(results), "cases": results}, ensure_ascii=False))
