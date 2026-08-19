# Retained more-itertools live runs

| Harness revision | Outcome | Public | Hidden | Attempts | Usage reports | Token-derived cost | Manual review |
| --- | --- | ---: | ---: | ---: | ---: | --- | --- |
| [`da3cfdd-live`](da3cfdd-live/) | `candidate_stopped` | `4/6 -> 4/6` | `1/6 -> 1/6` | 3 | 0 | not calculated | [`provider_requests_failed_no_candidate`](da3cfdd-live/review.json) |
| [`69843c7-live`](69843c7-live/) | `candidate_stopped` | `4/6 -> 4/6` | `1/6 -> 1/6` | 3 | 1 | not calculated | [`truncated_context_candidate_rejected_then_provider_failures`](69843c7-live/review.json) |

All three bounded provider attempts failed before returning model content or token usage: one `RemoteProtocolError` and two `ReadTimeout` failures. No candidate patch was produced, no trial was accepted, and fresh hidden validation remained at the frozen baseline.

This run is retained as provider/request-boundary evidence. It is not classified as a model-generated repair failure because the provider returned no candidate to evaluate, and the absence of usage data is not presented as zero cost.

The second run received one candidate before a timeout and a server disconnect exhausted the remaining request cap. The candidate attempted a full-file replacement after seeing only the configured 32,000-character prefix of a 158,840-character module; the target `sample()` implementation begins at character 120,143. The returned 1,173-line replacement failed the `py_compile` guard with an unterminated triple-quoted string and was rolled back. This is retained as a real guard rejection and as evidence that prefix-only context plus full-file replacement does not scale to this module; it is not reduced to a semantic model-capability claim.

Candidate source and patch artifacts preserve the exact bytes retained by the runner. `.gitattributes` prevents line-ending normalization and limits the whitespace exemption to those evidence file types.
