# p-queue abort-listener cleanup

This task replays the resource-cleanup defect fixed by [`sindresorhus/p-queue` pull request #235](https://github.com/sindresorhus/p-queue/pull/235). It pins the repository at the pull request base, `5e400174a89395a44399713191b76544cf743fe5`, where each queued operation with an `AbortSignal` registers a listener that remains attached after normal completion, rejection, or timeout.

Only `source/index.ts` is editable. The public evaluator checks successful and rejected operations together with pre-aborted and no-signal controls. The hidden holdout exercises repeated sequential work, concurrent work, timeout cleanup, in-flight abort, and a no-signal control. The split exposes listener accumulation without giving the candidate the full boundary set.

## Prepare the frozen checkout

```powershell
git clone --no-checkout https://github.com/sindresorhus/p-queue.git <checkout>
git -C <checkout> checkout --detach 5e400174a89395a44399713191b76544cf743fe5

Push-Location <checkout>
npm install --ignore-scripts --no-audit --no-fund --no-save --package-lock=false `
  @sindresorhus/tsconfig@8.1.0 @types/benchmark@2.1.5 @types/node@24.13.3 `
  benchmark@2.1.4 del-cli@6.0.0 delay@6.0.0 eventemitter3@5.0.4 `
  in-range@3.0.0 p-defer@4.0.1 p-timeout@7.0.1 random-int@3.1.0 `
  time-span@5.1.0 tsd@0.33.0 tsx@4.23.12 typescript@5.9.3 xo@1.2.3
Pop-Location
```

The upstream repository sets `package-lock=false`. The retained baseline therefore records the exact observed top-level package versions, but it is not a transitive dependency lock.

## Selected upstream checks

The pinned base passes all `129` Node functional tests plus `tsc` and `tsd`. The provenance-only fix commit `f444dce7a802cc76c4a80627b6aaafb284f9a27c` passes `130` functional tests plus the same type checks and moves the evaluator scores from public `2/4` and hidden `2/5` to public `4/4` and hidden `5/5`.

The repository's default `npm test` also invokes XO. On this Windows environment, XO exits before functional tests because its TypeScript project service does not locate the repository test files. The retained command set excludes that environment-specific lint failure and must not be described as the complete default `npm test` command.

## Reproduce the retained baseline

```powershell
py -3.11 scripts\run_repository_baseline.py `
  --task-dir examples\autoresearch\repository-scale\p-queue-abort-listener-cleanup `
  --checkout <checkout> `
  --python <python.exe> `
  --output examples\autoresearch\repository-scale\p-queue-abort-listener-cleanup\baseline.json
```

The pull request head and merge commit are provenance for human review only and are not included in candidate proposer context. This is not an official p-queue benchmark, and a contract pass does not claim semantic equivalence with the maintainer patch, complete resource-leak freedom, or upstream readiness.
