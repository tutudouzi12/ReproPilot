# Humanize `naturalsize` rounding rollover

This task replays the real defect fixed by [`python-humanize/humanize` PR #329](https://github.com/python-humanize/humanize/pull/329). It pins the repository at base commit `976484a655df046aa6849f440a4f0cd44fc4918c`, before the fix, where values such as `999999` bytes render as `1000.0 kB` instead of carrying to `1.0 MB`.

The upstream change is MIT-licensed and modifies `src/humanize/filesize.py`; its added regression cases are split between the public and hidden ReproPilot contracts. Ordinary exact-unit and maximum-suffix cases remain in the evaluators to detect broad regressions. The historical fix commit `4a7537012fe28aa70270000d1bdcfd08c820e188` is provenance for human review only and is not included in the candidate proposer context.

## Prepare the frozen checkout

```powershell
git clone --no-checkout https://github.com/python-humanize/humanize.git <checkout>
git -C <checkout> checkout --detach 976484a655df046aa6849f440a4f0cd44fc4918c

py -3.11 -m venv <venv>
<venv>\Scripts\python.exe -m pip install -e <checkout> `
  pytest==9.1.1 freezegun==1.5.5 `
  pytest-benchmark==5.2.3 pytest-codspeed==5.0.3
```

The editable installation only supplies distribution metadata and upstream test dependencies. ReproPilot prepends the materialized workspace `src` directory to `PYTHONPATH`, so baseline and candidate commands execute the pinned or patched workspace source rather than the installation checkout.

## Reproduce the retained baseline

```powershell
py -3.11 scripts\run_repository_baseline.py `
  --task-dir examples\autoresearch\repository-scale\humanize-naturalsize-rounding `
  --checkout <checkout> `
  --python <venv>\Scripts\python.exe `
  --output examples\autoresearch\repository-scale\humanize-naturalsize-rounding\baseline.json
```

The task replays one historical bug fix; it is not an official Humanize benchmark and does not claim that a contract-passing candidate is identical to the upstream maintainer patch.
