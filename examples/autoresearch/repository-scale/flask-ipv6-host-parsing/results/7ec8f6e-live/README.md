# Flask bracketed IPv6 host parsing live repository evaluation

- Recorded at: `2026-08-20T05:40:06.686323Z`
- Harness revision: `7ec8f6ebd47cdea471ec0a0c267b379cb4bca5b2`
- Target revision: `514fc6b3e8402e4c646d5284e97a4f0ab50a7c4b`
- Outcome: `validation_passed`
- Public baseline -> best: `0.5` -> `1.0`
- Hidden baseline -> observed: `0.4` -> `1.0`
- Validation acceptance: `minimum_improvement`, target `0.9`, delta `0.5`
- Model: `dashscope.aliyuncs.com/qwen3-coder-plus`
- Requests/tokens: `3` / `35392`
- Token-derived cost: `0.169744 CNY`
- Editable files: `src/flask/app.py, src/flask/testing.py`

## Keep/Reject ledger

| Trial | Status | Decision | Public metric | Reason |
| ---: | --- | --- | ---: | --- |
| 0 | baseline | keep | 0.5 | frozen baseline |
| 1 | rejected | reject | 0.5 | metrics.ipv6_host_score did not improve by required delta 0.1 |
| 2 | rejected | reject |  | ValueError: localized patch search must match exactly once in src/flask/app.py; matched 0 times |
| 3 | kept | keep | 1 | metrics.ipv6_host_score improved from 0.5 to 1 |

## Evidence boundary

This is one bounded module repair in a pinned external repository, not a full-project benchmark. The evaluator subprocess receives a stripped environment but runs locally rather than in a network-isolated container. Hidden validation is withheld from the proposer context. Cost is derived from provider-reported tokens and the cited public rate, not from a billing-console receipt.
