# ReproPilot multi-repository pilot benchmark results

- Evidence snapshot: `2026-08-20T05:47:10Z`
- Benchmark: `repository-scale-pilot-v1`
- Tasks / independent tasks / unique repositories: `5` / `4` / `4`
- Retained runs: `8`

## Selected primary metrics

| Metric | Value |
| --- | ---: |
| Automated contract pass rate | 4/4 (1.0000) |
| Manual acceptance rate | 2/4 (0.5000) |
| Manual pass@1 | 2/4 (0.5000) |
| Chronological first-run automated pass@1 | 1/4 (0.2500) |
| Chronological first-run manual pass@1 | 1/4 (0.2500) |
| Mean public-to-hidden gap | 0 |

> Selected primary runs are post-development release-evidence selections. Chronological first-run metrics are shown separately so earlier failures are not hidden.

## Selected primary runs

| Task | Run | Automated | Manual review | Public -> hidden | Attempts | Tokens | Cost |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: |
| `rank-bm25-boundary-robustness` | [`66b1b7a-live`](rank-bm25-boundary-robustness/results/66b1b7a-live/) | `validation_passed` | `accept_with_boundary` | 1 -> 1 | 1 | 7176 | 0.0717 CNY |
| `humanize-naturalsize-rounding` | [`6511078-live`](humanize-naturalsize-rounding/results/6511078-live/) | `validation_passed` | `accept_with_boundary` | 1 -> 1 | 1 | 3387 | 0.033132 CNY |
| `more-itertools-strict-counted-sample` | [`c261d99-live`](more-itertools-strict-counted-sample/results/c261d99-live/) | `validation_passed` | `reject` | 1 -> 1 | 1 | 10359 | 0.050724 CNY |
| `flask-ipv6-host-parsing` | [`7ec8f6e-live`](flask-ipv6-host-parsing/results/7ec8f6e-live/) | `validation_passed` | `reject` | 1 -> 1 | 3 | 35392 | 0.169744 CNY |

## Manually accepted pass efficiency

- Accepted primary runs: `2`
- Mean requests per pass: `1`
- Mean reported tokens per pass: `5281.5`
- Mean token-derived cost per pass: `0.052416 CNY`

## Adversarial follow-up

- `more-itertools-strict-counted-sample-adversarial/d7ad05b-live`: `hidden_validation_failed`, manual `reject`, hidden `0.9`.

## Retained evidence distribution

| Review classification | Runs |
| --- | ---: |
| `contract_pass_review_accepted` | 2 |
| `guard_rejection_then_provider_failures` | 1 |
| `hidden_validation_failed` | 2 |
| `manual_review_rejected_after_contract_pass` | 2 |
| `provider_requests_failed_no_candidate` | 1 |

Retained attempts / completed responses / usage reports / reported tokens: `16` / `11` / `11` / `114488`.

Known token-derived cost: `0.609384 CNY` across `6` runs; `2` runs lack complete cost data.

## Reporting boundaries

- Selected primary metrics are based on post-development run selection and are not an unbiased estimate of general software-engineering performance.
- Chronological first-run metrics are reported separately so earlier failures remain visible.
- The adversarial follow-up reuses more-itertools and is excluded from independent task and unique-repository counts.
- Manual acceptance means the retained review accepts the run as bounded benchmark evidence; it does not claim upstream readiness or production equivalence.
- This pilot contains five tasks across four unique repositories and is not a statistically representative software-engineering benchmark.
- The candidate-informed adversarial follow-up reuses the more-itertools base and must not be counted as an independent repository sample.
- Historical bug provenance and ReproPilot-authored boundary contracts are labeled separately and must not be aggregated without retaining that distinction.
- A contract pass does not establish equivalence with an upstream maintainer patch or production readiness.
- Model cost is token-derived from caller-supplied public rates and is not a billing receipt.
