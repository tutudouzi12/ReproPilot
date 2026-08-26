# ReproPilot repeated repository benchmark campaign

This report is a sanitized, deterministic public view of the retained 18-cell live-model campaign. It was rebuilt read-only after incomplete-cell usage bounds were added; the original campaign and its original matrix were not rewritten.

## Headline results

| Fact | Result |
| --- | ---: |
| Recorded cells | 18/18 |
| Completed cells | 15/18 |
| Automated contract passes | 9/18 |
| Incomplete cells | 3 |
| Known attempted requests | 30 |
| Attempted-request bound | 30-39 |
| Completed responses | 28 |
| Provider usage reports | 28 |
| Reported tokens | 205683 |

The campaign status remains `incomplete`. Incomplete cells stay in every frozen denominator and are not retried or reclassified for a better score.

## Evidence identity

| Field | Value |
| --- | --- |
| Campaign | [`repository-scale-repeat-3-v1`](repeated-benchmark.json) |
| Campaign contract SHA-256 | `4d7cce23a2de3f3c76228e8cde9ab5f32366d5af7b70131eac2380c547d07323` |
| Run manifest SHA-256 | `e0fc57733538adef2756923628829c378656027a4e5f2d6b41930e32f320ba75` |
| Preflight SHA-256 | `0d392cde312efac697b47a4910077acc0745c52908cffdf03ad6cda39a982154` |
| Benchmark | `repository-scale-pilot-v1` |
| Benchmark contract SHA-256 | `b12bfa95f51c8bbf7e3e875d810f08548de0762de5caaa014c9d015af494173c` |
| Harness revision | `65e33cc6c0f98f897571b16297c856d2f8e77285` |
| Provider / model | `dashscope.aliyuncs.com` / `qwen3-coder-plus` |
| Retained original matrix SHA-256 | `c03d4ba601a9a9782c7efc5d5c822d8678d304c62d26c0a56bc4772e3596857b` |
| Published rebuilt matrix SHA-256 | `0089f36863b39f8c8f13109132abf8225605545436e6cebc952d5ff4dd8b194b` |

The retained original matrix predates bounded unknown-usage reporting and remains hash-identical. The separately published rebuilt matrix is [`repeated-benchmark-results.json`](repeated-benchmark-results.json).

## Frozen-denominator rates

| Metric | Result |
| --- | ---: |
| Completion | 15/18 (0.8333) |
| Automated cell pass | 9/18 (0.5000) |
| First-repetition pass | 3/6 (0.5000) |
| Tasks passing all repetitions | 3/6 (0.5000) |
| Tasks passing at least once | 3/6 (0.5000) |

## Per-task results

| Task | Completed | Automated passes | Repetition outcomes |
| --- | ---: | ---: | --- |
| `rank-bm25-boundary-robustness` | 3/3 | 0/3 | r1 `candidate_stopped`, r2 `hidden_validation_failed`, r3 `candidate_stopped` |
| `humanize-naturalsize-rounding` | 3/3 | 3/3 | r1 `validation_passed`, r2 `validation_passed`, r3 `validation_passed` |
| `more-itertools-strict-counted-sample` | 3/3 | 3/3 | r1 `validation_passed`, r2 `validation_passed`, r3 `validation_passed` |
| `flask-ipv6-host-parsing` | 3/3 | 3/3 | r1 `validation_passed`, r2 `validation_passed`, r3 `validation_passed` |
| `p-queue-abort-listener-cleanup` | 0/3 | 0/3 | r1 `incomplete`, r2 `incomplete`, r3 `incomplete` |
| `commons-codec-phonetic-boundaries` | 3/3 | 0/3 | r1 `candidate_stopped`, r2 `hidden_validation_failed`, r3 `candidate_stopped` |

## Cell evidence index

