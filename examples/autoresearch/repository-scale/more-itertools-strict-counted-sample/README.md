# more-itertools strict counted sample exhaustion

This task replays the effective defect fix from [`more-itertools/more-itertools` PR #944](https://github.com/more-itertools/more-itertools/pull/944). It pins the repository at merge commit `7b9889c0b7de2189e7dd77688f7a811ce43337cc`'s first parent, `18225d856665bfc3bfdfcdbfa585290f92645daf`, where `sample(..., counts=..., strict=True)` can silently return an undersized sample because the strict-size check is inside a `suppress(StopIteration)` block.

The pull request head `b37b401fcac99e741a37e46fde0239e6e9aea02f` and merge commit are provenance for human review only. Comparing the pinned base with the merge commit isolates the effective two-file `+20/-2` change shown by the merged pull request; comparing the base directly with the topic head would incorrectly include unrelated changes from their earlier common ancestor.

## Prepare the frozen checkout

```powershell
git clone --no-checkout https://github.com/more-itertools/more-itertools.git <checkout>
git -C <checkout> checkout --detach 18225d856665bfc3bfdfcdbfa585290f92645daf

py -3.11 -m venv <venv>
```

The pinned suite and evaluators use only the Python standard library. They run from the materialized repository root, so no editable installation is required.

The pinned base runs `825` upstream tests with one skip. The provenance-only merge checkout runs `826` tests with one skip and passes both ReproPilot evaluators at `6/6`; the pinned base is retained at public `4/6` and hidden `1/6`.

## Reproduce the retained baseline

```powershell
py -3.11 scripts\run_repository_baseline.py `
  --task-dir examples\autoresearch\repository-scale\more-itertools-strict-counted-sample `
  --checkout <checkout> `
  --python <venv>\Scripts\python.exe `
  --output examples\autoresearch\repository-scale\more-itertools-strict-counted-sample\baseline.json
```

The task replays one historical bug fix; it is not an official more-itertools benchmark and does not claim that a contract-passing candidate is identical to the maintainer patch.
