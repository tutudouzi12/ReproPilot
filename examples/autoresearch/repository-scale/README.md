# Repository-scale AutoResearch tasks

This directory contains bounded tasks against real, independently versioned GitHub repositories. A task is release evidence only when the repository URL, full commit SHA, selected Git-blob hashes, dependency versions, original test command, public evaluator, hidden evaluator, and observed baseline are all retained.

The local `.gitattributes` disables checkout line-ending rewriting for frozen inputs and retained artifacts so their recorded SHA256 values remain stable across Git configurations.

These tasks exercise repository acquisition and real project code. They remain bounded repair experiments rather than claims about the full upstream product or a general software-engineering benchmark.

## Pilot tasks

| Task | Provenance | Frozen repository | Baseline | Scope |
| --- | --- | --- | ---: | --- |
| [`rank-bm25-boundary-robustness`](rank-bm25-boundary-robustness/) | ReproPilot boundary contract | `dorianbrown/rank_bm25@47aa3ddf8dc1ebeb7ef4e65f2b4536af44594099` | public `5/9`, hidden `1/4` | One real module plus the upstream test suite |
| [`humanize-naturalsize-rounding`](humanize-naturalsize-rounding/) | Historical merged PR [#329](https://github.com/python-humanize/humanize/pull/329) | `python-humanize/humanize@976484a655df046aa6849f440a4f0cd44fc4918c` | public `4/6`, hidden `1/6` | One historical defect plus 701 upstream tests |
| [`more-itertools-strict-counted-sample`](more-itertools-strict-counted-sample/) | Historical merged PR [#944](https://github.com/more-itertools/more-itertools/pull/944) | `more-itertools/more-itertools@18225d856665bfc3bfdfcdbfa585290f92645daf` | public `4/6`, hidden `1/6` | Counted-sampling exception flow plus 825 upstream tests |
| [`flask-ipv6-host-parsing`](flask-ipv6-host-parsing/) | Historical merged PR [#6096](https://github.com/pallets/flask/pull/6096) | `pallets/flask@514fc6b3e8402e4c646d5284e97a4f0ab50a7c4b` | public `2/4`, hidden `2/5` | Two production modules plus 491 upstream tests |
| [`p-queue-abort-listener-cleanup`](p-queue-abort-listener-cleanup/) | Historical merged PR [#235](https://github.com/sindresorhus/p-queue/pull/235) | `sindresorhus/p-queue@5e400174a89395a44399713191b76544cf743fe5` | public `2/4`, hidden `2/5` | TypeScript async cleanup plus 129 functional tests and type checks |
| [`more-itertools-strict-counted-sample-adversarial`](more-itertools-strict-counted-sample-adversarial/) | Candidate-informed follow-up | Same pinned `more-itertools` base | public `4/6`, hidden `2/10` | Lazy-iterator non-regression; excluded from independent repository counts |

The pilot therefore contains six tasks across five unique repositories. The adversarial follow-up is retained to show how manual review hardened a missed boundary; it is not an independent repository sample and must remain separately labeled in aggregates.

## Baseline contract

`scripts/run_repository_baseline.py` refuses to score a checkout when its GitHub origin, HEAD commit, cleanliness, selected Git-blob hashes, or filtered working-tree contents differ from `task.json`. Git-blob hashing keeps the frozen identity stable across checkout line-ending policies. The runner executes the upstream tests before the project-defined public and hidden evaluators and retains portable command forms, working-directory roles, stdout, stderr, duration, Python environment, dependency versions, scores, and evidence boundaries.

The baseline runner does not call an LLM and does not claim that a repair has been produced. Candidate search and retained Keep/Reject evidence belong in a later commit after this frozen starting point is reviewable.

## Bounded live search

After the baseline task is committed, `scripts/run_repository_evaluation.py` materializes the pinned checkout in a temporary workspace, freezes the AutoResearch contract, caps provider requests, and retains the exact model responses, candidate patch, Keep/Reject ledger, hidden validation, provider token usage, and cost basis. Release evidence requires a clean harness checkout and never overwrites an existing result directory.

Use `--preflight-only` first to validate the frozen checkout and evaluator without making a provider request. Live evaluator subprocesses receive a stripped environment; they are local processes rather than a network-isolated sandbox, and the result states that boundary explicitly.

Retained live evidence is indexed under each task's `results/` directory. Follow-up model requests receive deduplicated public evaluator stdout and stderr after partial improvements or rejections; hidden evaluator commands and content remain excluded from proposer context.

## Batch preflight

[`benchmark.json`](benchmark.json) freezes task membership, provenance, aggregate metric names, and the SHA-256 values of each retained contract artifact. Prepare every pinned checkout and fixed Python environment as described by its task README, then validate all tasks without making a model request:

```powershell
py -3.11 scripts\run_repository_benchmark_preflight.py `
  --benchmark examples\autoresearch\repository-scale\benchmark.json `
  --checkout rank-bm25-boundary-robustness=<rank-checkout> `
  --python rank-bm25-boundary-robustness=<rank-python> `
  --checkout humanize-naturalsize-rounding=<humanize-checkout> `
  --python humanize-naturalsize-rounding=<humanize-python> `
  --checkout more-itertools-strict-counted-sample=<more-itertools-checkout> `
  --python more-itertools-strict-counted-sample=<more-itertools-python> `
  --checkout flask-ipv6-host-parsing=<flask-checkout> `
  --python flask-ipv6-host-parsing=<flask-python> `
  --checkout p-queue-abort-listener-cleanup=<p-queue-checkout> `
  --python p-queue-abort-listener-cleanup=<python> `
  --checkout more-itertools-strict-counted-sample-adversarial=<more-itertools-checkout> `
  --python more-itertools-strict-counted-sample-adversarial=<more-itertools-python> `
  --output <preflight-report.json>
```

The runner checks benchmark-to-task identity and contract hashes before delegating to the repository preflight. It continues across task failures, verifies the observed public and hidden scores against each frozen `baseline.json`, emits one aggregate result, and exits non-zero if any selected task fails. Retained output replaces local checkout and interpreter paths with task-scoped placeholders.

## Opt-in cross-runtime replay

[`replay.json`](replay.json) selects Flask, p-queue, and Commons Codec as representative Python, TypeScript, and Java tasks. Python and npm dependencies use exact package versions; the Maven setup pins supported Java and Maven major versions and records the exact detected toolchain. The replay runner accepts only the three built-in setup kinds as argument lists and rejects unknown setup fields; it does not execute shell text from the manifest. On a clean runner with Python 3.11, Node 22, Java 8, and Maven 3, matching the retained runtime families:

```powershell
py -3.11 scripts\run_repository_benchmark_replay.py `
  --manifest examples\autoresearch\repository-scale\replay.json `
  --workspace <empty-workspace> `
  --output <replay-report.json>
```

The opt-in `Repository benchmark replay` workflow runs weekly and through `workflow_dispatch`, configures Temurin JDK 8, uploads the report even when setup or Preflight fails, and then reflects the replay result in the job status. It does not run on pushes or pull requests. Clone, registry, and toolchain failures are labeled `setup_failed`; a clean setup whose observed score differs from the frozen baseline is labeled `preflight_failed`. No model credential is read and `model_requests` remains zero.

## Audited aggregate report

[`run-selection.json`](run-selection.json) freezes the role and SHA-256 of every retained `result.json` and `review.json`. Exactly one manually reviewed run is selected as release evidence for each independent task; earlier development runs and the candidate-informed adversarial follow-up remain visible but are not silently mixed into the same denominator.

Regenerate [`benchmark-results.json`](benchmark-results.json) and the readable [`BENCHMARK_REPORT.md`](BENCHMARK_REPORT.md) in strict mode:

```powershell
py -3.11 scripts\build_repository_benchmark_report.py `
  --benchmark examples\autoresearch\repository-scale\benchmark.json `
  --selection examples\autoresearch\repository-scale\run-selection.json `
  --json-output examples\autoresearch\repository-scale\benchmark-results.json `
  --markdown-output examples\autoresearch\repository-scale\BENCHMARK_REPORT.md `
  --strict
```

Strict mode verifies the benchmark contract hashes, selected result and review hashes, result artifact hashes, repository identity, clean harness state, normalized review decision, one-primary-run-per-independent-task rule, and complete selection of every retained result. Missing reviews, tampered artifacts, or unselected runs fail report generation.

The report separates post-development selected-run metrics from chronological first-run metrics. This exposes selection bias instead of presenting the selected `pass@1` value as a general model capability estimate.
