# more-itertools strict counted sample exhaustion live repository evaluation

- Recorded at: `2026-08-19T14:33:06.581852Z`
- Harness revision: `da3cfdd2fba0d1f652383b1df7df33c4f456be94`
- Target revision: `18225d856665bfc3bfdfcdbfa585290f92645daf`
- Outcome: `candidate_stopped`
- Public baseline -> best: `0.6666666666666666` -> `0.6666666666666666`
- Hidden baseline -> observed: `0.16666666666666666` -> `0.16666666666666666`
- Model: `/`
- Requests/tokens: `0` / `0`
- Token-derived cost: `not calculated`
- Editable files: `more_itertools/more.py`

## Keep/Reject ledger

| Trial | Status | Decision | Public metric | Reason |
| ---: | --- | --- | ---: | --- |
| 0 | baseline | keep | 0.66666667 | frozen baseline |
| 1 | rejected | reject |  | RemoteProtocolError: Server disconnected without sending a response. |
| 2 | rejected | reject |  | ReadTimeout |
| 3 | rejected | reject |  | ReadTimeout |
| 4 | stopped | reject |  | live request cap reached (3) |

## Evidence boundary

This is one bounded module repair in a pinned external repository, not a full-project benchmark. The evaluator subprocess receives a stripped environment but runs locally rather than in a network-isolated container. Hidden validation is withheld from the proposer context. Cost is derived from provider-reported tokens and the cited public rate, not from a billing-console receipt.
