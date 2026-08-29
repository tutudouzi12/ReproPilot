# Examples

本目录提供可直接运行、带验收条件的 ReproPilot 示例。每次运行会生成独立摘要，作为本次环境的执行证据。

| Example | Flow | Runtime | Status |
|---|---|---|---|
| [fastText AG News bounded reproduction](paper-reproduction/fasttext-ag-news/) | Frozen claim -> official source/data -> Docker trials -> deterministic verdict -> evidence bundle | CPU; no model API | `92.433%`, `+1.133 pp`, verified |
| [Attention paper reproduction smoke](paper-reproduction/) | API -> Planner -> Scheduler -> Agents -> Docker Sandbox -> Artifacts | CPU smoke; GPU passthrough optional | Structural smoke only |
| [Bounded AutoResearch](autoresearch/minimal/) | Exact revision -> frozen spec -> repeated trials -> hidden validation -> Assessment | CPU + configured model | [One product-chain run](autoresearch/minimal/results/2026-08-29-product-assessment-e2e/): `0.6667` -> `1.0`, verified |
| [Evaluation scenario suite](autoresearch/evaluation-suite/) | Fixed inputs -> baseline -> Keep/Reject -> hidden validation -> evidence bundle | CPU; model optional | Seven deterministic scenarios in CI |

示例用于验证产品执行链，不自动等同于论文的完整训练复现。fastText 案例验证一条冻结的数值主张；Attention 示例只验证结构链路。每个示例都会明确说明运行边界、成功条件和证据边界。
