from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def load_evaluate_cases():
    directory = Path(__file__).resolve().parent
    evaluator_path = directory / "02-evaluator.py"
    if not evaluator_path.is_file():
        evaluator_path = directory / "evaluator.py"
    spec = importlib.util.spec_from_file_location("p_queue_public_evaluator", evaluator_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load evaluator: {evaluator_path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.evaluate_cases


evaluate_cases = load_evaluate_cases()


HIDDEN_CASES = r"""
const cases = {
  async sequentialSharedSignal() {
    const signal = new TrackingSignal();
    const queue = new PQueue({concurrency: 1});
    const values = [];
    for (let index = 0; index < 3; index++) {
      values.push(await queue.add(async () => index, {signal}));
    }
    if (values.join(',') !== '0,1,2' || signal.listenerCount !== 0) {
      throw new Error(`values=${values.join(',')} listeners=${signal.listenerCount}`);
    }
    return {observed: {values, listeners: signal.listenerCount}};
  },
  async parallelSharedSignal() {
    const signal = new TrackingSignal();
    const queue = new PQueue({concurrency: 2});
    const values = await Promise.all([
      queue.add(async () => 1, {signal}),
      queue.add(async () => 2, {signal}),
    ]);
    if (values.join(',') !== '1,2' || signal.listenerCount !== 0) {
      throw new Error(`values=${values.join(',')} listeners=${signal.listenerCount}`);
    }
    return {observed: {values, listeners: signal.listenerCount}};
  },
  async timeoutCleanup() {
    const signal = new TrackingSignal();
    const queue = new PQueue({timeout: 5});
    let timedOut = false;
    try {
      await queue.add(async () => delay(40), {signal});
    } catch (error) {
      timedOut = error.name === 'TimeoutError';
    }
    if (!timedOut || signal.listenerCount !== 0) {
      throw new Error(`timedOut=${timedOut} listeners=${signal.listenerCount}`);
    }
    return {observed: {timedOut, listeners: signal.listenerCount}};
  },
  async abortWhileRunning() {
    const signal = new TrackingSignal();
    const queue = new PQueue();
    const task = queue.add(async () => delay(40), {signal});
    setTimeout(() => signal.abort(new Error('cancelled')), 5);
    let message = '';
    try {
      await task;
    } catch (error) {
      message = error.message;
    }
    if (message !== 'cancelled' || signal.listenerCount !== 0) {
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
const selected = ['sequentialSharedSignal', 'parallelSharedSignal', 'timeoutCleanup', 'abortWhileRunning', 'noSignalControl'];
"""


print(json.dumps(evaluate_cases(HIDDEN_CASES), ensure_ascii=False))
