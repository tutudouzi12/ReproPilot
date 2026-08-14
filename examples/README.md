# Examples

本目录提供可直接运行、带验收条件的 ReproPilot 示例。每次运行会生成独立摘要，作为本次环境的执行证据。

| Example | Flow | Runtime | Status |
|---|---|---|---|
| [Attention paper reproduction](paper-reproduction/) | API -> Planner -> Scheduler -> Agents -> Docker Sandbox -> Artifacts | CPU smoke; GPU passthrough optional | Run locally |
| [Bounded AutoResearch](autoresearch/minimal/) | Exact revision -> frozen spec -> repeated trials -> hidden validation | CPU + configured model | Live result summary included |
| [Evaluation scenario suite](autoresearch/evaluation-suite/) | Fixed inputs -> baseline -> Keep/Reject -> hidden validation -> evidence bundle | CPU; model optional | Seven deterministic scenarios in CI |

示例用于验证产品执行链，不等同于论文的完整训练复现。每个示例都会明确说明运行边界、
成功条件和证据边界。
