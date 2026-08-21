# p-queue abort-listener cleanup live repository evaluation

- Recorded at: `2026-08-21T03:19:27.428386Z`
- Harness revision: `b856ce813b2bbdf25a71d649a07a804463752f38`
- Target revision: `5e400174a89395a44399713191b76544cf743fe5`
- Outcome: `candidate_stopped`
- Public baseline -> best: `0.5` -> `0.5`
- Hidden baseline -> observed: `0.4` -> `0.4`
- Validation acceptance: `minimum_improvement`, target `1.0`, delta `0.6`
- Model: `/`
- Requests/tokens: `0` / `0`
- Token-derived cost: `not calculated`
- Editable files: `source/index.ts`

## Keep/Reject ledger

| Trial | Status | Decision | Public metric | Reason |
| ---: | --- | --- | ---: | --- |
| 0 | baseline | keep | 0.5 | frozen baseline |
| 1 | rejected | reject |  | ConnectError |
| 2 | rejected | reject |  | ConnectError |
| 3 | rejected | reject |  | ConnectError |
| 4 | stopped | reject |  | live request cap reached (3) |

## Evidence boundary

This is one bounded module repair in a pinned external repository, not a full-project benchmark. The evaluator subprocess receives a stripped environment but runs locally rather than in a network-isolated container. Hidden validation is withheld from the proposer context. Cost is derived from provider-reported tokens and the cited public rate, not from a billing-console receipt.
