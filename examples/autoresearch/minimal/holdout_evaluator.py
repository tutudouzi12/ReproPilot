import json
import runpy
from pathlib import Path


candidate = next(Path(__file__).parent.glob("*-candidate.py"))
score_items = runpy.run_path(candidate)["score_items"]


cases = [([3, 0, -2], 1), ([1, 2, 3], 3), ([0, 0], 0)]
passed = sum(score_items(values) == expected for values, expected in cases)
print(json.dumps({"metrics": {"accuracy": passed / len(cases)}}))
