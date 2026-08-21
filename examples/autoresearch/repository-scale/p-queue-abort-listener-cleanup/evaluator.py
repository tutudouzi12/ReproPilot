from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


COMMON_JAVASCRIPT = r"""
const {default: PQueue} = await import('./source/index.ts');
const delay = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));

class TrackingSignal {
  aborted = false;
  reason = undefined;
  #listeners = new Set();

  throwIfAborted() {
    if (this.aborted) {
      throw this.reason;
    }
  }

  addEventListener(type, listener) {
    if (type === 'abort') {
      this.#listeners.add(listener);
    }
  }

  removeEventListener(type, listener) {
    if (type === 'abort') {
      this.#listeners.delete(listener);
    }
  }

  abort(reason = new Error('aborted')) {
    this.aborted = true;
    this.reason = reason;
    for (const listener of [...this.#listeners]) {
      listener();
    }
    this.#listeners.clear();
  }

  get listenerCount() {
    return this.#listeners.size;
  }
}

const execute = async (name, function_) => {
  try {
    const details = await function_();
    return {name, passed: true, ...details};
  } catch (error) {
    return {name, passed: false, error: `${error?.name ?? 'Error'}: ${error?.message ?? String(error)}`};
  }
};
"""


PUBLIC_CASES = r"""
const cases = {
  async successCleanup() {
    const signal = new TrackingSignal();
    const queue = new PQueue();
    const value = await queue.add(async () => 42, {signal});
    if (value !== 42 || signal.listenerCount !== 0) {
      throw new Error(`value=${value} listeners=${signal.listenerCount}`);
    }
    return {observed: {value, listeners: signal.listenerCount}};
  },
  async rejectionCleanup() {
    const signal = new TrackingSignal();
    const queue = new PQueue();
    let message = '';
    try {
      await queue.add(async () => { throw new Error('task failed'); }, {signal});
    } catch (error) {
      message = error.message;
    }
    if (message !== 'task failed' || signal.listenerCount !== 0) {
      throw new Error(`message=${message} listeners=${signal.listenerCount}`);
    }
    return {observed: {message, listeners: signal.listenerCount}};
  },
  async preAbortedControl() {
    const signal = new TrackingSignal();
    signal.abort(new Error('already aborted'));
    const queue = new PQueue();
    let message = '';
    try {
      await queue.add(async () => 1, {signal});
    } catch (error) {
      message = error.message;
    }
    if (message !== 'already aborted' || signal.listenerCount !== 0) {
      throw new Error(`message=${message} listeners=${signal.listenerCount}`);
    }
    return {observed: {message, listeners: signal.listenerCount}};
  },
  async noSignalControl() {
    const queue = new PQueue({concurrency: 1});
    const value = await queue.add(async () => 7);
    if (value !== 7 || queue.pending !== 0 || queue.size !== 0) {
      throw new Error(`value=${value} pending=${queue.pending} size=${queue.size}`);
    }
    return {observed: {value, pending: queue.pending, size: queue.size}};
  },
};
const selected = ['successCleanup', 'rejectionCleanup', 'preAbortedControl', 'noSignalControl'];
"""


def _run(command: list[str], timeout_seconds: float = 150) -> dict[str, Any]:
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=Path.cwd(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
        return {
            "command": command,
            "exit_code": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "duration_ms": int((time.monotonic() - started) * 1000),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "command": command,
            "exit_code": 124,
            "stdout": exc.stdout or "",
            "stderr": f"{exc.stderr or ''}\ncommand timed out after {timeout_seconds:.2f}s".strip(),
            "duration_ms": int((time.monotonic() - started) * 1000),
        }


def evaluate_cases(case_source: str) -> dict[str, Any]:
    trailer = r"""
const results = [];
for (const name of selected) {
  results.push(await execute(name, cases[name]));
}
const passed = results.filter(result => result.passed).length;
console.log(JSON.stringify({passed, total: results.length, cases: results}));
"""
    result = _run(
        [
            "node",
            "--import=tsx/esm",
            "--input-type=module",
            "--eval",
            COMMON_JAVASCRIPT + case_source + trailer,
        ],
        timeout_seconds=30,
    )
    if result["exit_code"] != 0:
        raise RuntimeError(result["stderr"] or result["stdout"] or "Node evaluator failed")
    payload = json.loads(result["stdout"].strip().splitlines()[-1])
    payload["metrics"] = {"listener_cleanup_score": payload["passed"] / payload["total"]}
    return payload


def upstream_checks() -> dict[str, Any]:
    commands = {
        "node_functional_tests": ["node", "--import=tsx/esm", "--test", "test/*.ts"],
        "typescript_compile": ["node", "node_modules/typescript/bin/tsc", "--pretty", "false"],
        "type_definition_tests": ["node", "node_modules/tsd/dist/cli.js"],
    }
    checks: dict[str, Any] = {}
    passed = True
    for name, command in commands.items():
        result = _run(command)
        summary: dict[str, Any] = {
            "command": result["command"],
            "exit_code": result["exit_code"],
            "duration_ms": result["duration_ms"],
        }
        if name == "node_functional_tests":
            for key in ("tests", "pass", "fail", "skipped"):
                match = re.search(rf"^# {key} (\d+)$", result["stdout"], re.MULTILINE)
                summary[key] = int(match.group(1)) if match else None
        if result["exit_code"] != 0:
            passed = False
            summary["stdout_tail"] = result["stdout"][-4000:]
            summary["stderr_tail"] = result["stderr"][-4000:]
        checks[name] = summary
    return {"upstream_checks_passed": passed, "checks": checks}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream", action="store_true")
    args = parser.parse_args()
    if args.upstream:
        payload = upstream_checks()
        print(json.dumps(payload, ensure_ascii=False))
        return 0 if payload["upstream_checks_passed"] else 1
    print(json.dumps(evaluate_cases(PUBLIC_CASES), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
