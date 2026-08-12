# ReproPilot end-to-end demo

这是一条可快速阅读的标准案例。它来自 2026-08-12 的 ReproPilot 真实产品链：真实模型提出候选，真实 Docker 容器执行冻结命令，Python Harness 决定 Keep/Reject 和最终验收。

## 0–15 秒：输入与计划

系统接收四个附件：一个带零值边界缺陷的 `candidate.py`、公开 evaluator、模型不可见 holdout evaluator，以及 `autoresearch.spec/v1`。规格固定 ReproPilot 仓库提交 `7d5120eb81a3f9fcd0bca690a3f204f435ba39e2`。

Planner 生成固定八节点 DAG：

```text
Repository discovery
→ exact revision checkout
→ ResearchSpec freeze
→ dependency resolution
→ isolated runtime
→ dependency installation
→ bounded candidate trials
→ hidden validation
```

节点分别由 Coder、Research Coding 和 Sandbox Agent 承担，依赖通过 Artifact 契约交接。

## 15–35 秒：冻结边界与 baseline

Harness 冻结以下内容：

- 精确 Git revision；
- 唯一可编辑文件；
- 两个受保护 evaluator；
- guard、公开评测和 holdout 命令；
- `3 x worst` 搜索测量、最多 3 个候选和 3 次最终验证；
- 文件与规格 SHA-256。

公开 baseline 在三个新命令序列中均得到 `0.6667`。隐藏 baseline 为 `0.3333`，但命令、源码与分数不会进入候选模型上下文。

## 35–55 秒：Reject、Keep 与回滚边界

模型共返回两次响应：

1. 第一个响应使用了非法的结构化状态值，在写文件前被契约校验拒绝；付费请求仍进入模型用量账本。
2. 第二个响应识别到 `value >= 0` 错把零计为正数，提出改为 `value > 0`。Harness 只替换授权文件，记录修改前后哈希，然后在同一冻结契约下执行三次测量。

三个候选分数均为 `1.0`，因此该候选被 Keep。它达到 `target_score=1.0` 后，Harness 确定性停止搜索；停止权不交给模型。

## 55–75 秒：隐藏验收与产物

最终验证不再调用模型。Harness 在三个新进程中运行模型不可见 holdout，得到：

```json
{
  "status": "passed",
  "validation_mode": "hidden_holdout",
  "observed_scores": [1.0, 1.0, 1.0],
  "candidate_intact": true,
  "protected_files_intact": true
}
```

最终交付包含冻结 `ResearchSpec`、Trial Ledger、最佳候选哈希、Validation Report 和通过验证的指标。八个 DAG 节点约 26 秒完成；账本记录 2 次模型请求、`2237` 个 provider-reported tokens，任务结束后没有容器残留。

## What this case proves

- 多 Agent 任务通过显式 DAG 和 Artifact 契约交接；
- 模型可以提出真实代码修改，但不能越过文件与评测边界；
- 非法输出、退化候选和隐藏验收失败不会被包装成成功；
- 最终结果由确定性执行与证据决定，而不是由模型声明。

## What it does not prove

- 该任务是刻意设计的小型边界用例，不代表大型论文复现性能；
- `hidden_holdout` 表示候选模型上下文不可见，不是密码学隔离或第三方测评；
- 单次成功案例不能支持生产 SLA、普遍代码修复率或优于其他 Agent 的结论。

可复现输入位于 [`examples/autoresearch/minimal`](../examples/autoresearch/minimal/)，脱敏结果摘要位于 [`live-result-summary.json`](../examples/autoresearch/minimal/live-result-summary.json)。实现与测试边界见 [Governed AutoResearch](autoresearch.md)。
