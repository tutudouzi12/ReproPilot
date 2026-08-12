import json
import runpy
from pathlib import Path


candidate = next(Path(__file__).parent.glob("*-candidate.py"))
score_items = runpy.run_path(candidate)["score_items"]


cases = [([1, -1, 2], 2), ([0, 1], 1), ([-1, -2], 0)]
passed = sum(score_items(values) == expected for values, expected in cases)
print(json.dumps({"metrics": {"accuracy": passed / len(cases)}}))
