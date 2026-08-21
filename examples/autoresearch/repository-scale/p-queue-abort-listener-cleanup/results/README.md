# Retained p-queue live runs

| Harness revision | Outcome | Public | Hidden | Attempts | Usage reports | Token-derived cost | Manual review |
| --- | --- | ---: | ---: | ---: | ---: | --- | --- |
| [`b856ce8-live`](b856ce8-live/) | `candidate_stopped` | `2/4 -> 2/4` | `2/5 -> 2/5` | 3 | 0 | not calculated | [`provider_requests_failed_no_candidate`](b856ce8-live/review.json) |
| [`81d5051-live`](81d5051-live/) | `candidate_stopped` | `2/4 -> 2/4` | `2/5 -> 2/5` | 3 | 1 | not calculated | [`guard_rejection_then_provider_failures`](81d5051-live/review.json) |
| [`d9cbaf2-live`](d9cbaf2-live/) | `candidate_stopped` | `2/4 -> 2/4` | `2/5 -> 2/5` | 3 | 2 | not calculated | [`guard_rejections_and_provider_failure`](d9cbaf2-live/review.json) |

All three bounded provider attempts failed with `ConnectError` before returning model content or token usage. No candidate patch was produced, the retained editable file matches the pinned base, and fresh hidden validation remained at the frozen baseline.

This run is retained as provider-connectivity and request-cap evidence. It is not classified as a model-generated repair failure. A later harness revision adds bounded retries for connection setup only; it does not retry read timeouts or HTTP status errors that could follow a provider-processed request.

The generated per-run README reports zero requests because the original renderer used provider usage reports rather than attempted calls. That artifact remains unchanged and hash-linked in `result.json`; the manual review records the discrepancy, and later runs report attempts, usage reports, and tokens separately.

The second run returned one candidate with two localized edits to the same file. The pre-fix patch engine rejected the second edit before execution, and two later connection failures exhausted the request cap. That run motivated bounded support for sequential localized replacements while preserving the prohibition on mixing complete-file replacement with other edits.

The third run used the corrected patch engine. Its first model candidate failed one pinned functional test. Its second returned candidate passed all 129 functional tests but failed TypeScript compilation and `tsd`; an intervening provider attempt disconnected. No candidate reached public scoring, so the pinned source was restored and hidden validation remained at baseline. This final run is selected as the primary manually rejected result rather than rerunning until success.
