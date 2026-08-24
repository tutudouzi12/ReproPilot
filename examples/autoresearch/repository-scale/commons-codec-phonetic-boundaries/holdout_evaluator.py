from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def load_public_evaluator():
    directory = Path(__file__).resolve().parent
    evaluator_path = directory / "02-evaluator.py"
    if not evaluator_path.is_file():
        evaluator_path = directory / "evaluator.py"
    spec = importlib.util.spec_from_file_location("commons_codec_public_evaluator", evaluator_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load evaluator: {evaluator_path.name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


public = load_public_evaluator()

HIDDEN_CASES = [
    public.Case("sephardic_al_prefix", "al", "SEPHARDIC", "APPROX", False, 10, "|al"),
    public.Case("sephardic_el_prefix", "el", "SEPHARDIC", "APPROX", False, 10),
    public.Case("ashkenazi_bar_prefix", "bar", "ASHKENAZI", "APPROX", False, 10, "bar|bor|var|vor"),
    public.Case("generic_da_control", "da", "GENERIC", "EXACT", False, 10, "da|di"),
    public.Case("ordinary_name_control", "smith", "GENERIC", "APPROX", False, 10),
]

print(json.dumps(public.evaluate_cases(HIDDEN_CASES), ensure_ascii=False))
