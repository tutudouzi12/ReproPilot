# Rank-BM25 boundary robustness

This task freezes [`dorianbrown/rank_bm25`](https://github.com/dorianbrown/rank_bm25) at commit `47aa3ddf8dc1ebeb7ef4e65f2b4536af44594099`. The upstream suite has two loading tests and passes before the ReproPilot evaluator runs.

The public contract measures nine ordinary-behavior and boundary cases. The hidden contract composes the same classes and unseen inputs across `BM25Okapi`, `BM25L`, and `BM25Plus`. The retained [`baseline.json`](baseline.json) is public `5/9` and hidden `1/4`; it is a starting point, not a successful repair.

## Reproduce the retained baseline

```powershell
git clone --no-checkout https://github.com/dorianbrown/rank_bm25.git <checkout>
git -C <checkout> checkout --detach 47aa3ddf8dc1ebeb7ef4e65f2b4536af44594099

py -3.11 -m venv <venv>
<venv>\Scripts\python.exe -m pip install numpy==2.1.3 pytest==8.3.5

py -3.11 scripts\run_repository_baseline.py `
  --task-dir examples\autoresearch\repository-scale\rank-bm25-boundary-robustness `
  --checkout <checkout> `
  --python <venv>\Scripts\python.exe `
  --output examples\autoresearch\repository-scale\rank-bm25-boundary-robustness\baseline.json
```

`task.json` freezes the external repository identity and baseline contract. `autoresearch.json` is the bounded candidate-search contract for the later live-model run; it permits edits only to `rank_bm25.py`, protects both evaluators, reruns the upstream suite for every candidate, and requires a fresh hidden improvement before acceptance.
