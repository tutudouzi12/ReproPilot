# more-itertools strict counted sample adversarial follow-up

This task versions the benchmark gap discovered during manual review of [`c261d99-live`](../more-itertools-strict-counted-sample/results/c261d99-live/). That candidate passed the original frozen public and hidden cases but eagerly materialized `counts` under `strict=True`. A bounded sentinel comparison showed that the candidate consumed past the population item while the merged upstream repair preserved lazy consumption.

The task keeps the same pinned base, public evaluator, objective, and upstream suite. Its hidden evaluator adds finite strict-exhaustion variants plus one bounded laziness case. This is a candidate-informed adversarial follow-up in the same repository, not a fourth unique repository and not an independent sample for repository-level aggregate claims.

Expected reference behavior:

- pinned base: public `4/6`, hidden `2/10`;
- merged upstream repair: public `6/6`, hidden `10/10`;
- retained `c261d99-live` candidate: public `6/6`, hidden `9/10` and rejected by the frozen `0.8` hidden minimum delta.

Reproduce the baseline with the existing detached checkout and Python environment:

```powershell
py -3.11 scripts\run_repository_baseline.py `
  --task-dir examples\autoresearch\repository-scale\more-itertools-strict-counted-sample-adversarial `
  --checkout <more-itertools-base-checkout> `
  --python <more-itertools-python> `
  --output examples\autoresearch\repository-scale\more-itertools-strict-counted-sample-adversarial\baseline.json
```

The original run is not rewritten retroactively. Both contracts remain available so the reason for the benchmark hardening is auditable.