| Cell | Task / repetition | Status | Classification | Evidence SHA-256 |
| ---: | --- | --- | --- | --- |
| 1 | `rank-bm25-boundary-robustness` / r1 | `completed` | `candidate_stopped` | `27648949354b2610bb6b9dd36bcf2275a200325a9158aa52c31b0ee14be4c437` |
| 2 | `humanize-naturalsize-rounding` / r1 | `completed` | `validation_passed` | `c4edf72a4bbd7300c69b8bedc9cfc0052c543609e8f25d904e06b7f96842a339` |
| 3 | `more-itertools-strict-counted-sample` / r1 | `completed` | `validation_passed` | `7fed445bd3448bd4d854c1b888527647e7a5db8e5ec47fe3b0b72bd0bba9939f` |
| 4 | `flask-ipv6-host-parsing` / r1 | `completed` | `validation_passed` | `9b77bde768ea1ed4f0f5c43d395e06faa4eb220b9cb234be9f6e3d08d7079346` |
| 5 | `p-queue-abort-listener-cleanup` / r1 | `incomplete` | `runner_failed_without_result` | `957a3cd99994e36e934c664e3a8b1b1dfbbdc888c88cd120dee1e0ff2b5d72a9` |
| 6 | `commons-codec-phonetic-boundaries` / r1 | `completed` | `candidate_stopped` | `bc2ba22361e6e7a1d82699595043a82242ba458c1a067fad7189be73e0eaf729` |
| 7 | `rank-bm25-boundary-robustness` / r2 | `completed` | `hidden_validation_failed` | `ef3504fcc7006efe4fabeec3f9bce098b25354570cc1998e0b6b27741b052c0a` |
| 8 | `humanize-naturalsize-rounding` / r2 | `completed` | `validation_passed` | `858bcc8420999892244430637601b9260d9d616b640e64b6508048d3296fca27` |
| 9 | `more-itertools-strict-counted-sample` / r2 | `completed` | `validation_passed` | `3953311ef48651c46b26bc027a8efef6ddc71de95f057981b80d75764460b4f7` |
| 10 | `flask-ipv6-host-parsing` / r2 | `completed` | `validation_passed` | `3f4f4329233a8a16a5196cb0f3b4b5ab45a4f8f1e096c9d21ff3de35b4a25383` |
| 11 | `p-queue-abort-listener-cleanup` / r2 | `incomplete` | `runner_failed_without_result` | `5fca5c0f615dffbff7402d27a8dd229d231c5a415577cbf23e2d0d5d21768631` |
| 12 | `commons-codec-phonetic-boundaries` / r2 | `completed` | `hidden_validation_failed` | `9ffb197cc2978be13b9fc264e3e28c8ce96771dd4c6764af6b51f825967f936e` |
| 13 | `rank-bm25-boundary-robustness` / r3 | `completed` | `candidate_stopped` | `0bc04f10f6c3cdebf21629a8399f65f433e740a33a27a081dd29fb37b2b1158d` |
| 14 | `humanize-naturalsize-rounding` / r3 | `completed` | `validation_passed` | `10f414f2c94c77e821db11701dc78ea301cc55192cb4cfeabcfa085bd2fd845c` |
| 15 | `more-itertools-strict-counted-sample` / r3 | `completed` | `validation_passed` | `0d0fef93b692e03a26c4c6681d2e604e15ede3c39946d54f7c064baf59983223` |
| 16 | `flask-ipv6-host-parsing` / r3 | `completed` | `validation_passed` | `72e08d0876c3db06766a284555230372996dc5d3f12ad8c34a5da7ec0b5f2a75` |
| 17 | `p-queue-abort-listener-cleanup` / r3 | `incomplete` | `runner_failed_without_result` | `8524dbe688dd997e4d991639f4ae3a6404a1bb14c32de75b97c4c70552bd5e44` |
| 18 | `commons-codec-phonetic-boundaries` / r3 | `completed` | `candidate_stopped` | `6be8456bfa0f68e6ef82674140e76bb091e6cadd02a2c881ca57da02cd673739` |

## Incomplete cells and usage bounds

All 3 usage-unknown cells are classified as `runner_failed_without_result`. Their retained legacy failure artifacts do not contain trustworthy request counters. The report therefore keeps 30 observed attempts as the minimum and adds 9 frozen possible attempts as the upper-bound allowance, producing `30-39` rather than treating unknown usage as zero.

## Public safety boundary

The public matrix and this report retain only campaign identity, hashes, bounded counters, task/cell status, classifications, aggregate scores and explicit interpretation boundaries. They exclude:

- API credentials and environment-file contents;
- prompts, model responses and candidate source;
- raw or sanitized subprocess stdout/stderr;
- local checkout, interpreter and user-profile paths;
- raw failure messages.

The source cell artifacts remain retained separately and hash-bound by the run manifest. This public view is an integrity-linked campaign report, not a self-contained redistribution of every model and subprocess artifact.

## Interpretation boundaries

- The campaign measures one frozen model, harness revision, six-task set, execution order and request cap.
- `validation_passed` is an automated task-contract result, not manual acceptance, upstream readiness or production equivalence.
- The 9/18 automated result is not a general coding-agent success-rate estimate.
- Incomplete cells remain visible and contribute to the planned denominator.
- Reported tokens come from retained provider metadata; no token-derived cost is claimed because this campaign lacks a complete frozen cost basis.
- The candidate-informed adversarial follow-up is excluded from this independent six-task campaign.
