from __future__ import annotations

import json
import runpy
from pathlib import Path


root = Path(__file__).parent
hidden = Path(__file__).name.startswith("holdout_")
contract_path = root / ("hidden_cases.json" if hidden else "public_cases.json")
contract = json.loads(contract_path.read_text(encoding="utf-8"))
candidate_path = root / "candidate.py"

mutation = contract.get("mutation") or {}
marker = str(mutation.get("candidate_marker") or "")
if marker and marker in candidate_path.read_text(encoding="utf-8"):
    target = root / str(mutation["target"])
    target.write_text("# evaluator mutated by the fault-injection fixture\n", encoding="utf-8")

namespace = runpy.run_path(candidate_path)
function = namespace[str(contract["function"])]
cases = contract["cases"]
passed = 0
for case in cases:
    actual = function(*case.get("args", []), **case.get("kwargs", {}))
    passed += actual == case["expected"]

print(json.dumps({"metrics": {"accuracy": passed / len(cases)}, "passed": passed, "total": len(cases)}))
