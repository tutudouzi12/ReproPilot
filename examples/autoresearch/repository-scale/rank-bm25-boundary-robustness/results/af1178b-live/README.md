# Rank-BM25 live repository evaluation

- Recorded at: `2026-08-19T02:25:58.128243Z`
- Harness revision: `af1178b6af72408d470fae714abf45c9a04513a8`
- Target revision: `47aa3ddf8dc1ebeb7ef4e65f2b4536af44594099`
- Outcome: `hidden_validation_failed`
- Public baseline -> best: `0.5555555555555556` -> `0.8888888888888888`
- Hidden baseline -> observed: `0.25` -> `0.75`
- Model: `dashscope.aliyuncs.com/qwen3-coder-plus`
- Requests/tokens: `3` / `26224`
- Token-derived cost: `0.225568 CNY`

## Keep/Reject ledger

| Trial | Status | Decision | Public metric | Reason |
| ---: | --- | --- | ---: | --- |
| 0 | baseline | keep | 0.55555556 | frozen baseline |
| 1 | kept | keep | 0.88888889 | metrics.robustness_score improved from 0.55555556 to 0.88888889 |
| 2 | rejected | reject | 0.88888889 | metrics.robustness_score did not improve by required delta 0.01 |
| 3 | rejected | reject | 0.88888889 | metrics.robustness_score did not improve by required delta 0.01 |
| 4 | stopped | reject |  | live request cap reached (3) |

## Evidence boundary

This is one bounded module repair in a pinned external repository, not a full-project benchmark. The evaluator subprocess receives a stripped environment but runs locally rather than in a network-isolated container. Hidden validation is withheld from the proposer context. Cost is derived from provider-reported tokens and the cited public rate, not from a billing-console receipt.
