# Flask bracketed IPv6 host parsing

This task replays the defect reported in [`pallets/flask` issue #6093](https://github.com/pallets/flask/issues/6093) and fixed by [pull request #6096](https://github.com/pallets/flask/pull/6096). It pins the repository at merge commit `05e9c6bd630ecf4ec0ec884b1fc7901663737bc7`'s first parent, `514fc6b3e8402e4c646d5284e97a4f0ab50a7c4b`, where colon-based splitting mishandles bracketed IPv6 hosts in two production paths.

In `src/flask/testing.py`, an IPv6 test-client host produces the wrong cookie domain, so a value written through `session_transaction()` is not returned on the next request. In `src/flask/app.py`, an IPv6 `SERVER_NAME` is split inside the address and can raise while converting the resulting port fragment. Both files are editable; the upstream tests and ReproPilot evaluators remain outside the editable scope.

The public contract combines ordinary hostname controls with loopback IPv6 cases. The hidden holdout uses IPv4, explicit port zero, a full IPv6 documentation address, and bracketed IPv6 without a port. This split rejects a patch that special-cases only `[::1]` while preserving ordinary host behavior.

## Prepare the frozen checkout

```powershell
git clone --no-checkout https://github.com/pallets/flask.git <checkout>
git -C <checkout> checkout --detach 514fc6b3e8402e4c646d5284e97a4f0ab50a7c4b

py -3.11 -m venv <venv>
<venv>\Scripts\python.exe -m pip install -e <checkout> `
  pytest==9.1.1 asgiref==3.12.1 python-dotenv==1.2.3 `
  Werkzeug==3.1.8 blinker==1.9.0 click==8.4.2 `
  itsdangerous==2.2.0 Jinja2==3.1.6 MarkupSafe==3.0.3
```

The editable installation supplies distribution metadata and test dependencies. ReproPilot prepends the materialized workspace `src` directory to `PYTHONPATH`, so evaluator and guard commands execute the pinned or candidate workspace source.

The clean pinned base runs `491` upstream tests. It scores public `2/4` and hidden `2/5`. The provenance-only merge checkout runs `493` upstream tests and scores public `4/4` and hidden `5/5`.

## Reproduce the retained baseline

```powershell
py -3.11 scripts\run_repository_baseline.py `
  --task-dir examples\autoresearch\repository-scale\flask-ipv6-host-parsing `
  --checkout <checkout> `
  --python <venv>\Scripts\python.exe `
  --output examples\autoresearch\repository-scale\flask-ipv6-host-parsing\baseline.json
```

The pull request head `7203feabf723edae0286ae5dc64fec8ac4c91735` and merge commit are provenance for human review only. They are not included in candidate proposer context. This task is not an official Flask benchmark, and a contract pass does not claim semantic equivalence with the maintainer patch or complete IPv6 correctness.
