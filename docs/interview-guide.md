# ReproPilot interview guide

## 项目定位

ReproPilot 是一个面向论文、仓库和数据实验的多 Agent 研究执行系统。它将用户目标编译为可恢复 DAG，让专业 Agent 在受控环境中完成仓库准备、代码修改、隔离执行和结果验证，并将结论绑定到可审计 Artifact。

## 简历四点

- **多 Agent 可靠运行时**：基于 FastAPI 与 `asyncio` 构建契约驱动的多 Agent DAG Runtime，通过类型化 Artifact 衔接 Librarian、Coder、Research Coding、Sandbox 与 Data Agent；使用 lease、execution epoch 和原子快照支持重试、取消、重分配、崩溃恢复及迟到结果隔离。
- **受治理代码研究**：设计 Research Coding Agent / AutoResearch Harness，冻结目标仓库 revision、文件白名单、评测命令和实验预算；对候选修改执行重复测量、Keep/Reject、退化回滚与目标分数停止，并通过模型不可见 holdout 最终验收。
- **确定性评测与证据**：构建从逐样本预测独立重算指标的 Validator，通过数据哈希、运行清单、Trial Ledger 和 Claim-to-Evidence Graph 将论文主张绑定到真实 Artifact，阻止模型自报指标或无证据结论进入最终报告。
- **隔离工具执行**：实现独立 Docker Sandbox，对任务镜像、挂载、网络、CPU、内存、PID、Linux capabilities、超时和输出大小进行限制，并在成功、失败或取消后清理容器，降低第三方仓库代码执行风险。

## 30 秒介绍

我做的是一个科研场景的多 Agent 执行系统，不是聊天套壳。Planner 把论文或仓库任务拆成带 Artifact 契约的 DAG，不同 Agent 负责文献、代码、执行和数据验证；Scheduler 用 lease 和 epoch 处理长任务恢复、重试和迟到结果。模型可以提出代码候选，但真实写入、Docker 执行、指标重算、Keep/Reject 和隐藏验收都由确定性 Harness 控制，最后交付 Trial Ledger 和证据图。

## 四个常见追问

### 为什么需要多 Agent，而不是一个 Agent 加很多工具？

不同阶段的上下文、输出契约和权限风险不同。文献 Agent 不需要写仓库，Data Agent 不应决定补丁，模型也不应直接控制 Docker。多 Agent 的价值在于缩小工具权限和故障域，并用 Artifact 明确交接；不是为了增加角色数量。

### execution epoch 解决什么问题？

异步任务被取消、重试或重新分配后，旧协程可能晚于新执行返回。每次尝试绑定 execution ID、递增 epoch 和 lease owner；结果返回时重新读取持久化状态，不匹配的结果只记录 discarded 事件，不能覆盖新状态或 Artifact。

### 为什么不能相信模型输出的指标？

模型可能读取错文件、使用不同样本口径，甚至把失败解释成成功。ReproPilot 从逐样本预测重新计算指标，并把数据哈希、命令、补丁和结果写进账本。模型负责提出候选，Validator 才拥有验收权。

### hidden holdout 是否真正安全？

当前含义是候选模型上下文不可见，同时 evaluator 文件受保护并在执行前后检查哈希。它能降低针对公开 evaluator 过拟合，但不是密码学隔离或第三方独立测评；高价值任务应把 holdout 迁到独立服务。

## 不要过度表述

- 不说“生产级分布式多 Agent 平台”；当前是可靠单节点原型。
- 不说“完整复现任意论文”；成功只针对冻结任务契约。
- 不说“实现了通用 ToT 树搜索”；当前 ToT 用于受限消融候选筛选。
- 不写未经 ReproPilot 当前 Artifact 支撑的外部仓库提升、业务规模、用户量或 SLA。
