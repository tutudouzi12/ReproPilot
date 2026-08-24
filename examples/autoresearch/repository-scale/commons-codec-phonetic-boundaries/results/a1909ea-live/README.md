# Commons Codec live attempt packaging failure

The live evaluation reached artifact packaging under harness revision `a1909eacb4bb5a4203fa1516b32d3a0bcdc4e3bb`, then failed while retaining the nested `PhoneticEngine.java` initial source on Windows. The target repository evaluation did not produce a durable `result.json`, `model-responses.json`, token count, or candidate patch.

This directory is retained as a harness failure, not classified as a model repair failure and not included in aggregate benchmark results. No request count or cost is inferred from the missing in-memory state.

The follow-up harness change shortens long retained editable-source paths using a stable hash prefix while preserving the original repository path in `candidate.patch`, `frozen-spec.json`, and `result.json`.
