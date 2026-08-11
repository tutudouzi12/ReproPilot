# ReproPilot 用户手册

ReproPilot 将科研目标转换为可执行 DAG，并由 Librarian、Coder、Research Coding、Sandbox 和 Data Agent 协作完成。工作台同时展示计划状态、节点日志、代码、指标和 Artifact。

## 创建任务

在对话区输入自然语言目标。常见入口包括：

- 论文复现：`使用指定仓库对 Attention Is All You Need 做 smoke 复现和两组消融。`
- 框架评测：`比较 LangChain 和 LlamaIndex 在同一 RAG 场景的运行结果。`
- 自有数据 Benchmark：先上传 CSV/TSV/JSON/JSONL，再说明输入列、标签列和样本上限。
- 普通代码执行：`生成并运行一个计算均值的 Python 实验。`

Planner 会显示节点依赖、执行 Agent、输入输出 Artifact、超时、重试和预算。Full reproduction 或管理员强制配置的高风险计划需要先审批。

## 论文复现链路

典型链路包括：

```text
解析论文 -> 冻结 Claim Rubric -> 发现仓库 -> 准备工作区
-> 解析依赖 -> 准备 Sandbox -> 安装依赖 -> 执行实验
-> 对比论文主张 -> 构建 Claim-to-Evidence Graph
```

建议先使用 `smoke` 模式验证端到端链路。`full` 模式会经过资源决策和审批，不满足资源要求时自动降级或阻止执行。

## 自有数据 Benchmark

支持 CSV、TSV、JSON 和 JSONL。系统会：

1. 校验附件所有权和 SHA-256。
2. 推断数据列与类型，生成稳定数据契约。
3. 为目标仓库生成边界受限的 Adapter。
4. 最多进行三轮小样本预检和修复。
5. 正式运行并逐条校验预测。
6. 根据预测重新计算指标，拒绝伪造或不一致的汇总结果。

上传文件的本地存储路径和文本摘录只在 Backend 内部使用，不会出现在计划 API 响应中。

## 执行状态与恢复

节点状态包括 `pending`、`ready`、`in_progress`、`completed`、`failed`、`blocked` 和 `canceled`。事件流会推送：

- `task_ready` / `task_started`
- `task_log`
- `artifact_created`
- `task_completed` / `task_failed` / `task_blocked`
- `plan_completed` / `plan_failed` / `plan_canceled`

刷新页面或断线重连后，SSE 会回放已持久化的历史事件。Backend 重启时，中断节点会回到可运行状态并清除旧租约；任务转交、取消或重试后，旧执行结果无法覆盖新状态。

## 失败处理

- `Retry`：对失败、阻塞或取消的节点重新排队。
- `Reassign`：切换执行 Agent，同时使旧 `execution_id/epoch/lease` 失效。
- `Cancel`：取消所有未完成节点；终态计划不能再次取消。
- 依赖修复：识别缺失包、标准库误报和 Python 版本不兼容，最多进行受限恢复。
- 论文代码修复：只允许修改模型已看到的工作区文件；策略校验失败或预算耗尽时恢复原文件。

## 安全边界

- API 可配置静态 Bearer Token，计划和上传按用户所有权隔离。
- PDF 代理只允许受信域名，连接到预先验证的公网 IP，并保留原域名 TLS 校验。
- Sandbox 默认关闭网络，限制 CPU、内存和 PID，丢弃 Linux capabilities，并启用 `no-new-privileges`。
- 镜像和挂载路径必须在白名单内；命令有超时和 UTF-8 安全输出截断。
- Docker socket 仍具有较高宿主机权限，本项目适合受控单机环境，不等同于生产级多租户隔离。

## 严格模式与离线演示

系统默认采用严格模式。未配置模型密钥、真实仓库或 Sandbox 时，依赖这些能力的任务会失败并触发正常重试、失败传播和下游阻塞。

只有显式设置 `OFFLINE_DEMO_MODE=true` 才会生成联调用占位结果。此类结果包含 `evidence_status=unverified_demo`；代码未实际运行时 `executed=false` 且 `exit_code=null`。报告和 Claim-to-Evidence 构建会排除这些产物，因此不能把演示链路表述为真实论文结论、框架评测或 Benchmark 证据。

前端会把这类节点显示为紫色“演示·未验证”，并单独统计，不计入绿色“已验证完成”；直接执行接口返回失败状态时会显示错误，不再把失败结果标成完成。
