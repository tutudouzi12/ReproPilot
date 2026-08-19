# Rank-BM25 live repository evaluation

- Recorded at: `2026-08-19T02:37:00.464053Z`
- Harness revision: `66b1b7ae6b2e2599092632cdc90af0b47ab9063e`
- Target revision: `47aa3ddf8dc1ebeb7ef4e65f2b4536af44594099`
- Outcome: `validation_passed`
- Public baseline -> best: `0.5555555555555556` -> `1.0`
- Hidden baseline -> observed: `0.25` -> `1.0`
- Model: `dashscope.aliyuncs.com/qwen3-coder-plus`
- Requests/tokens: `1` / `7176`
- Token-derived cost: `0.0717 CNY`

## Keep/Reject ledger

| Trial | Status | Decision | Public metric | Reason |
| ---: | --- | --- | ---: | --- |
| 0 | baseline | keep | 0.55555556 | frozen baseline |
| 1 | kept | keep | 1 | metrics.robustness_score improved from 0.55555556 to 1 |

## Post-run review

The frozen automated contract passed, but manual review found that the candidate checks `n <= 0` before preserving the original documents/corpus-size assertion. See [`review.json`](review.json). This result is evidence of a contract pass, not a claim that the patch is upstream-ready.

## Evidence boundary

This is one bounded module repair in a pinned external repository, not a full-project benchmark. The evaluator subprocess receives a stripped environment but runs locally rather than in a network-isolated container. Hidden validation is withheld from the proposer context. Cost is derived from provider-reported tokens and the cited public rate, not from a billing-console receipt.
