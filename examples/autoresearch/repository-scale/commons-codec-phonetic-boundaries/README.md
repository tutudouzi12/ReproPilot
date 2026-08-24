# Apache Commons Codec phonetic boundary task

This task freezes [`apache/commons-codec`](https://github.com/apache/commons-codec) at commit `41871c2cc31ebab1865736c61026d193409b30b5`, the first parent of the merged CODEC-315 repair. The pinned upstream Maven suite passes before the additional ReproPilot boundary evaluators run.

The public contract exposes apostrophe-only Sephardic inputs that trigger `ArrayIndexOutOfBoundsException` before the repair. Hidden validation separately exercises Sephardic and Ashkenazi prefix-only inputs that trigger `StringIndexOutOfBoundsException` after the intermediate word collection becomes empty. Ordinary Generic and non-prefix names remain as controls.

## Baseline

The retained baseline was recorded with CPython 3.11, Oracle JDK 8u202, and Maven 3.9.1. The evaluator supplies an isolated Maven settings file that uses Maven Central over HTTPS because the host's configured HTTP mirrors cannot resolve the historical plugin metadata. Each evaluation copies the candidate workspace to a temporary directory while excluding `.git`, `.repropilot`, and existing `target` directories; Maven and the Java probe run against that disposable copy so build artifacts cannot mutate the governed candidate workspace.

```powershell
py -3.11 scripts\run_repository_baseline.py `
  --task-dir examples\autoresearch\repository-scale\commons-codec-phonetic-boundaries `
  --checkout <pinned-commons-codec-checkout> `
  --output examples\autoresearch\repository-scale\commons-codec-phonetic-boundaries\baseline.json
```

## Preflight

```powershell
py -3.11 scripts\run_repository_evaluation.py `
  --task-dir examples\autoresearch\repository-scale\commons-codec-phonetic-boundaries `
  --checkout <pinned-commons-codec-checkout> `
  --preflight-only
```

`task.json` freezes the historical repository identity, selected Git blobs, provenance, toolchain evidence, commands, and observed scores. `autoresearch.json` permits edits only to `PhoneticEngine.java`, protects both evaluators, reruns the full Maven test phase for every candidate, and requires a fresh hidden improvement before acceptance.

This is one bounded module repair, not a full Apache Commons Codec benchmark. The hidden cases are withheld from proposer context but remain inspectable in the retained public evidence package. Passing the contract does not establish semantic equivalence with the merged maintainer patch or general Java repair capability.
