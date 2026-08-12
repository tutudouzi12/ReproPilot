# Governed AutoResearch

ReproPilot AutoResearch converts repeated model-driven code editing into a bounded, auditable experiment. The model proposes hypotheses and complete replacements for authorized files; deterministic Python code owns validation, writes, execution, scoring, rollback and acceptance.

## Execution graph

```text
Repository discovery
→ exact revision checkout
→ ResearchSpec freeze
→ dependency resolution and isolated runtime
→ baseline and bounded candidate trials
→ fresh public replay or model-hidden holdout
```

The Planner always emits the same eight safety-critical nodes. An uploaded `autoresearch.spec/v1` file takes precedence over generic JSON Benchmark routing.

## Frozen contract

`ResearchSpec` declares:

- the exact 40- or 64-character repository commit;
- up to eight existing editable files and protected evaluator/data files;
- allowlisted argument-array commands, metric path and maximize/minimize direction;
- minimum improvement, optional target score, trial count and wall-time budget;
- one to five search repetitions with `mean`, `median` or direction-aware `worst` aggregation;
- optional hidden holdout, one to five fresh validation runs and bounded package dependencies.

Freezing normalizes paths, rejects symlinks and editable/evaluator overlap, hashes protected files and fingerprints every non-editable workspace file. The frozen spec is itself bound by SHA-256 and must match both the requested and checked-out repository commit.

## Candidate and validation boundary

The candidate model receives editable source, the public part of the spec, baseline/best scores and bounded feedback from recent rejected trials. It does not receive the holdout command, protected-file list or hidden evaluator source.

Each candidate may replace at most three authorized existing files. Guards and the evaluator run in the prepared Docker runtime. A candidate is kept only if all repetitions succeed and the frozen aggregation improves by `min_delta`; otherwise the previous best snapshot is restored. Persistent modification of protected or other non-editable files aborts the campaign and restores the original workspace snapshot.

Final validation does not call the candidate model. It rechecks the spec, TrialLedger ownership, candidate hashes and protected workspace before and after fresh command processes. With a holdout, the candidate must improve over the frozen holdout baseline; without one, the result is explicitly labeled `public_replay` rather than hidden validation.

## Artifacts

| Artifact | Meaning |
|---|---|
| `research_spec` | Frozen version, paths, commands, budgets and integrity hashes |
| `research_trial_ledger` | Baseline and trial hypotheses, metrics, samples, patches, decisions and stop reason |
| `research_best_candidate` | Best score and final editable-file hashes |
| `research_validation_report` | Fresh scores, mode, pass/fail, candidate integrity and protected-file integrity |
| `validated_research_metrics` | Metric published only after final validation passes |

The existing ReproPilot Execution Inspector renders TrialLedger and validation reports inside its Artifact Preview, using the same layout tokens and interaction hierarchy as other research objects.

`research_trial_ledger.model_usage` records the provider host, model, request count and provider-reported prompt, completion and total tokens. Usage is recorded before candidate-contract validation, so a paid response that is later rejected still remains visible. `reported_request_count` distinguishes responses with token metadata from compatible providers that omit it.

## Validation boundary

Unit and API tests cover contract freezing, exact revision routing, hidden-context redaction, repeated aggregation, Keep/Reject, regression rollback, protected-file restoration, spec/ledger binding and final hash failure. These tests do not prove a live provider or real Docker campaign. A resume claim about external repository AutoResearch requires a separately recorded real-model, real-container run.

The first recorded live campaign used DashScope `qwen3-coder-plus` against pinned ReproPilot commit `7d5120eb81a3f9fcd0bca690a3f204f435ba39e2`. All eight DAG nodes completed. The public baseline improved from `0.6667` to `1.0`; model-hidden holdout validation returned `1.0` in three fresh runs with candidate and protected-file integrity intact. The ledger recorded two provider-reported requests (`1794` prompt, `443` completion and `2237` total tokens), and all task containers were removed afterward. This bounded fixture proves the execution and governance path, not performance on a large research workload.
